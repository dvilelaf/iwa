"""Safe transaction executor with retry logic and gas handling."""

import time
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple

from loguru import logger
from safe_eth.eth import EthereumClient, TxSpeed
from safe_eth.safe import Safe
from safe_eth.safe.safe_tx import SafeTx

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
    "signature_errors": 0,
}

# Minimum signature length (65 bytes per signature for ECDSA)
MIN_SIGNATURE_LENGTH = 65


class SafeTransactionExecutor:
    """Execute Safe transactions with retry, gas estimation, and RPC rotation."""

    DEFAULT_MAX_RETRIES = 6
    DEFAULT_RETRY_DELAY = 1.0
    GAS_BUFFER_PERCENTAGE = 1.5  # 50% buffer
    MAX_GAS_MULTIPLIER = 10  # Hard cap: never exceed 10x original estimate
    DEFAULT_FALLBACK_GAS = 500_000  # Fallback when estimation fails

    # Fee bumping for "max fee per gas less than block base fee" errors
    FEE_BUMP_PERCENTAGE = 1.30  # 30% bump per retry on fee errors
    MAX_FEE_BUMP_FACTOR = 3.0  # Cap: never bump more than 3x original

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
        self._client_cache: Dict[str, EthereumClient] = {}

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
        fee_bump_factor = 1.0  # Multiplier for EIP-1559 fees, increases on fee errors

        for attempt in range(self.max_retries + 1):
            SAFE_TX_STATS["total_attempts"] += 1
            try:
                # Prepare and execute attempt
                tx_hash = self._execute_attempt(
                    safe_address,
                    safe_tx,
                    signer_keys,
                    operation_name,
                    attempt,
                    current_gas,
                    base_estimate,
                    fee_bump_factor,
                )

                # Check receipt
                receipt = self.chain_interface.web3.eth.wait_for_transaction_receipt(tx_hash)
                if self._check_receipt_status(receipt):
                    SAFE_TX_STATS["final_successes"] += 1
                    logger.info(
                        f"[{operation_name}] Success on attempt {attempt + 1}. Tx Hash: {tx_hash}"
                    )
                    return True, tx_hash, receipt

                logger.error(
                    f"[{operation_name}] Mined but failed (status 0) on attempt {attempt + 1}."
                )
                raise ValueError("Transaction reverted on-chain")

            except Exception as e:
                updated_tx, should_retry, is_fee_error = self._handle_execution_failure(
                    e, safe_address, safe_tx, attempt, operation_name
                )
                last_error = e
                if not should_retry:
                    break

                # Update gas/nonce for next loop if needed
                safe_tx = updated_tx

                # Bump fee multiplier on fee-related errors (base fee > max fee)
                if is_fee_error and fee_bump_factor < self.MAX_FEE_BUMP_FACTOR:
                    fee_bump_factor *= self.FEE_BUMP_PERCENTAGE
                    fee_bump_factor = min(fee_bump_factor, self.MAX_FEE_BUMP_FACTOR)
                    logger.info(f"[{operation_name}] Fee bump factor increased to {fee_bump_factor:.2f}x")

                delay = self.DEFAULT_RETRY_DELAY * (2**attempt)
                time.sleep(delay)

        return False, str(last_error), None

    def _execute_attempt(
        self,
        safe_address,
        safe_tx,
        signer_keys,
        operation_name,
        attempt,
        current_gas,
        base_estimate,
        fee_bump_factor: float = 1.0,
    ) -> str:
        """Prepare client, estimate gas, simulate, and execute."""
        # 1. (Re)Create Safe client
        self._recreate_safe_client(safe_address)

        # NOTE: We do NOT modify safe_tx_gas here because the transaction is already signed.
        # The Safe tx hash includes safe_tx_gas, so changing it would invalidate all signatures.
        # Gas estimation must happen BEFORE signing in SafeService.

        # 2. Validate signatures exist before any operation
        sig_len = len(safe_tx.signatures) if safe_tx.signatures else 0
        if sig_len < MIN_SIGNATURE_LENGTH:
            SAFE_TX_STATS["signature_errors"] += 1
            raise ValueError(
                f"No valid signatures on transaction (have {sig_len} bytes, need >= {MIN_SIGNATURE_LENGTH})"
            )

        # 3. Simulate locally
        try:
            safe_tx.call()
        except Exception as e:
            classification = self._classify_error(e)
            # Signature errors (GS020, GS026) are not recoverable - fail immediately
            if classification["is_signature_error"]:
                SAFE_TX_STATS["signature_errors"] += 1
                reason = self._decode_revert_reason(e)
                logger.error(f"[{operation_name}] Signature error (not retryable): {reason or e}")
                raise e
            if classification["is_revert"] and not classification["is_nonce_error"]:
                reason = self._decode_revert_reason(e)
                logger.error(f"[{operation_name}] Simulation reverted: {reason or e}")
                raise e
            raise

        # 4. Execute
        # IMPORTANT: safe-eth-py's execute() method CLEARS signatures after execution.
        # We must backup and restore them to support retries if something goes wrong (e.g. timeout after broadcast).
        signatures_backup = safe_tx.signatures

        try:
            # Execute with appropriate gas pricing
            result = self._execute_with_gas_pricing(
                safe_tx, signer_keys[0], fee_bump_factor, operation_name
            )
            return self._extract_tx_hash(result)

        finally:
            # Restore signatures for next attempt if needed
            # (execute() clears them on lines 407-409 of safe_eth/safe/safe_tx.py)
            if safe_tx.signatures != signatures_backup:
                safe_tx.signatures = signatures_backup

    def _execute_with_gas_pricing(
        self, safe_tx: SafeTx, signer_key: str, fee_bump_factor: float, operation_name: str
    ):
        """Execute transaction with appropriate gas pricing strategy.

        If fee_bump_factor > 1.0, calculates a bumped gas price to overcome
        base fee volatility. Otherwise uses EIP-1559 FAST speed.
        """
        if fee_bump_factor > 1.0:
            bumped_gas_price = self._calculate_bumped_gas_price(fee_bump_factor)
            if bumped_gas_price:
                logger.debug(
                    f"[{operation_name}] Using bumped gas price: {bumped_gas_price} wei "
                    f"(factor: {fee_bump_factor:.2f}x)"
                )
                return safe_tx.execute(signer_key, tx_gas_price=bumped_gas_price)
            # Fallback to FAST if calculation fails
            return safe_tx.execute(signer_key, eip1559_speed=TxSpeed.FAST)
        # Default: use EIP-1559 'FAST' speed
        return safe_tx.execute(signer_key, eip1559_speed=TxSpeed.FAST)

    def _extract_tx_hash(self, result) -> str:
        """Extract transaction hash from execute() result."""
        # Handle both tuple return (tx_hash, tx) and bytes return
        tx_hash_bytes = result[0] if isinstance(result, tuple) else result

        # Handle both bytes and hex string returns
        if isinstance(tx_hash_bytes, bytes):
            return f"0x{tx_hash_bytes.hex()}"
        if isinstance(tx_hash_bytes, str):
            return tx_hash_bytes if tx_hash_bytes.startswith("0x") else f"0x{tx_hash_bytes}"
        return str(tx_hash_bytes)

    def _check_receipt_status(self, receipt) -> bool:
        """Check if receipt has successful status."""
        status = getattr(receipt, "status", None)
        if status is None and isinstance(receipt, dict):
            status = receipt.get("status")
        return status == 1

    def _handle_execution_failure(
        self,
        error: Exception,
        safe_address: str,
        safe_tx: SafeTx,
        attempt: int,
        operation_name: str,
    ) -> Tuple[SafeTx, bool, bool]:
        """Handle execution failure and determine next steps.

        Returns:
            Tuple of (updated_safe_tx, should_retry, is_fee_error)

        """
        classification = self._classify_error(error)
        is_fee_error = classification["is_fee_error"]

        if attempt >= self.max_retries:
            SAFE_TX_STATS["final_failures"] += 1
            logger.error(f"[{operation_name}] Failed after {attempt + 1} attempts: {error}")
            return safe_tx, False, is_fee_error

        strategy = "retry"
        safe = self._recreate_safe_client(safe_address)

        if classification["is_nonce_error"]:
            strategy = "nonce refresh"
            SAFE_TX_STATS["nonce_retries"] += 1
            safe_tx = self._refresh_nonce(safe, safe_tx)
        elif classification["is_rpc_error"]:
            strategy = "RPC rotation"
            SAFE_TX_STATS["rpc_rotations"] += 1
            result = self.chain_interface._handle_rpc_error(error)
            if not result["should_retry"]:
                return safe_tx, False, is_fee_error
        elif is_fee_error:
            strategy = "fee bump"
            SAFE_TX_STATS["gas_retries"] += 1
        elif classification["is_gas_error"]:
            strategy = "gas increase"
            SAFE_TX_STATS["gas_retries"] += 1

        self._log_retry(attempt + 1, error, strategy)
        return safe_tx, True, is_fee_error

    def _estimate_safe_tx_gas(self, safe: Safe, safe_tx: SafeTx, base_estimate: int = 0) -> int:
        """Estimate gas for a Safe transaction with buffer and hard cap."""
        try:
            # Use on-chain simulation via safe-eth-py
            estimated = safe.estimate_tx_gas(
                safe_tx.to, safe_tx.value, safe_tx.data, safe_tx.operation
            )
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
            return self.DEFAULT_FALLBACK_GAS

    def _recreate_safe_client(self, safe_address: str) -> Safe:
        """Recreate Safe with current (possibly rotated) RPC."""
        rpc_url = self.chain_interface.current_rpc
        if rpc_url not in self._client_cache:
            self._client_cache[rpc_url] = EthereumClient(rpc_url)
        ethereum_client = self._client_cache[rpc_url]
        return Safe(safe_address, ethereum_client)

    def _is_nonce_error(self, error: Exception) -> bool:
        """Check if error is due to Safe nonce conflict."""
        error_text = str(error).lower()
        # GS025 = Invalid nonce (NOT GS026 which is invalid signatures)
        return any(x in error_text for x in ["nonce", "gs025", "already executed", "duplicate"])

    def _is_signature_error(self, error: Exception) -> bool:
        """Check if error is due to invalid Safe signatures.

        GS020 = Signatures data too short
        GS021 = Invalid signature data pointer
        GS024 = Invalid contract signature
        GS026 = Invalid owner (signature from non-owner)
        """
        error_text = str(error).lower()
        return any(
            x in error_text
            for x in [
                "gs020",
                "gs021",
                "gs024",
                "gs026",
                "invalid signatures",
                "signatures data too short",
            ]
        )

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
            # Note: signatures are NOT copied - tx hash changes with new nonce
            safe_nonce=current_nonce,
        )

    def _classify_error(self, error: Exception) -> dict:
        """Classify Safe transaction errors for retry decisions."""
        err_text = str(error).lower()
        is_rpc = self.chain_interface._is_rate_limit_error(
            error
        ) or self.chain_interface._is_connection_error(error)

        # Fee-specific errors: base fee jumped above our max fee
        fee_error_signals = [
            "max fee per gas less than block base fee",
            "maxfeepergas",
            "fee too low",
            "underpriced",
        ]
        is_fee_error = any(signal in err_text for signal in fee_error_signals)

        return {
            "is_gas_error": any(x in err_text for x in ["gas", "out of gas", "intrinsic"]),
            "is_fee_error": is_fee_error,
            "is_nonce_error": self._is_nonce_error(error),
            "is_rpc_error": is_rpc,
            "is_revert": "revert" in err_text or "execution reverted" in err_text,
            "is_signature_error": self._is_signature_error(error),
        }

    def _calculate_bumped_gas_price(self, bump_factor: float) -> Optional[int]:
        """Calculate a bumped gas price based on current base fee.

        Uses legacy gas price (not EIP-1559) for compatibility with safe-eth-py's
        tx_gas_price parameter. The bumped price ensures we're above the current
        base fee even if it's volatile.

        Args:
            bump_factor: Multiplier to apply to the base fee (e.g., 1.3 = 30% bump)

        Returns:
            Gas price in wei, or None if calculation fails

        """
        try:
            web3 = self.chain_interface.web3
            latest_block = web3.eth.get_block("latest")
            base_fee = latest_block.get("baseFeePerGas")

            if base_fee is not None:
                # EIP-1559 chain: calculate bumped max fee
                # base_fee * bump_factor * 1.5 (extra buffer) + priority fee
                priority_fee = max(int(web3.eth.max_priority_fee), 1)
                bumped_fee = int(base_fee * bump_factor * 1.5) + priority_fee
                return bumped_fee
            else:
                # Legacy chain: bump the gas price directly
                gas_price = web3.eth.gas_price
                return int(gas_price * bump_factor)
        except Exception as e:
            logger.debug(f"Failed to calculate bumped gas price: {e}")
            return None

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
        logger.warning(f"Safe TX attempt {attempt} failed, strategy: {strategy}. Error: {error}")
