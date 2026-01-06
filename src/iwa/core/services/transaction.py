"""Transaction service module."""

import time
from typing import Dict, List, Optional, Tuple

from loguru import logger
from web3 import exceptions as web3_exceptions

from iwa.core.chain import ChainInterfaces
from iwa.core.db import log_transaction
from iwa.core.keys import KeyStorage
from iwa.core.services.account import AccountService


class TransactionService:
    """Manages transaction lifecycle: signing, sending, retrying."""

    def __init__(self, key_storage: KeyStorage, account_service: AccountService):
        """Initialize TransactionService."""
        self.key_storage = key_storage
        self.account_service = account_service

    def sign_and_send(
        self,
        transaction: dict,
        signer_address_or_tag: str,
        chain_name: str = "gnosis",
        tags: Optional[List[str]] = None,
    ) -> Tuple[bool, Dict]:
        """Sign and send a transaction with retry logic for gas."""
        chain_interface = ChainInterfaces().get(chain_name)
        tx = dict(transaction)
        max_retries = 3

        if not self._prepare_transaction(tx, signer_address_or_tag, chain_interface):
            return False, {}

        for attempt in range(1, max_retries + 1):
            try:
                signed_txn = self.key_storage.sign_transaction(tx, signer_address_or_tag)
                txn_hash = chain_interface.web3.eth.send_raw_transaction(signed_txn.raw_transaction)
                receipt = chain_interface.web3.eth.wait_for_transaction_receipt(txn_hash)

                if receipt and getattr(receipt, "status", None) == 1:
                    signer_account = self.account_service.resolve_account(signer_address_or_tag)
                    chain_interface.wait_for_no_pending_tx(signer_account.address)
                    logger.info(f"Transaction sent successfully. Tx Hash: {txn_hash.hex()}")

                    self._log_successful_transaction(
                        receipt, tx, signer_account, chain_name, txn_hash, tags
                    )
                    return True, receipt

                # Transaction reverted
                logger.error("Transaction failed (status 0).")
                return False, {}

            except web3_exceptions.Web3RPCError as e:
                if self._handle_gas_error(e, tx, attempt, max_retries):
                    continue
                return False, {}

            except Exception as e:
                # Attempt RPC rotation
                if self._handle_generic_error(e, chain_interface, attempt, max_retries):
                    continue
                return False, {}

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
        return True

    def _handle_gas_error(self, e, tx, attempt, max_retries) -> bool:
        err_text = str(e)
        if self._is_gas_too_low_error(err_text) and attempt < max_retries:
            logger.warning(
                f"Gas too low error detected. Retrying with increased gas (Attempt {attempt}/{max_retries})..."
            )
            current_gas = int(tx.get("gas", 30_000))
            tx["gas"] = int(current_gas * 1.5)
            time.sleep(0.5 * attempt)
            return True
        logger.exception(f"Error sending transaction: {e}")
        return False

    def _handle_generic_error(self, e, chain_interface, attempt, max_retries) -> bool:
        if attempt < max_retries:
            logger.warning(f"Error encountered: {e}. Attempting to rotate RPC...")
            if chain_interface.rotate_rpc():
                logger.info("Retrying with new RPC...")
                time.sleep(0.5 * attempt)
                return True
        logger.exception(f"Unexpected error sending transaction: {e}")
        return False

    def _log_successful_transaction(self, receipt, tx, signer_account, chain_name, txn_hash, tags):
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

    def _is_gas_too_low_error(self, err_text: str) -> bool:
        """Check if error is due to low gas."""
        low_gas_signals = [
            "feetoolow",
            "intrinsic gas too low",
            "replacement transaction underpriced",
        ]
        text = (err_text or "").lower()
        return any(sig in text for sig in low_gas_signals)
