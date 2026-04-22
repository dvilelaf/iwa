"""Safe transaction executor with retry logic and gas handling."""

import time
from typing import TYPE_CHECKING

from loguru import logger
from safe_eth.eth import TxSpeed
from safe_eth.safe import Safe
from safe_eth.safe.safe_tx import SafeTx

from iwa.core.chain.errors import sanitize_rpc_url
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
    "insufficient_funds": 0,
    "gs013_inner_revert_retries": 0,
    "parallel_nonce_races": 0,
    "parallel_nonce_race_retries": 0,
    "parallel_nonce_races_exhausted": 0,
}

# Fast retry delay for parallel nonce races (predecessor TX mines in ~1 block on Gnosis)
PARALLEL_NONCE_RACE_RETRY_DELAY = 1.0

# Sentinel for _decode_revert_reason memoisation (distinguishes "not yet
# computed" from "computed as None").
_UNSET = object()

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
        max_retries: int | None = None,
        gas_buffer: float | None = None,
    ):
        """Initialize the executor."""
        self.chain_interface = chain_interface

        # Use centralized config with fallbacks
        config = Config().core
        self.max_retries = max_retries or config.safe_tx_max_retries
        self.gas_buffer = gas_buffer or config.safe_tx_gas_buffer

    def execute_with_retry(
        self,
        safe_address: str,
        safe_tx: SafeTx,
        signer_keys: list[str],
        operation_name: str = "safe_tx",
        allow_nonce_refresh: bool = True,
    ) -> tuple[bool, str, dict | None]:
        """Execute SafeTx with full retry mechanism.

        Args:
            safe_address: The address of the Safe.
            safe_tx: The Safe transaction object.
            signer_keys: List of private keys for signing.
            operation_name: Name for logging purposes.
            allow_nonce_refresh: If False, nonce errors abort immediately instead of
                refreshing.  Set to False when the caller pre-assigns nonces via
                NonceAllocator to prevent _refresh_nonce from clobbering other workers'
                already-assigned nonce slots.

        Returns:
            Tuple of (success, tx_hash_or_error, receipt)

        """
        last_error = None
        last_was_nonce_race = False
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
                    allow_nonce_refresh=allow_nonce_refresh,
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
                updated_tx, should_retry, is_fee_error, is_nonce_race = (
                    self._handle_execution_failure(
                        e, safe_address, safe_tx, signer_keys, attempt, operation_name,
                        allow_nonce_refresh=allow_nonce_refresh,
                    )
                )
                last_error = e
                last_was_nonce_race = is_nonce_race
                if not should_retry:
                    break

                # Update gas/nonce for next loop if needed
                safe_tx = updated_tx

                # Bump fee multiplier on fee-related errors (base fee > max fee)
                if is_fee_error and fee_bump_factor < self.MAX_FEE_BUMP_FACTOR:
                    fee_bump_factor *= self.FEE_BUMP_PERCENTAGE
                    fee_bump_factor = min(fee_bump_factor, self.MAX_FEE_BUMP_FACTOR)
                    logger.info(f"[{operation_name}] Fee bump factor increased to {fee_bump_factor:.2f}x")

                # Parallel nonce race: predecessor TX mines in ~1 block (~5s on
                # Gnosis).  Use a short fixed delay instead of exponential
                # backoff, which would waste most of the window waiting.
                if is_nonce_race:
                    delay = PARALLEL_NONCE_RACE_RETRY_DELAY
                else:
                    delay = self.DEFAULT_RETRY_DELAY * (2**attempt)
                time.sleep(delay)

        # If we exhausted retries on a parallel nonce race, track it
        if last_error is not None and last_was_nonce_race:
            SAFE_TX_STATS["parallel_nonce_races_exhausted"] += 1

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
        allow_nonce_refresh: bool = True,
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
            classification = self._classify_error(e, allow_nonce_refresh=allow_nonce_refresh)
            # Parallel nonce race: GS026 during simulation with a pre-assigned
            # nonce.  Not a genuine signature failure — the predecessor TX
            # hasn't mined yet.  Let it propagate to _handle_execution_failure,
            # which uses a short fixed retry delay instead of aborting.
            if classification["is_parallel_nonce_race"]:
                SAFE_TX_STATS["parallel_nonce_races"] += 1
                logger.warning(
                    f"[{operation_name}] Parallel nonce race in simulation "
                    f"(attempt {attempt + 1}): nonce not yet on-chain, "
                    "predecessor TX still pending"
                )
                raise
            # Signature errors (GS020, GS026) are not recoverable - fail immediately
            if classification["is_signature_error"]:
                SAFE_TX_STATS["signature_errors"] += 1
                reason = self._decode_revert_reason(e)
                logger.error(
                    f"[{operation_name}] Signature error (not retryable): "
                    f"{reason or self._sanitize_error(e)}"
                )
                raise e
            if (
                classification["is_revert"]
                and not classification["is_nonce_error"]
                and not classification["is_gs013_inner_revert"]
            ):
                reason = self._decode_revert_reason(e)
                logger.error(
                    f"[{operation_name}] Simulation reverted: "
                    f"{reason or self._sanitize_error(e)}"
                )
                raise e
            # GS013 = inner call reverted (safeTxGas=0, gasPrice=0).
            # May be transient (RPC stale state, marketplace hiccup).
            # Let it fall through to retry; diagnosis happens in _handle_execution_failure.
            if classification["is_gs013_inner_revert"]:
                logger.warning(
                    f"[{operation_name}] GS013 inner call revert in simulation "
                    f"(attempt {attempt + 1}), will retry: "
                    f"{self._sanitize_error(e)}"
                )
                raise
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

        Always uses _calculate_bumped_gas_price (even on the first attempt with
        factor=1.0) to guarantee maxPriorityFeePerGas >= 1 wei.  Gnosis RPC
        returns max_priority_fee=0 which causes instant FeeTooLow rejection —
        letting safe-eth-py set the fee via eip1559_speed=FAST is not safe.
        Falls back to FAST only if the gas price calculation itself fails.
        """
        bumped_gas_price = self._calculate_bumped_gas_price(max(fee_bump_factor, 1.0))
        if bumped_gas_price:
            logger.debug(
                f"[{operation_name}] Using gas price: {bumped_gas_price} wei "
                f"(factor: {fee_bump_factor:.2f}x)"
            )
            return safe_tx.execute(signer_key, tx_gas_price=bumped_gas_price)
        # Fallback: let safe-eth-py pick the fee (may be 0 on Gnosis)
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

    def _handle_execution_failure(  # noqa: C901
        self,
        error: Exception,
        safe_address: str,
        safe_tx: SafeTx,
        signer_keys: list[str],
        attempt: int,
        operation_name: str,
        allow_nonce_refresh: bool = True,
    ) -> tuple[SafeTx, bool, bool, bool]:
        """Handle execution failure and determine next steps.

        Returns:
            Tuple of (updated_safe_tx, should_retry, is_fee_error, is_nonce_race)

            is_nonce_race: True when this failure was classified as a parallel
            nonce race (GS026 with pre-assigned nonce).  The caller uses this
            to choose between fast fixed delay and exponential backoff without
            re-classifying the error a second time.

        """
        classification = self._classify_error(error, allow_nonce_refresh=allow_nonce_refresh)
        is_fee_error = classification["is_fee_error"]

        # Decode revert reason once for all abort paths
        reason = self._decode_revert_reason(error)
        reason_suffix = f" | Decoded: {reason}" if reason else ""

        # Sanitize error text to prevent RPC API key leakage in logs
        safe_error = self._sanitize_error(error)

        # Parallel nonce race: GS026 with a pre-assigned nonce.  Not a genuine
        # signature failure — the predecessor TX with nonce N-1 hasn't mined
        # yet.  Retry quickly (predecessor mines in ~1 block on Gnosis) rather
        # than aborting on what looks like a signature error.
        if classification["is_parallel_nonce_race"]:
            if attempt >= self.max_retries:
                SAFE_TX_STATS["final_failures"] += 1
                logger.error(
                    f"[{operation_name}] Parallel nonce race — budget exhausted "
                    f"after {attempt + 1} attempts: {safe_error}{reason_suffix}"
                )
                return safe_tx, False, is_fee_error, True
            SAFE_TX_STATS["parallel_nonce_race_retries"] += 1
            logger.debug(
                f"[{operation_name}] Parallel nonce race retry "
                f"{attempt + 1}/{self.max_retries}"
            )
            return safe_tx, True, False, True

        # Signature errors (GS020, GS026) are never recoverable — abort immediately
        if classification["is_signature_error"]:
            SAFE_TX_STATS["signature_errors"] += 1
            SAFE_TX_STATS["final_failures"] += 1
            logger.error(
                f"[{operation_name}] Signature error — aborting (attempt {attempt + 1}): "
                f"{safe_error}{reason_suffix}"
            )
            return safe_tx, False, is_fee_error, False

        # GS013 = RPC provider returning stale state that makes the Safe
        # simulation fail.  The diagnosis eth.call always succeeds because
        # with_retry() may already use a different node.  Fix: rotate RPC
        # immediately so the next _execute_attempt hits a fresh node instead
        # of waiting through exponential backoff against the same stale node.
        if classification["is_gs013_inner_revert"]:
            SAFE_TX_STATS["gs013_inner_revert_retries"] += 1
            SAFE_TX_STATS["rpc_rotations"] += 1
            self._diagnose_inner_revert(safe_tx, operation_name)
            self.chain_interface._handle_rpc_error(error)
            logger.warning(
                f"[{operation_name}] GS013 inner call revert (attempt {attempt + 1}), "
                f"rotating RPC and retrying: {safe_error}{reason_suffix}"
            )
            return safe_tx, True, is_fee_error, False

        # InsufficientFunds: account can't cover value + gas.  Retrying won't
        # help — the balance won't increase by itself.
        if classification["is_insufficient_funds"]:
            SAFE_TX_STATS["insufficient_funds"] += 1
            SAFE_TX_STATS["final_failures"] += 1
            logger.error(
                f"[{operation_name}] Insufficient funds — aborting (attempt {attempt + 1}): "
                f"{safe_error}{reason_suffix}"
            )
            return safe_tx, False, is_fee_error, False

        if attempt >= self.max_retries:
            SAFE_TX_STATS["final_failures"] += 1
            logger.error(
                f"[{operation_name}] Failed after {attempt + 1} attempts: "
                f"{safe_error}{reason_suffix}"
            )
            return safe_tx, False, is_fee_error, False

        strategy = "retry"
        safe = self._recreate_safe_client(safe_address)

        if classification["is_nonce_error"] or classification["is_timeout"]:
            if classification["is_nonce_error"] and not allow_nonce_refresh:
                # Caller pre-assigned a nonce via NonceAllocator; refreshing would
                # clobber other workers' already-assigned slots.  Abort and let the
                # allocator invalidate + refetch on the next tick.
                logger.warning(
                    f"[{operation_name}] Nonce error with allow_nonce_refresh=False — "
                    "aborting (allocator will invalidate)"
                )
                return safe_tx, False, is_fee_error, False
            strategy = "nonce refresh" if classification["is_nonce_error"] else "timeout + nonce refresh"
            SAFE_TX_STATS["nonce_retries"] += 1
            safe_tx = self._refresh_nonce(safe, safe_tx, signer_keys)
        elif classification["is_rpc_error"]:
            strategy = "RPC rotation"
            SAFE_TX_STATS["rpc_rotations"] += 1
            result = self.chain_interface._handle_rpc_error(error)
            if not result["should_retry"]:
                return safe_tx, False, is_fee_error, False
        elif is_fee_error:
            strategy = "fee bump"
            SAFE_TX_STATS["gas_retries"] += 1
        elif classification["is_gas_error"]:
            strategy = "gas increase"
            SAFE_TX_STATS["gas_retries"] += 1

        self._log_retry(attempt + 1, error, strategy)
        return safe_tx, True, is_fee_error, False

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
        from iwa.plugins.gnosis.safe import get_ethereum_client

        rpc_url = self.chain_interface.current_rpc
        # Use shared cache to prevent FD exhaustion
        ethereum_client = get_ethereum_client(rpc_url)
        return Safe(safe_address, ethereum_client)

    def _is_nonce_error(self, error: Exception) -> bool:
        """Check if error is due to Safe nonce conflict.

        Matches both plain-text error messages and hex-encoded revert reasons
        (e.g. `0x...4753303235` for GS025), which some RPC providers return
        without a decoded string.
        """
        error_text = str(error).lower()
        decoded = (self._decode_revert_reason(error) or "").lower()
        combined = error_text + " " + decoded
        # GS025 = Invalid nonce (NOT GS026 which is invalid signatures)
        return any(
            x in combined
            for x in [
                "nonce",
                "gs025",
                "already executed",
                "duplicate",
                "could not replace existing tx",
                "replacement transaction underpriced",
            ]
        )

    def _is_signature_error(self, error: Exception) -> bool:
        """Check if error is due to invalid Safe signatures.

        GS020 = Signatures data too short
        GS021 = Invalid signature data pointer
        GS024 = Invalid contract signature
        GS026 = Invalid owner (signature from non-owner)

        Matches both plain-text error messages and hex-encoded revert reasons
        (e.g. `0x...4753303236` for GS026), which some RPC providers return
        without a decoded string.
        """
        error_text = str(error).lower()
        decoded = (self._decode_revert_reason(error) or "").lower()
        combined = error_text + " " + decoded
        return any(
            x in combined
            for x in [
                "gs020",
                "gs021",
                "gs024",
                "gs026",
                "invalid signatures",
                "signatures data too short",
            ]
        )

    def _refresh_nonce(
        self, safe: Safe, safe_tx: SafeTx, signer_keys: list[str]
    ) -> SafeTx:
        """Re-fetch nonce, rebuild transaction, and re-sign.

        The Safe tx hash includes the nonce, so changing the nonce invalidates
        all existing signatures.  We must re-sign with the available keys.
        """
        current_nonce = safe.retrieve_nonce()
        logger.info(f"Refreshing Safe nonce to {current_nonce}")
        new_tx = safe.build_multisig_tx(
            safe_tx.to,
            safe_tx.value,
            safe_tx.data,
            safe_tx.operation,
            safe_tx_gas=safe_tx.safe_tx_gas,
            base_gas=safe_tx.base_gas,
            gas_price=safe_tx.gas_price,
            gas_token=safe_tx.gas_token,
            refund_receiver=safe_tx.refund_receiver,
            safe_nonce=current_nonce,
        )

        # Re-sign with all available keys (hash changed with new nonce)
        for key in signer_keys:
            if key:
                new_tx.sign(key)

        return new_tx

    def _classify_error(self, error: Exception, allow_nonce_refresh: bool = True) -> dict:
        """Classify Safe transaction errors for retry decisions.

        Args:
            error: The exception to classify.
            allow_nonce_refresh: Whether the caller permits nonce refresh.  When
                False (caller pre-assigned nonces via NonceAllocator), a GS026
                revert in simulation is treated as a "parallel nonce race" —
                the predecessor TX hasn't mined yet, so the nonce slot on-chain
                doesn't match the pre-assigned one and the Safe reports it as
                an invalid-owner signature check failure.

        INVARIANT: ``allow_nonce_refresh=False`` MUST mean the caller has
        pre-assigned a nonce via NonceAllocator (the only current call site is
        ``micromech/runtime/delivery.py`` with ``allow_nonce_refresh=safe_nonce is None``).
        The ``is_parallel_nonce_race`` flag relies on this invariant — passing
        ``False`` for any other reason (e.g. "I manage the nonce myself but it
        is not pre-assigned") will mis-classify real GS026 signature failures as
        transient races and retry them instead of aborting.

        The returned dict guarantees mutual exclusivity:
        ``is_parallel_nonce_race=True`` implies ``is_signature_error=False``.

        """
        err_text = str(error).lower()
        decoded = (self._decode_revert_reason(error) or "").lower()
        combined = err_text + " " + decoded
        is_rpc = self.chain_interface._is_rate_limit_error(
            error
        ) or self.chain_interface._is_connection_error(error)

        # Fee-specific errors: base fee jumped above our max fee.
        # NOTE: Gnosis RPC sends "FeeTooLow" (no space) and
        # "EffectivePriorityFeePerGas too low" — both must be matched.
        fee_error_signals = [
            "max fee per gas less than block base fee",
            "maxfeepergas",
            "fee too low",
            "feetoolow",
            "effectivepriorityfeepergas",
            "underpriced",
        ]
        is_fee_error = any(signal in err_text for signal in fee_error_signals)

        # Timeout: TX was broadcast but not mined within the wait window.
        # The nonce is likely consumed or pending, so a nonce refresh is needed.
        # NOTE: Only match specific receipt-wait messages here.  Generic
        # "timeout" or "timed out" could be network-level and should go
        # through the RPC rotation path instead.
        is_timeout = "not in the chain after" in err_text

        # InsufficientFunds: the sender can't cover value + gas.
        # RPC code -32010 with "InsufficientFunds" or similar.
        insufficient_funds_signals = [
            "insufficientfunds",
            "insufficient funds",
            "sender doesn't have enough funds",
            "insufficient balance",
        ]
        is_insufficient_funds = any(s in err_text for s in insufficient_funds_signals)

        # GS013 = inner call reverted while safeTxGas=0 and gasPrice=0.
        # The Safe contract wraps ANY inner revert as GS013 in this mode.
        # May be transient (stale RPC state, marketplace hiccup).
        is_gs013_inner_revert = "gs013" in combined

        is_revert = "revert" in err_text or "execution reverted" in err_text
        is_signature_error = self._is_signature_error(error)

        # Parallel nonce race: GS026 in simulation when the caller pre-assigned
        # a nonce via NonceAllocator.  The predecessor TX (with nonce N-1) is
        # still pending, so on-chain nonce hasn't advanced — the Safe's
        # signature check reads the wrong hash and reports GS026.  Not a real
        # signature failure; retry quickly rather than aborting.
        # allow_nonce_refresh=False signals that the caller pre-assigned this
        # nonce via NonceAllocator.  When that flag is set AND the error is a
        # GS026 revert, it is almost certainly a parallel nonce race (the
        # predecessor TX hasn't mined yet) rather than a real signature failure.
        # We treat it as a transient race and retry quickly instead of aborting.
        # NOTE: is_parallel_nonce_race takes precedence; is_signature_error is
        # set to False when the race is detected so branches never overlap.
        is_parallel_nonce_race = (
            not allow_nonce_refresh
            and is_signature_error
            and is_revert
            and "gs026" in combined
        )
        # Mutual exclusivity: a race is NOT a permanent signature error.
        # Keeping both True would require callers to enforce branch order by
        # convention; making them exclusive encodes the invariant in the data.
        if is_parallel_nonce_race:
            is_signature_error = False

        return {
            "is_gas_error": any(x in err_text for x in ["gas", "out of gas", "intrinsic"]),
            "is_fee_error": is_fee_error,
            "is_nonce_error": self._is_nonce_error(error),
            "is_rpc_error": is_rpc,
            "is_revert": is_revert,
            "is_signature_error": is_signature_error,
            "is_timeout": is_timeout,
            "is_insufficient_funds": is_insufficient_funds,
            "is_gs013_inner_revert": is_gs013_inner_revert,
            "is_parallel_nonce_race": is_parallel_nonce_race,
        }

    def _calculate_bumped_gas_price(self, bump_factor: float) -> int | None:
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

    def _diagnose_inner_revert(self, safe_tx: "SafeTx", operation_name: str) -> None:
        """When GS013 occurs, call the inner tx directly to get the real reason.

        GS013 hides the inner revert reason behind the Safe wrapper.
        By calling safe_tx.to with safe_tx.data directly (bypassing the Safe),
        we can capture the actual contract revert reason.
        """
        try:
            self.chain_interface.with_retry(
                lambda: self.chain_interface.web3.eth.call(
                    {
                        "from": safe_tx.safe_address,
                        "to": safe_tx.to,
                        "data": safe_tx.data.hex() if safe_tx.data else "0x",
                        "value": safe_tx.value,
                    },
                    "latest",
                )
            )
            # If it succeeds here, the issue was truly transient
            logger.info(
                f"[{operation_name}] GS013 diagnosis: inner call succeeds now "
                "(transient RPC state issue)"
            )
        except Exception as inner_err:
            reason = self._decode_revert_reason(inner_err)
            sanitized = self._sanitize_error(inner_err)
            logger.warning(
                f"[{operation_name}] GS013 diagnosis: inner call reverts with: "
                f"{reason or sanitized}"
            )

    _DECODED_REASON_ATTR = "_iwa_decoded_revert_reason"

    def _decode_revert_reason(self, error: Exception) -> str | None:
        """Attempt to decode the revert reason from exception data.

        Tries multiple extraction strategies:
        1. Exception .data attribute (web3/safe-eth-py store revert data here)
        2. Exception .args — look for hex strings in positional args
        3. Regex on str(error) as fallback

        Result is memoised on the exception object so repeated classification
        passes (_is_signature_error, _is_nonce_error, _classify_error etc. all
        within one retry) don't re-instantiate ErrorDecoder or re-run regex.
        """
        cached = getattr(error, self._DECODED_REASON_ATTR, _UNSET)
        if cached is not _UNSET:
            return cached

        result: str | None = None
        hex_data = self._extract_revert_hex(error)
        if hex_data:
            try:
                decoded = ErrorDecoder().decode(hex_data)
                if decoded:
                    _name, msg, source = decoded[0]
                    result = f"{msg} (from {source})"
            except Exception:
                logger.debug(f"ErrorDecoder.decode() failed for data: {hex_data[:20]}...")

        try:
            object.__setattr__(error, self._DECODED_REASON_ATTR, result)
        except (AttributeError, TypeError):
            # Some exception types reject dynamic attrs; skip caching for those.
            pass
        return result

    @staticmethod
    def _extract_revert_hex(error: Exception) -> str | None:  # noqa: C901
        """Extract hex revert data from an exception, trying multiple sources."""
        import re

        # 1. Check .data attribute (web3 exceptions, safe-eth-py)
        raw_data = getattr(error, "data", None)
        if raw_data:
            if isinstance(raw_data, bytes):
                return "0x" + raw_data.hex()
            if isinstance(raw_data, str) and re.fullmatch(r"0x[0-9a-fA-F]{8,}", raw_data):
                return raw_data
            if isinstance(raw_data, dict):
                nested = raw_data.get("data")
                if isinstance(nested, str) and re.fullmatch(r"0x[0-9a-fA-F]{8,}", nested):
                    return nested

        # 2. Check .args for hex strings (some exceptions pack data in args)
        for arg in getattr(error, "args", ()):
            if isinstance(arg, bytes) and len(arg) >= 4:
                return "0x" + arg.hex()
            if isinstance(arg, str):
                # Negative lookbehind for '/' avoids matching hex in URL paths
                match = re.search(r"(?<!/)\b0x[0-9a-fA-F]{8,}", arg)
                if match:
                    return match.group(0)
            # Some exceptions nest a dict with 'data' key in args
            if isinstance(arg, dict):
                nested = arg.get("data")
                if isinstance(nested, str) and re.fullmatch(r"0x[0-9a-fA-F]{8,}", nested):
                    return nested

        # 3. Fallback: regex on the string representation.
        # Use negative lookbehind for '/' to avoid matching hex API keys
        # embedded in RPC URLs (e.g., https://rpc.example.com/0xABCDEF...).
        error_text = str(error)
        hex_match = re.search(r"(?<!/)\b0x[0-9a-fA-F]{8,}", error_text)
        if hex_match:
            return hex_match.group(0)

        return None

    @staticmethod
    def _sanitize_error(error: Exception) -> str:
        """Sanitize error message to prevent RPC API key leakage in logs."""
        import re

        text = str(error)
        # Sanitize any embedded URLs (may contain API keys in path/query)
        text = re.sub(
            r"https?://[^\s\"')\]]+",
            lambda m: sanitize_rpc_url(m.group(0)),
            text,
        )
        return text

    def _log_retry(self, attempt: int, error: Exception, strategy: str):
        """Log a retry attempt."""
        logger.warning(
            f"Safe TX attempt {attempt} failed, strategy: {strategy}. "
            f"Error: {self._sanitize_error(error)}"
        )
