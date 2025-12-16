"""Managers for transaction and chain interactions."""

import time
from typing import Dict, Tuple

from web3 import exceptions as web3_exceptions

from iwa.core.chain import ChainInterfaces
from iwa.core.keys import KeyStorage
from iwa.core.utils import configure_logger

logger = configure_logger()


class TransactionManager:
    """Manages transaction lifecycle: signing, sending, retrying."""

    def __init__(self, key_storage: KeyStorage):
        """Initialize TransactionManager."""
        self.key_storage = key_storage

    def sign_and_send(  # noqa: C901
        self, transaction: dict, signer_address_or_tag: str, chain_name: str = "gnosis"
    ) -> Tuple[bool, Dict]:
        """Sign and send a transaction with retry logic for gas."""
        chain_interface = ChainInterfaces().get(chain_name)
        tx = dict(transaction)
        max_retries = 3

        # Ensure nonce is set if not present
        if "nonce" not in tx:
            signer_account = self.key_storage.get_account(signer_address_or_tag)
            if not signer_account:
                logger.error(f"Signer {signer_address_or_tag} not found")
                return False, {}
            tx["nonce"] = chain_interface.web3.eth.get_transaction_count(signer_account.address)

        if "chainId" not in tx:
            tx["chainId"] = chain_interface.chain.chain_id

        for attempt in range(1, max_retries + 1):
            try:
                # Sign
                signed_txn = self.key_storage.sign_transaction(tx, signer_address_or_tag)

                # Send
                txn_hash = chain_interface.web3.eth.send_raw_transaction(signed_txn.rawTransaction)

                # Wait
                receipt = chain_interface.web3.eth.wait_for_transaction_receipt(txn_hash)

                if receipt and getattr(receipt, "status", None) == 1:
                    signer_account = self.key_storage.get_account(signer_address_or_tag)
                    chain_interface.wait_for_no_pending_tx(signer_account.address)
                    logger.info(f"Transaction sent successfully. Tx Hash: {txn_hash.hex()}")
                    return True, receipt

                logger.error("Transaction failed (status 0).")
                return False, {}

            except web3_exceptions.Web3RPCError as e:
                err_text = str(e)
                if self._is_gas_too_low_error(err_text) and attempt < max_retries:
                    logger.warning(
                        f"Gas too low error detected. Retrying with increased gas (Attempt {attempt}/{max_retries})..."
                    )
                    current_gas = int(tx.get("gas", 30_000))
                    tx["gas"] = int(current_gas * 1.5)
                    time.sleep(0.5 * attempt)  # backoff
                    continue
                else:
                    logger.exception(f"Error sending transaction: {e}")
                    return False, {}

            except Exception as e:
                # Attempt RPC rotation on failure if it's likely a connection/node issue
                # Differentiating is hard, so we might rotate on unknown errors too if we haven't exhausted attempts yet
                if attempt < max_retries:
                    logger.warning(f"Error encountered: {e}. Attempting to rotate RPC...")
                    rotated = chain_interface.rotate_rpc()
                    if rotated:
                        logger.info("Retrying with new RPC...")
                        time.sleep(0.5 * attempt)
                        continue

                logger.exception(f"Unexpected error sending transaction: {e}")
                return False, {}

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
