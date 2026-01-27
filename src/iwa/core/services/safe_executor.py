"""Safe transaction executor with retry logic and gas handling."""

import os
import time
from typing import Dict, List, Optional, Tuple, TYPE_CHECKING, Callable

from loguru import logger
from safe_eth.eth import EthereumClient
from safe_eth.safe import Safe
from safe_eth.safe.safe_tx import SafeTx
from web3 import exceptions as web3_exceptions

from iwa.core.contracts.decoder import ErrorDecoder
from iwa.core.models import Config

if TYPE_CHECKING:
    from iwa.core.chain import ChainInterface


# Simple in-memory counters for debugging
SAFE_TX_STATS = {
    "total_attempts": 0,
    "gas_retries": 0,
    "nonce_retries": 0,
    "rpc_rotations": 0,
    "final_successes": 0,
    "final_failures": 0,
}


class SafeTransactionExecutor:
    """Execute Safe transactions with retry, gas estimation, and RPC rotation."""

    DEFAULT_MAX_RETRIES = 6
    DEFAULT_RETRY_DELAY = 1.0
    GAS_BUFFER_PERCENTAGE = 1.5  # 50% buffer
    MAX_GAS_MULTIPLIER = 10  # Hard cap: never exceed 10x original estimate

    def __init__(
        self,
        chain_interface: "ChainInterface",
        max_retries: Optional[int] = None,
        gas_buffer: Optional[float] = None,
    ):
        """Initialize the executor."""
        self.chain_interface = chain_interface

        # Use centralized config with fallbacks
        config = Config().core
        self.max_retries = max_retries or config.safe_tx_max_retries
        self.gas_buffer = gas_buffer or config.safe_tx_gas_buffer

        # We also check for ETHEREUM_RPC_RETRY_COUNT for library compliance
        # but our higher level retry uses max_retries
        if os.getenv("ETHEREUM_RPC_RETRY_COUNT") is None:
            os.environ["ETHEREUM_RPC_RETRY_COUNT"] = str(self.max_retries)

    def execute_with_retry(
        self,
        safe_address: str,
        safe_tx: SafeTx,
        signer_keys: List[str],
        operation_name: str = "safe_tx",
    ) -> Tuple[bool, str, Optional[Dict]]:
        """Execute SafeTx with full retry mechanism.

        Args:
            safe_address: The address of the Safe.
            safe_tx: The Safe transaction object.
            signer_keys: List of private keys for signing.
            operation_name: Name for logging purposes.

        Returns:
            Tuple of (success, tx_hash_or_error, receipt)
        """
        last_error = None
        current_gas = safe_tx.safe_tx_gas
        base_estimate = current_gas if current_gas > 0 else 0

        for attempt in range(self.max_retries + 1):
            SAFE_TX_STATS["total_attempts"] += 1
            try:
                # 1. (Re)Create Safe client with current (possibly rotated) RPC
                safe = self._recreate_safe_client(safe_address)

                # 2. Re-estimate gas if this is a retry or first run if not set
                if attempt > 0 or current_gas == 0:
                    current_gas = self._estimate_safe_tx_gas(safe, safe_tx, base_estimate)
                    safe_tx.safe_tx_gas = current_gas
                    SAFE_TX_STATS["gas_retries"] += 1

                # 3. Simulate locally before sending
                try:
                    safe_tx.call()
                except Exception as e:
                    classification = self._classify_error(e)
                    if classification["is_revert"]:
                        reason = self._decode_revert_reason(e)
                        logger.error(f"[{operation_name}] Simulation reverted: {reason or e}")
                        # If it's a logic revert, retrying probably won't help unless it's a nonce issue
                        if not classification["is_nonce_error"]:
                            return False, f"Reverted: {reason or e}", None
                    raise

                # 4. Execute
                # Always use the first signer for execution as per existing pattern
                tx_hash_bytes = safe_tx.execute(signer_keys[0])
                tx_hash = f"0x{tx_hash_bytes.hex()}"

                # 5. Wait for receipt
                receipt = self.chain_interface.web3.eth.wait_for_transaction_receipt(tx_hash)

                status = getattr(receipt, "status", None)
                if status is None and isinstance(receipt, dict):
                    status = receipt.get("status")

                if receipt and status == 1:
                    SAFE_TX_STATS["final_successes"] += 1
                    logger.info(f"[{operation_name}] Success on attempt {attempt + 1}. Tx Hash: {tx_hash}")
                    return True, tx_hash, receipt
                else:
                    logger.error(f"[{operation_name}] Mined but failed (status 0) on attempt {attempt + 1}.")
                    raise ValueError("Transaction reverted on-chain")

            except Exception as e:
                last_error = e
                classification = self._classify_error(e)

                if attempt >= self.max_retries:
                    SAFE_TX_STATS["final_failures"] += 1
                    logger.error(f"[{operation_name}] Failed after {attempt + 1} attempts: {e}")
                    break

                strategy = "retry"
                if classification["is_nonce_error"]:
                    strategy = "nonce refresh"
                    SAFE_TX_STATS["nonce_retries"] += 1
                    safe_tx = self._refresh_nonce(safe, safe_tx)
                elif classification["is_rpc_error"]:
                    strategy = "RPC rotation"
                    SAFE_TX_STATS["rpc_rotations"] += 1
                    result = self.chain_interface._handle_rpc_error(e)
                    if not result["should_retry"]:
                        break
                elif classification["is_gas_error"]:
                    strategy = "gas increase"
                    # Gas increase happens in the next loop iteration via _estimate_safe_tx_gas

                self._log_retry(attempt + 1, e, strategy)

                delay = self.DEFAULT_RETRY_DELAY * (2**attempt)
                time.sleep(delay)

        return False, str(last_error), None

    def _estimate_safe_tx_gas(self, safe: Safe, safe_tx: SafeTx, base_estimate: int = 0) -> int:
        """Estimate gas for a Safe transaction with buffer and hard cap."""
        try:
            # Use on-chain simulation via safe-eth-py
            estimated = safe.estimate_tx_gas(safe_tx.to, safe_tx.value, safe_tx.data, safe_tx.operation)
            with_buffer = int(estimated * self.gas_buffer)

            # Apply x10 hard cap if we have a base estimate
            if base_estimate > 0:
                max_allowed = base_estimate * self.MAX_GAS_MULTIPLIER
                if with_buffer > max_allowed:
                    logger.warning(f"Gas {with_buffer} exceeds x10 cap, capping to {max_allowed}")
                    return max_allowed

            return with_buffer
        except Exception as e:
            logger.warning(f"Gas estimation failed, using fallback: {e}")
            return 500_000  # Fallback

    def _recreate_safe_client(self, safe_address: str) -> Safe:
        """Recreate Safe with current (possibly rotated) RPC."""
        ethereum_client = EthereumClient(self.chain_interface.current_rpc)
        return Safe(safe_address, ethereum_client)

    def _is_nonce_error(self, error: Exception) -> bool:
        """Check if error is due to Safe nonce conflict."""
        error_text = str(error).lower()
        return any(x in error_text for x in [
            "nonce", "gs026", "already executed", "duplicate"
        ])

    def _refresh_nonce(self, safe: Safe, safe_tx: SafeTx) -> SafeTx:
        """Re-fetch nonce and rebuild transaction."""
        current_nonce = safe.retrieve_nonce()
        logger.info(f"Refreshing Safe nonce to {current_nonce}")
        return safe.build_multisig_tx(
            safe_tx.to,
            safe_tx.value,
            safe_tx.data,
            safe_tx.operation,
            safe_tx_gas=safe_tx.safe_tx_gas,
            base_gas=safe_tx.base_gas,
            gas_price=safe_tx.gas_price,
            gas_token=safe_tx.gas_token,
            refund_receiver=safe_tx.refund_receiver,
            signatures=safe_tx.signatures,
            safe_nonce=current_nonce,
        )

    def _classify_error(self, error: Exception) -> dict:
        """Classify Safe transaction errors for retry decisions."""
        err_text = str(error).lower()
        is_rpc = self.chain_interface._is_rate_limit_error(error) or self.chain_interface._is_connection_error(error)

        return {
            "is_gas_error": any(x in err_text for x in ["gas", "out of gas", "intrinsic"]),
            "is_nonce_error": self._is_nonce_error(error),
            "is_rpc_error": is_rpc,
            "is_revert": "revert" in err_text or "execution reverted" in err_text,
        }

    def _decode_revert_reason(self, error: Exception) -> Optional[str]:
        """Attempt to decode the revert reason."""
        import re
        error_text = str(error)
        hex_match = re.search(r"0x[0-9a-fA-F]{8,}", error_text)
        if hex_match:
            try:
                data = hex_match.group(0)
                decoded = ErrorDecoder().decode(data)
                if decoded:
                    name, msg, source = decoded[0]
                    return f"{msg} (from {source})"
            except Exception:
                pass
        return None

    def _log_retry(self, attempt: int, error: Exception, strategy: str):
        """Log a retry attempt."""
        logger.warning(
            f"Safe TX attempt {attempt} failed, strategy: {strategy}. Error: {error}"
        )
