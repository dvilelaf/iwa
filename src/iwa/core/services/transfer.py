"""Transfer service module."""

from typing import TYPE_CHECKING, Optional

from loguru import logger
from safe_eth.safe import SafeOperationEnum
from web3 import Web3
from web3.types import Wei

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
        self, token_symbol: str, amount_wei: Wei, chain_name: str
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

    def _is_whitelisted_destination(self, to_address: str) -> bool:
        """Check if destination address is whitelisted.

        An address is whitelisted if it's:
        1. One of our own accounts (from wallets.json)
        2. In the explicit whitelist in config.yaml [core.whitelist]

        Returns:
            True if allowed, False if blocked.

        """
        # Normalize address for comparison
        try:
            target_addr = EthereumAddress(to_address)
        except ValueError:
            logger.error(f"Invalid address format: {to_address}")
            return False

        # Check 1: Is it one of our own wallets?
        if self.account_service.resolve_account(to_address):
            return True

        # Check 2: Is it in the config whitelist?
        config = Config()
        if config.core and config.core.whitelist:
            if target_addr in config.core.whitelist.values():
                return True

        # Not in whitelist - block transaction
        logger.error(
            f"SECURITY: Destination {to_address} is NOT whitelisted. "
            "Transaction blocked. Add to config.yaml [core.whitelist] to allow."
        )
        return False

    def _is_supported_token(self, token_address_or_name: str, chain_name: str) -> bool:
        """Validate that the token is supported on this chain.

        Supported tokens are:
        1. Native currency
        2. Tokens defined in chain.tokens (defaults + custom_tokens)

        Returns:
            True if token is supported, False otherwise.

        """
        # Native currency is always allowed
        if token_address_or_name.lower() in ("native", NATIVE_CURRENCY_ADDRESS.lower()):
            return True

        chain_interface = ChainInterfaces().get(chain_name)
        supported_tokens = chain_interface.tokens

        # Check by name (e.g., "OLAS")
        if token_address_or_name.upper() in supported_tokens:
            return True

        # Check by address
        try:
            token_addr = EthereumAddress(token_address_or_name)
            if token_addr in supported_tokens.values():
                return True
        except ValueError:
            pass  # Not a valid address, already checked by name

        # Token not supported
        supported_list = ", ".join(supported_tokens.keys())
        logger.error(
            f"SECURITY: Token '{token_address_or_name}' is NOT supported on {chain_name}. "
            f"Supported tokens: {supported_list}. "
            "Add to config.yaml [core.custom_tokens] to allow."
        )
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
        self,
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

    def _send_erc20_via_safe(
        self,
        from_account: StoredSafeAccount,
        from_address_or_tag: str,
        to_address: str,
        amount_wei: Wei,
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
        amount_wei: Wei,
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
        amount_wei: Wei,
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

        # SECURITY: Validate destination is whitelisted
        if not self._is_whitelisted_destination(to_address):
            return None

        # SECURITY: Validate token is supported
        if not self._is_supported_token(token_address_or_name, chain_name):
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

    def multi_send(  # noqa: C901
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

        # Group ERC20s by token to check allowances if EOA
        erc20_totals = {}
        if not is_safe and not is_all_native:
            # Check allowances and approve if needed
            for tx in transactions:
                token_addr_or_tag = tx.get("token", NATIVE_CURRENCY_ADDRESS)
                if token_addr_or_tag != NATIVE_CURRENCY_ADDRESS:
                    token_address = self.account_service.get_token_address(
                        token_addr_or_tag, chain_interface.chain
                    )
                    amount_wei = chain_interface.web3.to_wei(tx["amount"], "ether")
                    erc20_totals[token_address] = erc20_totals.get(token_address, 0) + amount_wei

            for token_addr, total_amount in erc20_totals.items():
                self.approve_erc20(
                    owner_address_or_tag=from_address_or_tag,
                    spender_address_or_tag=MULTISEND_CALL_ONLY_ADDRESS,
                    token_address_or_name=token_addr,
                    amount_wei=total_amount,
                    chain_name=chain_name,
                )

        for tx in transactions:
            to = self.account_service.resolve_account(tx["to"])
            recipient_address = to.address if to else tx["to"]
            # Ensure recipient address is checksummed for Web3 compatibility
            recipient_address = chain_interface.web3.to_checksum_address(recipient_address)
            token_address_or_tag = tx.get("token", NATIVE_CURRENCY_ADDRESS)

            # Calculate amount_wei respecting the token's decimals
            if token_address_or_tag == NATIVE_CURRENCY_ADDRESS:
                amount_wei = chain_interface.web3.to_wei(tx["amount"], "ether")
            else:
                token_address = self.account_service.get_token_address(
                    token_address_or_tag, chain_interface.chain
                )
                erc20 = ERC20Contract(token_address, chain_name)
                # Use the token's actual decimals
                amount_wei = int(tx["amount"] * (10 ** erc20.decimals))

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
                # erc20 was already created above for decimal calculation

                if is_safe:
                    # Safe uses transfer() because it DelegateCalls the MultiSend (sender identity preserved)
                    transfer_tx = erc20.prepare_transfer_tx(
                        from_address=from_account.address,
                        to=recipient_address,
                        amount_wei=amount_wei,
                    )
                else:
                    # EOA uses transferFrom() because MultiSendCallOnly matches the calls (sender is MultiSend contract)
                    transfer_tx = erc20.prepare_transfer_from_tx(
                        from_address=from_account.address,
                        sender=from_account.address,
                        recipient=recipient_address,
                        amount_wei=amount_wei,
                    )

                if not transfer_tx:
                    logger.error(f"Failed to prepare transfer transaction for {token_address_or_tag}")
                    continue

                tx["to"] = erc20.address
                tx["value"] = 0
                tx["data"] = transfer_tx["data"]
                tx["operation"] = SafeOperationEnum.CALL

        # Filter out malformed transactions (those that failed to prepare)
        valid_transactions = [tx for tx in transactions if tx.get("operation") is not None]

        if not valid_transactions:
            logger.error("No valid transactions to send")
            return

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
            from_address=from_account.address, transactions=valid_transactions
        )
        if not transaction:
            return

        logger.info("Sending multisend transaction")

        if is_safe:
            return self.safe_service.execute_safe_transaction(
                safe_address_or_tag=from_address_or_tag,
                to=multi_send_contract.address,
                value=transaction["value"],
                chain_name=chain_name,
                data=transaction["data"],
                operation=SafeOperationEnum.DELEGATE_CALL.value,
            )
        else:
            return self.transaction_service.sign_and_send(
                transaction, from_address_or_tag, chain_name
            )

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
        amount_wei: Wei,
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
            success, _ = self.transaction_service.sign_and_send(
                transaction, owner_address_or_tag, chain_name
            )
            return success

    def transfer_from_erc20(
        self,
        from_address_or_tag: str,
        sender_address_or_tag: str,
        recipient_address_or_tag: str,
        token_address_or_name: str,
        amount_wei: Wei,
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

    async def swap(  # noqa: C901
        self,
        account_address_or_tag: str,
        amount_eth: Optional[float],
        sell_token_name: str,
        buy_token_name: str,
        chain_name: str = "gnosis",
        order_type: OrderType = OrderType.SELL,
    ) -> Optional[dict]:
        """Swap ERC-20 tokens on CowSwap.

        Returns:
            dict | None: The executed order data if successful, None otherwise.

        """
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
                return None

            cow = CowSwap(
                private_key_or_signer=signer,
                chain=chain,
            )

            # Check current allowance first
            current_allowance = self.get_erc20_allowance(
                owner_address_or_tag=account_address_or_tag,
                spender_address=COWSWAP_GPV2_VAULT_RELAYER_ADDRESS,
                token_address_or_name=sell_token_name,
                chain_name="gnosis",
            ) or 0

            # Calculate required amount
            required_amount = (
                amount_wei
                if order_type == OrderType.SELL
                else cow.get_max_sell_amount_wei(
                    amount_wei,
                    sell_token_name,
                    buy_token_name,
                )
            )

            # If allowance is insufficient, approve EXACT amount (No Infinite)
            if current_allowance < required_amount:
                logger.info(f"Insufficient allowance ({current_allowance} < {required_amount}). Approving EXACT amount.")
                self.approve_erc20(
                    owner_address_or_tag=account_address_or_tag,
                    spender_address_or_tag=COWSWAP_GPV2_VAULT_RELAYER_ADDRESS,
                    token_address_or_name=sell_token_name,
                    amount_wei=required_amount,
                    chain_name="gnosis",
                )
            else:
                logger.info(f"Allowance sufficient ({current_allowance} >= {required_amount}). Skipping approval.")

            result = await cow.swap(
                amount_wei=amount_wei,
                sell_token_name=sell_token_name,
                buy_token_name=buy_token_name,
                order_type=order_type,
            )

            if result:
                logger.info("Swap successful")

                # Log transaction and analytics
                try:
                    # Extract Data
                    executed_sell = float(result.get("executedSellAmount", 0))
                    executed_buy = float(result.get("executedBuyAmount", 0))
                    quote = result.get("quote", {})
                    sell_price_usd = float(quote.get("sellTokenPrice", 0) or 0)
                    buy_price_usd = float(quote.get("buyTokenPrice", 0) or 0)
                    tx_hash = result.get("txHash") or result.get("uid")

                    # Calculate Analytics
                    execution_price = 0.0
                    if executed_sell > 0:
                        execution_price = executed_buy / executed_sell # Raw ratio

                    value_sold = (executed_sell / 1e18) * sell_price_usd
                    value_bought = (executed_buy / 1e18) * buy_price_usd

                    value_change_pct = None
                    if value_sold > 0 and buy_price_usd > 0:
                        value_change_pct = ((value_bought - value_sold) / value_sold) * 100

                    # Prepare extra_data
                    analytics = {
                        "type": "swap",
                        "platform": "cowswap",
                        "sell_token": sell_token_name,
                        "buy_token": buy_token_name,
                        "executed_sell_amount": executed_sell,
                        "executed_buy_amount": executed_buy,
                        "sell_price_usd": sell_price_usd,
                        "buy_price_usd": buy_price_usd,
                        "execution_price": execution_price,
                        "value_change_pct": value_change_pct if value_change_pct is not None else "N/A"
                    }

                    # Log to DB if we have a tx_hash (CowSwap usually provides it in order info if confirmed)
                    if tx_hash:
                         from iwa.core.db import log_transaction
                         log_transaction(
                            tx_hash=tx_hash,
                            from_addr=account.address,
                            to_addr=COWSWAP_GPV2_VAULT_RELAYER_ADDRESS, # Or settlement contract
                            token=sell_token_name,
                            amount_wei=int(executed_sell),
                            chain=chain_name,
                            from_tag=account_address_or_tag,
                            tags=["swap", "cowswap", sell_token_name, buy_token_name],
                            gas_cost="0", # User doesn't pay gas for settlement (solver does)
                            gas_value_eur=0.0,
                            value_eur=float(value_sold) if value_sold > 0 else None, # Approximate as USD
                            extra_data=analytics
                         )

                    # Inject analytics back into result for API/Frontend
                    result["analytics"] = analytics

                except Exception as log_err:
                    logger.warning(f"Failed to log swap analytics: {log_err}")

                return result

            logger.error(f"Swap try {retries}/{max_retries}] failed")
            retries += 1

        logger.error("Max swap retries reached. Swap failed.")

    def drain(
        self,
        from_address_or_tag: str,
        to_address_or_tag: str = "master",
        chain_name: str = "gnosis",
    ):
        """Drain entire balance of an account to another account.

        For Safes that are Olas service multisigs, this will first claim any
        pending staking rewards before draining.

        Uses multi_send to batch all transfers (ERC20 + native) into a single
        transaction for gas efficiency.
        """
        from_account = self.account_service.resolve_account(from_address_or_tag)

        if not from_account:
            logger.error(f"From account '{from_address_or_tag}' not found in wallet.")
            return

        to_account = self.account_service.resolve_account(to_address_or_tag)
        to_address = to_account.address if to_account else to_address_or_tag

        is_safe = isinstance(from_account, StoredSafeAccount)
        chain_interface = ChainInterfaces().get(chain_name)

        # If this is a Safe, check if it's an Olas service multisig and claim rewards
        if is_safe:
            self._claim_olas_rewards_if_service(from_account.address, chain_name)

        transactions = []

        # Collect ERC-20 token transfers
        for token_name in chain_interface.chain.tokens.keys():
            balance_wei = self.balance_service.get_erc20_balance_wei(
                from_address_or_tag, token_name, chain_name
            )
            if balance_wei and balance_wei > 0:
                # Convert to ether for multi_send (which expects amount in ether)
                amount_ether = chain_interface.web3.from_wei(balance_wei, "ether")
                transactions.append(
                    {
                        "to": to_address,
                        "amount": float(amount_ether),
                        "token": token_name,
                    }
                )
                logger.info(f"Queued {amount_ether} {token_name} for drain.")
            else:
                logger.debug(f"No {token_name} to drain on {from_address_or_tag}.")

        # Calculate drainable native balance
        native_balance_wei = self.balance_service.get_native_balance_wei(from_account.address)
        if native_balance_wei and native_balance_wei > 0:
            if is_safe:
                # Safe pays gas from the Safe, so we can drain all
                drainable_balance_wei = native_balance_wei
            else:
                # EOA needs to reserve gas for the multi_send transaction
                # Estimate: base 21k + ~30k per transfer in batch + buffer
                num_transfers = len(transactions) + 1  # +1 for native
                estimated_gas = 50_000 + (30_000 * num_transfers)
                gas_cost_wei = chain_interface.web3.eth.gas_price * estimated_gas
                drainable_balance_wei = native_balance_wei - gas_cost_wei

            if drainable_balance_wei > 0:
                amount_ether = chain_interface.web3.from_wei(drainable_balance_wei, "ether")
                transactions.append(
                    {
                        "to": to_address,
                        "amount": float(amount_ether),
                        # No "token" key = native currency
                    }
                )
                logger.info(f"Queued {amount_ether} native for drain.")
            else:
                logger.info(
                    f"Not enough native balance to cover gas fees for draining from {from_address_or_tag}."
                )

        if not transactions:
            logger.info(f"Nothing to drain from {from_address_or_tag}.")
            return

        logger.info(
            f"Draining {len(transactions)} assets from {from_address_or_tag} to {to_address_or_tag}..."
        )
        return self.multi_send(
            from_address_or_tag=from_address_or_tag,
            transactions=transactions,
            chain_name=chain_name,
        )

    def _claim_olas_rewards_if_service(self, safe_address: str, chain_name: str) -> bool:
        """Check if Safe is an Olas service multisig and claim pending rewards.

        This is a best-effort operation - if the Olas plugin is not available or
        there's an error, it will log a warning and continue without failing.

        Args:
            safe_address: The Safe address to check.
            chain_name: The chain name.

        Returns:
            True if rewards were claimed, False otherwise.

        """
        try:
            # Import Olas plugin (optional dependency)
            from iwa.plugins.olas.models import OlasConfig
            from iwa.plugins.olas.service_manager import ServiceManager

            # Check if this Safe is an Olas service multisig
            config = Config()
            if "olas" not in config.plugins:
                return False

            olas_config: OlasConfig = config.plugins["olas"]
            service = olas_config.get_service_by_multisig(safe_address)

            if not service:
                logger.debug(f"Safe {safe_address} is not an Olas service multisig.")
                return False

            if not service.staking_contract_address:
                logger.debug(f"Olas service {service.key} is not staked.")
                return False

            logger.info(
                f"Safe {safe_address} is Olas service {service.key}. "
                "Checking for pending staking rewards..."
            )

            # Use ServiceManager to claim rewards
            # Need to import Wallet dynamically to avoid circular import
            from iwa.core.wallet import Wallet

            wallet = Wallet()
            service_manager = ServiceManager(wallet=wallet, service_key=service.key)
            success, claimed_amount = service_manager.claim_rewards()

            if success and claimed_amount > 0:
                claimed_olas = claimed_amount / 1e18
                logger.info(f"Claimed {claimed_olas:.4f} OLAS rewards before drain.")
                return True
            elif not success:
                logger.debug("No rewards to claim or claim failed.")

            return False

        except ImportError:
            logger.debug("Olas plugin not available, skipping reward claiming.")
            return False
        except Exception as e:
            logger.warning(f"Failed to check/claim Olas rewards: {e}")
            return False

    def wrap_native(
        self,
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
        self,
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
