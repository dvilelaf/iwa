"""Transaction service module."""

from typing import TYPE_CHECKING, Dict, List, Optional, Tuple

from loguru import logger
from web3 import Web3
from web3 import exceptions as web3_exceptions

from iwa.core.chain import ChainInterfaces
from iwa.core.db import log_transaction
from iwa.core.keys import KeyStorage
from iwa.core.models import StoredSafeAccount
from iwa.core.services.account import AccountService

if TYPE_CHECKING:
    from iwa.core.chain import ChainInterface

    # Circular import during type checking

# ERC20 Transfer event signature: Transfer(address indexed from, address indexed to, uint256 value)
TRANSFER_EVENT_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"


class TransferLogger:
    """Parse and log transfer events from transaction receipts."""

    def __init__(
        self,
        account_service: AccountService,
        chain_interface: "ChainInterface",
    ):
        """Initialize TransferLogger."""
        self.account_service = account_service
        self.chain_interface = chain_interface

    def log_transfers(self, receipt: Dict) -> None:
        """Log all transfers (ERC20 and native) from a transaction receipt.

        Args:
            receipt: Transaction receipt containing logs.

        """
        # Get the original transaction to check for native value transfer
        tx_hash = receipt.get("transactionHash") or getattr(receipt, "transactionHash", None)
        if tx_hash:
            try:
                tx = self.chain_interface.web3.eth.get_transaction(tx_hash)
                native_value = (
                    getattr(tx, "value", 0) or tx.get("value", 0)
                    if isinstance(tx, dict)
                    else getattr(tx, "value", 0)
                )
                if native_value and int(native_value) > 0:
                    from_addr = (
                        getattr(tx, "from", "") if hasattr(tx, "from") else tx.get("from", "")
                    )
                    # Handle AttributeDict's special 'from' attribute
                    if not from_addr and hasattr(tx, "__getitem__"):
                        from_addr = tx["from"]
                    to_addr = getattr(tx, "to", "") or (
                        tx.get("to", "") if isinstance(tx, dict) else ""
                    )
                    self._log_native_transfer(from_addr, to_addr, native_value)
            except Exception as e:
                logger.debug(f"Could not get tx for native transfer logging: {e}")

        # Log ERC20 transfers from event logs
        logs = (
            receipt.get("logs", []) if isinstance(receipt, dict) else getattr(receipt, "logs", [])
        )

        for log in logs:
            self._process_log(log)

    def _log_native_transfer(self, from_addr: str, to_addr: str, value_wei: int) -> None:
        """Log a native currency transfer."""
        from_label = self._resolve_address_label(from_addr)
        to_label = self._resolve_address_label(to_addr)

        native_symbol = self.chain_interface.chain.native_currency
        amount_eth = Web3.from_wei(value_wei, "ether")

        logger.info(f"[TRANSFER] {amount_eth:.6g} {native_symbol}: {from_label} → {to_label}")

    def _process_log(self, log) -> None:
        """Process a single log entry for Transfer events."""
        # Get topics - handle both dict and AttributeDict
        topics = log.get("topics", []) if isinstance(log, dict) else getattr(log, "topics", [])

        if not topics:
            return

        # Check if this is a Transfer event
        first_topic = topics[0]
        if isinstance(first_topic, bytes):
            first_topic = "0x" + first_topic.hex()
        elif hasattr(first_topic, "hex"):
            first_topic = first_topic.hex()
            if not first_topic.startswith("0x"):
                first_topic = "0x" + first_topic

        if first_topic.lower() != TRANSFER_EVENT_TOPIC.lower():
            return

        # Need at least 3 topics for indexed from/to
        if len(topics) < 3:
            return

        try:
            # Extract from/to from indexed topics (last 20 bytes of 32-byte topic)
            from_topic = topics[1]
            to_topic = topics[2]

            from_addr = self._topic_to_address(from_topic)
            to_addr = self._topic_to_address(to_topic)

            # Extract amount from data
            data = log.get("data", b"") if isinstance(log, dict) else getattr(log, "data", b"")
            if isinstance(data, str):
                data = bytes.fromhex(data.replace("0x", ""))

            amount = int.from_bytes(data, "big") if data else 0

            # Get token address
            token_addr = (
                log.get("address", "") if isinstance(log, dict) else getattr(log, "address", "")
            )

            self._log_erc20_transfer(token_addr, from_addr, to_addr, amount)

        except Exception as e:
            logger.debug(f"Failed to parse Transfer event: {e}")

    def _topic_to_address(self, topic) -> str:
        """Convert a 32-byte topic to a 20-byte address."""
        if isinstance(topic, bytes):
            # Last 20 bytes
            addr_bytes = topic[-20:]
            return Web3.to_checksum_address("0x" + addr_bytes.hex())
        elif hasattr(topic, "hex"):
            hex_str = topic.hex()
            if not hex_str.startswith("0x"):
                hex_str = "0x" + hex_str
            # Last 40 chars (20 bytes)
            return Web3.to_checksum_address("0x" + hex_str[-40:])
        elif isinstance(topic, str):
            if topic.startswith("0x"):
                topic = topic[2:]
            return Web3.to_checksum_address("0x" + topic[-40:])
        return ""

    def _log_erc20_transfer(
        self, token_addr: str, from_addr: str, to_addr: str, amount_wei: int
    ) -> None:
        """Log an ERC20 transfer (or NFT transfer if detected)."""
        from_label = self._resolve_address_label(from_addr)
        to_label = self._resolve_address_label(to_addr)
        token_label = self._resolve_token_label(token_addr)

        # Try to get decimals - if None, it's an NFT (ERC721)
        decimals = self.chain_interface.get_token_decimals(token_addr, fallback_to_18=False)

        if decimals is not None:
            amount = amount_wei / (10**decimals)
            logger.info(f"[TRANSFER] {amount:.6g} {token_label}: {from_label} → {to_label}")
        else:
            # Likely an NFT (ERC721) - the amount is the token ID
            if amount_wei > 0:
                logger.info(
                    f"[NFT TRANSFER] Token #{amount_wei} {token_label}: {from_label} → {to_label}"
                )
            else:
                logger.debug(f"[NFT TRANSFER] {token_label}: {from_label} → {to_label}")

    def _resolve_address_label(self, address: str) -> str:
        """Resolve an address to a human-readable label.

        Priority:
        1. Known wallet tag (from wallets.json)
        2. Known token name (it's a token contract)
        3. Abbreviated address

        """
        if not address:
            return "unknown"

        # 1. Check known wallets
        tag = self.account_service.get_tag_by_address(address)
        if tag:
            return tag

        # 2. Check if it's a known token contract
        token_name = self.chain_interface.chain.get_token_name(address)
        if token_name:
            return f"{token_name}_contract"

        # 3. Fallback to abbreviated address
        return f"{address[:6]}...{address[-4:]}"

    def _resolve_token_label(self, token_addr: str) -> str:
        """Resolve a token address to its symbol.

        Priority:
        1. Known token from chain config
        2. Abbreviated address

        """
        if not token_addr:
            return "UNKNOWN"

        # Check known tokens
        token_name = self.chain_interface.chain.get_token_name(token_addr)
        if token_name:
            return token_name

        # Fallback to abbreviated address
        return f"{token_addr[:6]}...{token_addr[-4:]}"


class TransactionService:
    """Manages transaction lifecycle: signing, sending, retrying."""

    def __init__(self, key_storage: KeyStorage, account_service: AccountService, safe_service=None):
        """Initialize TransactionService."""
        self.key_storage = key_storage
        self.account_service = account_service
        self.safe_service = safe_service

    def _resolve_label(self, address: str, chain_name: str = "gnosis") -> str:
        """Resolve address to human-readable label."""
        if not address:
            return "None"
        # Try account/safe tags
        tag = self.account_service.get_tag_by_address(address)
        if tag:
            return tag
        # Try token/contract names
        try:
            chain_interface = ChainInterfaces().get(chain_name)
            name = chain_interface.chain.get_token_name(address)
            if name:
                return name
        except Exception:
            pass
        return address

    def sign_and_send(  # noqa: C901
        self,
        transaction: dict,
        signer_address_or_tag: str,
        chain_name: str = "gnosis",
        tags: Optional[List[str]] = None,
    ) -> Tuple[bool, Dict]:
        """Sign and send a transaction using unified retry mechanism.

        Uses ChainInterface.with_retry() for consistent RPC rotation and retry logic.
        Gas errors are handled by increasing gas and retrying within the same mechanism.
        """
        chain_interface = ChainInterfaces().get(chain_name)
        tx = dict(transaction)

        if not self._prepare_transaction(tx, signer_address_or_tag, chain_interface):
            return False, {}

        # CHECK FOR SAFE TRANSACTION
        signer_account = self.account_service.resolve_account(signer_address_or_tag)
        if isinstance(signer_account, StoredSafeAccount):
            if not self.safe_service:
                logger.error("Attempted Safe transaction but SafeService is not initialized.")
                return False, {}
            return self._execute_via_safe(tx, signer_account, chain_interface, chain_name, tags)

        # Mutable state for retry attempts
        state = {"gas_retries": 0, "max_gas_retries": 5}

        def _do_sign_send_wait() -> Tuple[bool, Dict, bytes]:
            """Inner operation wrapped by with_retry."""
            try:
                signed_txn = self.key_storage.sign_transaction(tx, signer_address_or_tag)
                txn_hash = chain_interface.web3.eth.send_raw_transaction(signed_txn.raw_transaction)
                receipt = chain_interface.web3.eth.wait_for_transaction_receipt(txn_hash)

                status = getattr(receipt, "status", None)
                if status is None and isinstance(receipt, dict):
                    status = receipt.get("status")

                if receipt and status == 1:
                    return True, receipt, txn_hash
                # Transaction mined but reverted - don't retry
                logger.error("Transaction failed (status 0).")
                raise ValueError("Transaction reverted")

            except web3_exceptions.Web3RPCError as e:
                # Handle gas errors by increasing gas and re-raising
                self._handle_gas_retry(e, tx, state)
                raise  # Re-raise to trigger with_retry's retry mechanism

        try:
            success, receipt, txn_hash = chain_interface.with_retry(
                _do_sign_send_wait,
                operation_name=f"sign_and_send to {tx.get('to', 'unknown')[:10]}...",
            )
            if success:
                signer_account = self.account_service.resolve_account(signer_address_or_tag)
                chain_interface.wait_for_no_pending_tx(signer_account.address)
                logger.info(f"Transaction sent successfully. Tx Hash: {txn_hash.hex()}")
                self._log_successful_transaction(
                    receipt, tx, signer_account, chain_name, txn_hash, tags, chain_interface
                )
                return True, receipt
            return False, {}
        except ValueError as e:
            # Transaction reverted - already logged
            if "reverted" in str(e).lower():
                return False, {}
            logger.exception(f"Transaction failed: {e}")
            return False, {}
        except Exception as e:
            logger.exception(f"Transaction failed after retries: {e}")
            return False, {}

    def _prepare_transaction(self, tx: dict, signer_tag: str, chain_interface) -> bool:
        """Ensure nonce and chainId are set."""
        if "nonce" not in tx:
            signer_account = self.account_service.resolve_account(signer_tag)
            if not signer_account:
                logger.error(f"Signer {signer_tag} not found")
                return False
            tx["nonce"] = chain_interface.web3.eth.get_transaction_count(signer_account.address)

        if "chainId" not in tx:
            tx["chainId"] = chain_interface.chain.chain_id

        # Safety net: Ensure fees are set if missing (prevents FeeTooLow on Gnosis)
        if "gasPrice" not in tx and "maxFeePerGas" not in tx:
            try:
                fees = chain_interface.get_suggested_fees()
                tx.update(fees)
            except Exception as e:
                logger.debug(f"Failed to auto-fill fees in _prepare_transaction: {e}")

        return True

    def _handle_gas_retry(self, e: Exception, tx: dict, state: dict) -> None:
        """Increase gas if error is gas-related and retries remaining."""
        if self._is_gas_too_low_error(str(e)) and state["gas_retries"] < state["max_gas_retries"]:
            current_gas = int(tx.get("gas", 30_000))
            tx["gas"] = int(current_gas * 1.5)
            state["gas_retries"] += 1
            logger.warning(
                f"Gas too low, increasing to {tx['gas']} "
                f"(attempt {state['gas_retries']}/{state['max_gas_retries']})"
            )

    def _log_successful_transaction(
        self, receipt, tx, signer_account, chain_name, txn_hash, tags, chain_interface
    ):
        try:
            gas_cost_wei, gas_value_eur = self._calculate_gas_cost(receipt, tx, chain_name)
            final_tags = self._determine_tags(tx, tags)

            log_transaction(
                tx_hash=txn_hash.hex(),
                from_addr=signer_account.address,
                to_addr=tx.get("to", ""),
                token="NATIVE",
                amount_wei=tx.get("value", 0),
                chain=chain_name,
                from_tag=signer_account.tag if hasattr(signer_account, "tag") else None,
                gas_cost=str(gas_cost_wei) if gas_cost_wei else None,
                gas_value_eur=gas_value_eur,
                tags=final_tags if final_tags else None,
            )

            # Log transfer events (ERC20 and native value)
            transfer_logger = TransferLogger(self.account_service, chain_interface)
            transfer_logger.log_transfers(receipt)

        except Exception as log_err:
            logger.warning(f"Failed to log transaction: {log_err}")

    def _calculate_gas_cost(self, receipt, tx, chain_name):
        gas_used = getattr(receipt, "gasUsed", 0)
        gas_price = getattr(
            receipt,
            "effectiveGasPrice",
            tx.get("gasPrice", tx.get("maxFeePerGas", 0)),
        )
        gas_cost_wei = gas_used * gas_price if gas_price else 0

        gas_value_eur = None
        if gas_cost_wei > 0:
            try:
                from iwa.core.pricing import PriceService

                token_id = "dai" if chain_name.lower() == "gnosis" else "ethereum"
                pricing = PriceService()
                native_price = pricing.get_token_price(token_id)
                if native_price:
                    gas_eth = float(gas_cost_wei) / 10**18
                    gas_value_eur = gas_eth * native_price
            except Exception as price_err:
                logger.warning(f"Failed to calculate gas value: {price_err}")
        return gas_cost_wei, gas_value_eur

    def _determine_tags(self, tx, tags):
        final_tags = tags or []
        data_hex = tx.get("data", "")
        if isinstance(data_hex, bytes):
            data_hex = data_hex.hex()
        if data_hex.startswith("0x095ea7b3") or data_hex.startswith("095ea7b3"):
            final_tags.append("approve")

        if "olas" in str(tx.get("to", "")).lower():
            final_tags.append("olas")

        return list(set(final_tags))

    def _execute_via_safe(
        self,
        tx: dict,
        signer_account: StoredSafeAccount,
        chain_interface,
        chain_name: str,
        tags: List[str] = None,
    ) -> Tuple[bool, Dict]:
        """Execute transaction via SafeService."""
        logger.info(
            f"Routing transaction via Safe {self._resolve_label(signer_account.address, chain_name)}..."
        )

        try:
            # Extract basic params
            to_addr = tx.get("to")
            value = tx.get("value", 0)
            data = tx.get("data", "")
            if isinstance(data, bytes):
                data = "0x" + data.hex()

            # Execute
            tx_hash = self.safe_service.execute_safe_transaction(
                safe_address_or_tag=signer_account.address,
                to=to_addr,
                value=value,
                chain_name=chain_name,
                data=data,
            )

            # Receipt is already waited for inside execute_safe_transaction/executor
            # but we can fetch it again here to be safe and continue with Olas logging
            receipt = chain_interface.web3.eth.wait_for_transaction_receipt(tx_hash)

            status = getattr(receipt, "status", None)
            if status is None and isinstance(receipt, dict):
                status = receipt.get("status")

            if receipt and status == 1:
                logger.info(f"Safe transaction executed successfully. Tx Hash: {tx_hash}")
                self._log_successful_transaction(
                    receipt,
                    tx,
                    signer_account,
                    chain_name,
                    bytes.fromhex(tx_hash.replace("0x", "")),
                    tags,
                    chain_interface,
                )
                return True, receipt
            else:
                logger.error("Safe transaction failed (status 0).")
                return False, {}

        except Exception as e:
            # Try to decode detailed revert reason
            error_text = str(e)
            decoded_msg = None

            # Extract hex data from common error patterns
            # Pattern 1: ('execution reverted', '0x...')
            import re

            hex_match = re.search(r"0x[0-9a-fA-F]{8,}", error_text)

            if hex_match:
                try:
                    from iwa.core.contracts.decoder import ErrorDecoder

                    data = hex_match.group(0)
                    decoded = ErrorDecoder().decode(data)
                    if decoded:
                        # Use the first successful decoding
                        name, msg, source = decoded[0]
                        decoded_msg = f"{msg} (from {source})"
                except Exception:
                    pass

            if decoded_msg:
                logger.error(f"Safe transaction failed: {decoded_msg}")
            else:
                logger.exception(f"Safe transaction failed: {e}")

            return False, {}

    def _is_gas_too_low_error(self, err_text: str) -> bool:
        """Check if error is due to low gas."""
        low_gas_signals = [
            "feetoolow",
            "intrinsic gas too low",
            "replacement transaction underpriced",
        ]
        text = (err_text or "").lower()
        return any(sig in text for sig in low_gas_signals)
