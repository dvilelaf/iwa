"""Native transfer mixin."""

from typing import TYPE_CHECKING, Optional

from loguru import logger
from web3 import Web3
from web3.types import Wei

from iwa.core.chain import ChainInterfaces
from iwa.core.db import log_transaction
from iwa.core.models import StoredSafeAccount

if TYPE_CHECKING:
    from iwa.core.services.transfer import TransferService


class NativeTransferMixin:
    """Mixin for native currency transfers and wrapping."""

    def _send_native_via_safe(
        self: "TransferService",
        from_account: StoredSafeAccount,
        from_address_or_tag: str,
        to_address: str,
        amount_wei: Wei,
        chain_name: str,
        from_tag: Optional[str],
        to_tag: Optional[str],
        token_symbol: str,
    ) -> str:
        """Send native currency via Safe multisig."""
        tx_hash = self.safe_service.execute_safe_transaction(
            safe_address_or_tag=from_address_or_tag,
            to=to_address,
            value=amount_wei,
            chain_name=chain_name,
        )
        # Get receipt for gas calculation
        receipt = None
        try:
            interface = ChainInterfaces().get(chain_name)
            receipt = interface.web3.eth.get_transaction_receipt(tx_hash)
        except Exception as e:
            logger.warning(f"Could not get receipt for Safe tx {tx_hash}: {e}")

        gas_cost, gas_value_eur = self._calculate_gas_info(receipt, chain_name)
        # Get price and value
        p_eur, v_eur = self._get_token_price_info(token_symbol, amount_wei, chain_name)
        log_transaction(
            tx_hash=tx_hash,
            from_addr=from_account.address,
            to_addr=to_address,
            token=token_symbol,
            amount_wei=amount_wei,
            chain=chain_name,
            from_tag=from_tag,
            to_tag=to_tag,
            gas_cost=gas_cost,
            gas_value_eur=gas_value_eur,
            price_eur=p_eur,
            value_eur=v_eur,
            tags=["native-transfer", "safe-transaction"],
        )
        return tx_hash

    def _send_native_via_eoa(
        self: "TransferService",
        from_account,
        to_address: str,
        amount_wei: Wei,
        chain_name: str,
        chain_interface,
        from_tag: Optional[str],
        to_tag: Optional[str],
        token_symbol: str,
    ) -> Optional[str]:
        """Send native currency via EOA (externally owned account)."""
        success, tx_hash = chain_interface.send_native_transfer(
            from_address=from_account.address,
            to_address=to_address,
            value_wei=amount_wei,
            sign_callback=lambda tx: self.key_storage.sign_transaction(tx, from_account.address),
        )
        if success and tx_hash:
            # Get receipt for gas calculation
            receipt = None
            try:
                receipt = chain_interface.web3.eth.get_transaction_receipt(tx_hash)
            except Exception as e:
                logger.warning(f"Could not get receipt for {tx_hash}: {e}")

            gas_cost, gas_value_eur = self._calculate_gas_info(receipt, chain_name)
            p_eur, v_eur = self._get_token_price_info(token_symbol, amount_wei, chain_name)
            log_transaction(
                tx_hash=tx_hash,
                from_addr=from_account.address,
                to_addr=to_address,
                token=token_symbol,
                amount_wei=amount_wei,
                chain=chain_name,
                from_tag=from_tag,
                to_tag=to_tag,
                gas_cost=gas_cost,
                gas_value_eur=gas_value_eur,
                price_eur=p_eur,
                value_eur=v_eur,
                tags=["native-transfer"],
            )
            return tx_hash
        return None

    def wrap_native(
        self: "TransferService",
        account_address_or_tag: str,
        amount_wei: Wei,
        chain_name: str = "gnosis",
    ) -> Optional[str]:
        """Wrap native currency to wrapped token (e.g., xDAI → WXDAI).

        Args:
            account_address_or_tag: Account to wrap from
            amount_wei: Amount in wei to wrap
            chain_name: Chain name (default: gnosis)

        Returns:
            Transaction hash if successful, None otherwise.

        """
        account = self.account_service.resolve_account(account_address_or_tag)
        if not account:
            logger.error(f"Account '{account_address_or_tag}' not found.")
            return None

        chain_interface = ChainInterfaces().get(chain_name)
        wrapped_token = chain_interface.chain.tokens.get("WXDAI")
        if not wrapped_token:
            logger.error(f"WXDAI not found on {chain_name}")
            return None

        # Simple WETH ABI for deposit
        weth_abi = [
            {
                "constant": False,
                "inputs": [],
                "name": "deposit",
                "outputs": [],
                "payable": True,
                "type": "function",
            }
        ]

        contract = chain_interface.web3._web3.eth.contract(address=wrapped_token, abi=weth_abi)

        amount_eth = float(Web3.from_wei(amount_wei, "ether"))
        logger.info(f"Wrapping {amount_eth:.4f} xDAI → WXDAI...")

        try:
            tx = contract.functions.deposit().build_transaction(
                {
                    "from": account.address,
                    "value": amount_wei,
                    "gas": 100000,
                    "gasPrice": chain_interface.web3._web3.eth.gas_price,
                    "nonce": chain_interface.web3._web3.eth.get_transaction_count(account.address),
                }
            )

            signed = self.key_storage.sign_transaction(tx, account.address)
            tx_hash = chain_interface.web3._web3.eth.send_raw_transaction(signed.raw_transaction)
            receipt = chain_interface.web3._web3.eth.wait_for_transaction_receipt(
                tx_hash, timeout=60
            )

            if receipt.status == 1:
                logger.info(f"Wrap successful! TX: {tx_hash.hex()}")
                return tx_hash.hex()
            else:
                logger.error(f"Wrap failed. TX: {tx_hash.hex()}")
                return None
        except Exception as e:
            logger.error(f"Error wrapping: {e}")
            return None

    def unwrap_native(
        self: "TransferService",
        account_address_or_tag: str,
        amount_wei: Optional[Wei] = None,
        chain_name: str = "gnosis",
    ) -> Optional[str]:
        """Unwrap wrapped token to native currency (e.g., WXDAI → xDAI).

        Args:
            account_address_or_tag: Account to unwrap from
            amount_wei: Amount in wei to unwrap (None = all balance)
            chain_name: Chain name (default: gnosis)

        Returns:
            Transaction hash if successful, None otherwise.

        """
        account = self.account_service.resolve_account(account_address_or_tag)
        if not account:
            logger.error(f"Account '{account_address_or_tag}' not found.")
            return None

        chain_interface = ChainInterfaces().get(chain_name)
        wrapped_token = chain_interface.chain.tokens.get("WXDAI")
        if not wrapped_token:
            logger.error(f"WXDAI not found on {chain_name}")
            return None

        # Get balance if amount not specified
        if amount_wei is None:
            amount_wei = self.balance_service.get_erc20_balance_wei(
                account.address, "WXDAI", chain_name
            )
            if not amount_wei or amount_wei == 0:
                logger.warning("No WXDAI balance to unwrap")
                return None

        # Simple WETH ABI for withdraw
        weth_abi = [
            {
                "constant": False,
                "inputs": [{"name": "wad", "type": "uint256"}],
                "name": "withdraw",
                "outputs": [],
                "payable": False,
                "type": "function",
            }
        ]

        contract = chain_interface.web3._web3.eth.contract(address=wrapped_token, abi=weth_abi)

        amount_eth = float(Web3.from_wei(amount_wei, "ether"))
        logger.info(f"Unwrapping {amount_eth:.4f} WXDAI → xDAI...")

        try:
            tx = contract.functions.withdraw(amount_wei).build_transaction(
                {
                    "from": account.address,
                    "gas": 100000,
                    "gasPrice": chain_interface.web3._web3.eth.gas_price,
                    "nonce": chain_interface.web3._web3.eth.get_transaction_count(account.address),
                }
            )

            signed = self.key_storage.sign_transaction(tx, account.address)
            tx_hash = chain_interface.web3._web3.eth.send_raw_transaction(signed.raw_transaction)
            receipt = chain_interface.web3._web3.eth.wait_for_transaction_receipt(
                tx_hash, timeout=60
            )

            if receipt.status == 1:
                logger.info(f"Unwrap successful! TX: {tx_hash.hex()}")
                return tx_hash.hex()
            else:
                logger.error(f"Unwrap failed. TX: {tx_hash.hex()}")
                return None
        except Exception as e:
            logger.error(f"Error unwrapping: {e}")
            return None
