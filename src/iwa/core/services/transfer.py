"""Transfer service module."""

from typing import TYPE_CHECKING, Optional

from loguru import logger
from safe_eth.safe import SafeOperationEnum
from web3 import Web3

from iwa.core.chain import ChainInterfaces
from iwa.core.constants import NATIVE_CURRENCY_ADDRESS
from iwa.core.contracts.erc20 import ERC20Contract
from iwa.core.contracts.multisend import (
    MULTISEND_ADDRESS,
    MULTISEND_CALL_ONLY_ADDRESS,
    MultiSendCallOnlyContract,
    MultiSendContract,
)
from iwa.core.db import log_transaction
from iwa.core.models import Config, EthereumAddress, StoredSafeAccount
from iwa.core.pricing import PriceService
from iwa.plugins.gnosis.cow import COWSWAP_GPV2_VAULT_RELAYER_ADDRESS, CowSwap, OrderType

# Coingecko IDs for tokens and native currencies
TOKEN_COINGECKO_IDS = {
    "XDAI": "xdai",
    "ETH": "ethereum",
    "OLAS": "autonolas",
    "USDC": "usdc",
    "WXDAI": "xdai",
    "SDAI": "savings-xdai",
    "EURE": "monerium-eur-money",
}

CHAIN_COINGECKO_IDS = {
    "gnosis": "dai",
    "ethereum": "ethereum",
    "base": "ethereum",
}

if TYPE_CHECKING:
    from iwa.core.keys import KeyStorage
    from iwa.core.services.account import AccountService
    from iwa.core.services.balance import BalanceService
    from iwa.core.services.safe import SafeService
    from iwa.core.services.transaction import TransactionService


class TransferService:
    """Service for handling transfers, swaps, and approvals."""

    def __init__(
        self,
        key_storage: "KeyStorage",
        account_service: "AccountService",
        balance_service: "BalanceService",
        safe_service: "SafeService",
        transaction_service: "TransactionService",
    ):
        """Initialize TransferService."""
        self.key_storage = key_storage
        self.account_service = account_service
        self.balance_service = balance_service
        self.safe_service = safe_service
        self.transaction_service = transaction_service

    def _resolve_destination(self, to_address_or_tag: str) -> tuple[Optional[str], Optional[str]]:
        """Resolve destination address and tag.

        Returns:
            Tuple of (address, tag) or (None, None) if invalid.

        """
        to_account = self.account_service.resolve_account(to_address_or_tag)
        if to_account:
            return to_account.address, getattr(to_account, "tag", None)

        try:
            to_address = EthereumAddress(to_address_or_tag)
            # Try to find tag in whitelist
            to_tag = self._resolve_whitelist_tag(to_address)
            return to_address, to_tag
        except ValueError:
            logger.error(f"Invalid destination address: {to_address_or_tag}")
            return None, None

    def _resolve_whitelist_tag(self, address: str) -> Optional[str]:
        """Resolve tag from whitelist for an address."""
        config = Config()
        if config.core and config.core.whitelist:
            try:
                target_addr = EthereumAddress(address)
                for name, addr in config.core.whitelist.items():
                    if addr == target_addr:
                        return name
            except ValueError:
                pass
        return None

    def _calculate_gas_info(
        self, receipt: Optional[dict], chain_name: str
    ) -> tuple[Optional[int], Optional[float]]:
        """Calculate gas cost and gas value in EUR from transaction receipt.

        Args:
            receipt: Transaction receipt containing gasUsed and effectiveGasPrice.
            chain_name: Name of the chain for price lookup.

        Returns:
            Tuple of (gas_cost_wei, gas_value_eur) or (None, None) if unavailable.

        """
        if not receipt:
            return None, None

        try:
            gas_used = receipt.get("gasUsed", 0)
            effective_gas_price = receipt.get("effectiveGasPrice", 0)
            gas_cost_wei = gas_used * effective_gas_price

            # Get native token price
            coingecko_id = CHAIN_COINGECKO_IDS.get(chain_name, "ethereum")
            price_service = PriceService()
            native_price_eur = price_service.get_token_price(coingecko_id, "eur")

            gas_value_eur = None
            if native_price_eur and gas_cost_wei > 0:
                gas_cost_eth = gas_cost_wei / 10**18
                gas_value_eur = gas_cost_eth * native_price_eur

            return gas_cost_wei, gas_value_eur
        except Exception as e:
            logger.warning(f"Failed to calculate gas info: {e}")
            return None, None

    def _get_token_price_info(
        self, token_symbol: str, amount_wei: int, chain_name: str
    ) -> tuple[Optional[float], Optional[float]]:
        """Calculate token price and total value in EUR.

        Args:
            token_symbol: Token symbol (e.g. 'OLAS', 'ETH')
            amount_wei: Amount in wei
            chain_name: Chain name

        Returns:
            Tuple of (price_eur, value_eur) or (None, None) if unavailable.

        """
        try:
            # Map symbol to coingecko id
            symbol_upper = token_symbol.upper()
            cg_id = TOKEN_COINGECKO_IDS.get(symbol_upper)
            if not cg_id:
                # Try name mapping if it's native signal
                if symbol_upper in ["NATIVE", "TOKEN"]:
                    cg_id = CHAIN_COINGECKO_IDS.get(chain_name.lower())

            if not cg_id:
                return None, None

            price_service = PriceService()
            price_eur = price_service.get_token_price(cg_id, "eur")

            if price_eur is None:
                return None, None

            # Get decimals for value calculation
            interface = ChainInterfaces().get(chain_name)
            decimals = 18
            if symbol_upper not in ["NATIVE", "TOKEN", "XDAI", "ETH"]:
                token_address = interface.chain.get_token_address(token_symbol)
                if token_address:
                    decimals = interface.get_token_decimals(token_address)

            value_eur = (amount_wei / 10**decimals) * price_eur
            return price_eur, value_eur
        except Exception as e:
            logger.warning(f"Failed to calculate token price info for {token_symbol}: {e}")
            return None, None

    def _check_whitelist(self, to_address: str) -> bool:
        """Check if address is in whitelist.

        Returns:
            True if allowed (no whitelist or address is in it), False otherwise.

        """
        config = Config()
        if not (config.core and config.core.whitelist):
            return True

        try:
            target_addr = EthereumAddress(to_address)
            if target_addr in config.core.whitelist.values():
                return True
        except ValueError:
            pass

        logger.error(f"Address '{to_address}' is not in the whitelist. Transaction blocked.")
        return False

    def _resolve_token_symbol(
        self, token_address: str, token_address_or_name: str, chain_interface
    ) -> str:
        """Resolve token symbol for logging."""
        if token_address == NATIVE_CURRENCY_ADDRESS:
            return chain_interface.chain.native_currency

        if not token_address_or_name.startswith("0x"):
            return token_address_or_name

        for name, addr in chain_interface.tokens.items():
            if addr == token_address:
                return name

        return token_address_or_name

    def _send_native_via_safe(
        self,
        from_account: StoredSafeAccount,
        from_address_or_tag: str,
        to_address: str,
        amount_wei: int,
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
        self,
        from_account,
        to_address: str,
        amount_wei: int,
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

    def _send_erc20_via_safe(
        self,
        from_account: StoredSafeAccount,
        from_address_or_tag: str,
        to_address: str,
        amount_wei: int,
        chain_name: str,
        erc20: ERC20Contract,
        transaction: dict,
        from_tag: Optional[str],
        to_tag: Optional[str],
        token_symbol: str,
    ) -> str:
        """Send ERC20 token via Safe multisig."""
        tx_hash = self.safe_service.execute_safe_transaction(
            safe_address_or_tag=from_address_or_tag,
            to=erc20.address,
            value=0,
            chain_name=chain_name,
            data=transaction["data"],
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
            tags=["erc20-transfer", "safe-transaction"],
        )
        return tx_hash

    def _send_erc20_via_eoa(
        self,
        from_account,
        from_address_or_tag: str,
        to_address: str,
        amount_wei: int,
        chain_name: str,
        transaction: dict,
        from_tag: Optional[str],
        to_tag: Optional[str],
        token_symbol: str,
    ) -> Optional[str]:
        """Send ERC20 token via EOA (externally owned account)."""
        success, receipt = self.transaction_service.sign_and_send(
            transaction, from_address_or_tag, chain_name
        )
        if success and receipt:
            tx_hash = receipt["transactionHash"].hex()
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
                tags=["erc20-transfer"],
            )
            return tx_hash
        return None

    def send(
        self,
        from_address_or_tag: str,
        to_address_or_tag: str,
        amount_wei: int,
        token_address_or_name: str = "native",
        chain_name: str = "gnosis",
    ) -> Optional[str]:
        """Send native currency or ERC20 token.

        Args:
            from_address_or_tag: Source account address or tag
            to_address_or_tag: Destination address or tag
            amount_wei: Amount in wei
            token_address_or_name: Token address, name, or "native"
            chain_name: Chain name (default: "gnosis")

        Returns:
            Transaction hash if successful, None otherwise.

        """
        # Resolve accounts
        from_account = self.account_service.resolve_account(from_address_or_tag)
        if not from_account:
            logger.error(f"From account '{from_address_or_tag}' not found in wallet.")
            return None

        to_address, to_tag = self._resolve_destination(to_address_or_tag)
        if not to_address:
            return None

        # Whitelist check
        if not self._check_whitelist(to_address):
            return None

        # Resolve chain and token
        chain_interface = ChainInterfaces().get(chain_name)
        token_address = self.account_service.get_token_address(
            token_address_or_name, chain_interface.chain
        )
        if not token_address:
            return None

        # Resolve tags and symbols for logging
        from_tag = self.account_service.get_tag_by_address(from_account.address)
        token_symbol = self._resolve_token_symbol(
            token_address, token_address_or_name, chain_interface
        )
        is_safe = isinstance(from_account, StoredSafeAccount)

        # Native currency transfer
        if token_address == NATIVE_CURRENCY_ADDRESS:
            amount_eth = float(chain_interface.web3.from_wei(amount_wei, "ether"))
            logger.info(
                f"Sending {amount_eth:.4f} {chain_interface.chain.native_currency} "
                f"from {from_address_or_tag} to {to_address_or_tag}"
            )
            if is_safe:
                return self._send_native_via_safe(
                    from_account,
                    from_address_or_tag,
                    to_address,
                    amount_wei,
                    chain_name,
                    from_tag,
                    to_tag,
                    token_symbol,
                )
            return self._send_native_via_eoa(
                from_account,
                to_address,
                amount_wei,
                chain_name,
                chain_interface,
                from_tag,
                to_tag,
                token_symbol,
            )

        # ERC20 token transfer
        erc20 = ERC20Contract(token_address, chain_name)
        transaction = erc20.prepare_transfer_tx(from_account.address, to_address, amount_wei)
        if not transaction:
            return None

        amount_eth = float(chain_interface.web3.from_wei(amount_wei, "ether"))
        logger.info(
            f"Sending {amount_eth:.4f} {token_address_or_name} "
            f"from {from_address_or_tag} to {to_address_or_tag}"
        )

        if is_safe:
            return self._send_erc20_via_safe(
                from_account,
                from_address_or_tag,
                to_address,
                amount_wei,
                chain_name,
                erc20,
                transaction,
                from_tag,
                to_tag,
                token_symbol,
            )
        return self._send_erc20_via_eoa(
            from_account,
            from_address_or_tag,
            to_address,
            amount_wei,
            chain_name,
            transaction,
            from_tag,
            to_tag,
            token_symbol,
        )

    def multi_send(
        self,
        from_address_or_tag: str,
        transactions: list,
        chain_name: str = "gnosis",
    ):
        """Send multiple transactions in a single multisend transaction."""
        from_account = self.account_service.resolve_account(from_address_or_tag)
        is_safe = isinstance(from_account, StoredSafeAccount)

        if not from_account:
            logger.error(f"From account '{from_address_or_tag}' not found in wallet.")
            return

        chain_interface = ChainInterfaces().get(chain_name)

        is_all_native = all(
            tx.get("token", NATIVE_CURRENCY_ADDRESS) == NATIVE_CURRENCY_ADDRESS
            for tx in transactions
        )

        if not is_safe and not is_all_native:
            raise ValueError("Multisend with ERC20 tokens requires a Safe account.")

        for tx in transactions:
            to = self.account_service.resolve_account(tx["to"])
            recipient_address = to.address if to else tx["to"]
            amount_wei = chain_interface.web3.to_wei(tx["amount"], "ether")
            token_address_or_tag = tx.get("token", NATIVE_CURRENCY_ADDRESS)
            if "amount" in tx:
                del tx["amount"]
            if "token" in tx:
                del tx["token"]

            if token_address_or_tag == NATIVE_CURRENCY_ADDRESS:
                tx["to"] = recipient_address
                tx["value"] = amount_wei
                tx["data"] = b""
                tx["operation"] = SafeOperationEnum.CALL

            else:
                token_address = self.account_service.get_token_address(
                    token_address_or_tag, chain_interface.chain
                )
                erc20 = ERC20Contract(token_address, chain_name)
                transfer_tx = erc20.prepare_transfer_tx(
                    from_address=from_account.address,
                    to=recipient_address,
                    amount_wei=amount_wei,
                )
                tx["to"] = erc20.address
                tx["value"] = 0
                tx["data"] = transfer_tx["data"]
                tx["operation"] = SafeOperationEnum.CALL

        multi_send_normal_contract = MultiSendContract(
            address=MULTISEND_ADDRESS, chain_name=chain_name
        )
        multi_send_call_only_contract = MultiSendCallOnlyContract(
            address=MULTISEND_CALL_ONLY_ADDRESS, chain_name=chain_name
        )

        multi_send_contract = (
            multi_send_normal_contract if is_safe else multi_send_call_only_contract
        )
        transaction = multi_send_contract.prepare_tx(
            from_address=from_account.address, transactions=transactions
        )
        if not transaction:
            return

        logger.info("Sending multisend transaction")

        if is_safe:
            self.safe_service.execute_safe_transaction(
                safe_address_or_tag=from_address_or_tag,
                to=multi_send_contract.address,
                value=transaction["value"],
                chain_name=chain_name,
                data=transaction["data"],
                operation=SafeOperationEnum.DELEGATE_CALL.value,
            )
        else:
            self.transaction_service.sign_and_send(transaction, from_address_or_tag, chain_name)

    def get_erc20_allowance(
        self,
        owner_address_or_tag: str,
        spender_address: str,
        token_address_or_name: str,
        chain_name: str = "gnosis",
    ) -> Optional[float]:
        """Get ERC20 token allowance."""
        chain = ChainInterfaces().get(chain_name)

        token_address = self.account_service.get_token_address(token_address_or_name, chain.chain)
        if not token_address:
            return None

        owner_account = self.account_service.resolve_account(owner_address_or_tag)
        if not owner_account:
            return None

        contract = ERC20Contract(chain_name=chain_name, address=token_address)
        return contract.allowance_wei(owner_account.address, spender_address)

    def approve_erc20(
        self,
        owner_address_or_tag: str,
        spender_address_or_tag: str,
        token_address_or_name: str,
        amount_wei: int,
        chain_name: str = "gnosis",
    ) -> bool:
        """Approve ERC20 token allowance."""
        owner_account = self.account_service.resolve_account(owner_address_or_tag)
        spender_account = self.account_service.resolve_account(spender_address_or_tag)
        spender_address = spender_account.address if spender_account else spender_address_or_tag

        if not owner_account:
            logger.error(f"Owner account '{owner_address_or_tag}' not found in wallet.")
            return False

        chain_interface = ChainInterfaces().get(chain_name)

        token_address = self.account_service.get_token_address(
            token_address_or_name, chain_interface.chain
        )
        if not token_address:
            return False

        erc20 = ERC20Contract(token_address, chain_name)

        allowance_wei = self.get_erc20_allowance(
            owner_address_or_tag,
            spender_address,
            token_address_or_name,
            chain_name,
        )
        if allowance_wei is not None and allowance_wei >= amount_wei:
            logger.info("Current allowance is sufficient. No need to approve.")
            return True

        transaction = erc20.prepare_approve_tx(
            from_address=owner_account.address,
            spender=spender_address,
            amount_wei=amount_wei,
        )
        if not transaction:
            return False

        is_safe = isinstance(owner_account, StoredSafeAccount)
        amount_eth = float(chain_interface.web3.from_wei(amount_wei, "ether"))

        logger.info(
            f"Approving {spender_address} to spend {amount_eth:.4f} {token_address_or_name} from {owner_address_or_tag}"
        )

        if is_safe:
            tx_limit = self.safe_service.execute_safe_transaction(
                safe_address_or_tag=owner_address_or_tag,
                to=erc20.address,
                value=0,
                chain_name=chain_name,
                data=transaction["data"],
            )
            return bool(tx_limit)
        else:
            success, _ = self.transaction_service.sign_and_send(transaction, owner_address_or_tag, chain_name)
            return success

    def transfer_from_erc20(
        self,
        from_address_or_tag: str,
        sender_address_or_tag: str,
        recipient_address_or_tag: str,
        token_address_or_name: str,
        amount_wei: int,
        chain_name: str = "gnosis",
    ):
        """TransferFrom ERC20 tokens."""
        from_account = self.account_service.resolve_account(from_address_or_tag)
        sender_account = self.account_service.resolve_account(sender_address_or_tag)
        recipient_account = self.account_service.resolve_account(recipient_address_or_tag)
        recipient_address = (
            recipient_account.address if recipient_account else recipient_address_or_tag
        )

        if not sender_account:
            logger.error(f"Sender account '{sender_address_or_tag}' not found in wallet.")
            return None

        chain_interface = ChainInterfaces().get(chain_name)

        token_address = self.account_service.get_token_address(
            token_address_or_name, chain_interface.chain
        )
        if not token_address:
            return

        erc20 = ERC20Contract(token_address, chain_name)
        transaction = erc20.prepare_transfer_from_tx(
            from_address=from_account.address,
            sender=sender_account.address,
            recipient=recipient_address,
            amount_wei=amount_wei,
        )
        if not transaction:
            return

        is_safe = isinstance(from_account, StoredSafeAccount)

        logger.info("Transferring ERC20 tokens via TransferFrom")

        if is_safe:
            self.safe_service.execute_safe_transaction(
                safe_address_or_tag=from_address_or_tag,
                to=erc20.address,
                value=0,
                chain_name=chain_name,
                data=transaction["data"],
            )
        else:
            self.transaction_service.sign_and_send(transaction, from_address_or_tag, chain_name)

    async def swap(
        self,
        account_address_or_tag: str,
        amount_eth: Optional[float],
        sell_token_name: str,
        buy_token_name: str,
        chain_name: str = "gnosis",
        order_type: OrderType = OrderType.SELL,
    ) -> bool:
        """Swap ERC-20 tokens on CowSwap."""
        if amount_eth is None:
            if order_type == OrderType.BUY:
                raise ValueError("Amount must be specified for buy orders.")

            logger.info(f"Swapping entire {sell_token_name} balance to {buy_token_name}")
            amount_wei = self.balance_service.get_erc20_balance_wei(
                account_address_or_tag, sell_token_name, chain_name
            )
        else:
            amount_wei = Web3.to_wei(amount_eth, "ether")

        chain = ChainInterfaces().get(chain_name).chain
        account = self.account_service.resolve_account(account_address_or_tag)

        retries = 1
        max_retries = 3
        while retries < max_retries + 1:
            # Get signer (LocalAccount)
            signer = self.key_storage.get_signer(account.address)
            if not signer:
                logger.error(f"Could not retrieve signer for {account_address_or_tag}")
                return False

            cow = CowSwap(
                private_key_or_signer=signer,
                chain=chain,
            )

            approval_amount_wei = (
                amount_wei
                if order_type == OrderType.SELL
                else cow.get_max_sell_amount_wei(
                    amount_wei,
                    sell_token_name,
                    buy_token_name,
                )
            )

            self.approve_erc20(
                owner_address_or_tag=account_address_or_tag,
                spender_address_or_tag=COWSWAP_GPV2_VAULT_RELAYER_ADDRESS,
                token_address_or_name=sell_token_name,
                amount_wei=approval_amount_wei,
                chain_name="gnosis",
            )

            success = await cow.swap(
                amount_wei=amount_wei,
                sell_token_name=sell_token_name,
                buy_token_name=buy_token_name,
                order_type=order_type,
            )
            if success:
                logger.info("Swap successful")
                return True

            logger.error(f"Swap try {retries}/{max_retries}] failed")
            retries += 1

        logger.error("Max swap retries reached. Swap failed.")

    def drain(
        self,
        from_address_or_tag: str,
        to_address_or_tag: str = "master",
        chain_name: str = "gnosis",
    ):
        """Drain entire balance of an account to another account."""
        from_account = self.account_service.resolve_account(from_address_or_tag)

        if not from_account:
            logger.error(f"From account '{from_address_or_tag}' not found in wallet.")
            return

        is_safe = isinstance(from_account, StoredSafeAccount)
        chain_interface = ChainInterfaces().get(chain_name)

        # ERC-20 tokens
        for token_name in chain_interface.chain.tokens.keys():
            balance_wei = self.balance_service.get_erc20_balance_wei(
                from_address_or_tag, token_name, chain_name
            )
            if balance_wei and balance_wei > 0:
                self.send(
                    from_address_or_tag=from_address_or_tag,
                    to_address_or_tag=to_address_or_tag,
                    token_address_or_name=token_name,
                    amount_wei=balance_wei,
                    chain_name=chain_name,
                )
            else:
                logger.info(f"No {token_name} to drain on {from_address_or_tag}.")

        # Native currency
        native_balance_wei = self.balance_service.get_native_balance_wei(from_account.address)
        if native_balance_wei and native_balance_wei > 0:
            if is_safe:
                drainable_balance_wei = native_balance_wei
            else:
                # Estimate gas cost
                estimated_gas = (
                    30_000  # Basic transfer gas is 21_000 EOA->EOA. but more expensive EOA->Safe
                )
                gas_cost_wei = chain_interface.web3.eth.gas_price * estimated_gas
                drainable_balance_wei = native_balance_wei - gas_cost_wei

            if drainable_balance_wei <= 0:
                logger.info(
                    f"Not enough native balance to cover gas fees for draining from {from_address_or_tag}."
                )
                return

            self.send(
                from_address_or_tag=from_address_or_tag,
                to_address_or_tag=to_address_or_tag,
                token_address_or_name=NATIVE_CURRENCY_ADDRESS,
                amount_wei=drainable_balance_wei,
                chain_name=chain_name,
            )
