"""Wallet module."""

from typing import Dict, Optional, Tuple

from safe_eth.safe import SafeOperationEnum
from web3 import Web3

from iwa.core.chain import ChainInterfaces, SupportedChain
from iwa.core.constants import NATIVE_CURRENCY_ADDRESS
from iwa.core.contracts.erc20 import ERC20Contract
from iwa.core.contracts.multisend import (
    MULTISEND_ADDRESS_GNOSIS,
    MULTISEND_CALL_ONLY_ADDRESS_GNOSIS,
    MultiSendCallOnlyContract,
    MultiSendContract,
)
from iwa.core.db import init_db, log_transaction
from iwa.core.keys import KeyStorage
from iwa.core.managers import TransactionManager
from iwa.core.models import Config, EthereumAddress, StoredSafeAccount
from iwa.core.tables import list_accounts
from iwa.core.utils import configure_logger
from iwa.plugins.gnosis.cow import COWSWAP_GPV2_VAULT_RELAYER_ADDRESS, CowSwap, OrderType
from iwa.plugins.gnosis.safe import SafeMultisig

logger = configure_logger()


class Wallet:
    """Wallet management"""

    def __init__(self):
        """Initialize wallet."""
        self.key_storage = KeyStorage()
        self.transaction_manager = TransactionManager(self.key_storage)
        init_db()

    @property
    def master_account(self) -> Optional[StoredSafeAccount]:
        """Get master account"""
        return self.key_storage.master_account

    def get_token_address(
        self, token_address_or_name: str, chain: SupportedChain
    ) -> Optional[EthereumAddress]:
        """Get token address from address or name"""
        if token_address_or_name == "native":
            return EthereumAddress(NATIVE_CURRENCY_ADDRESS)

        try:
            token_address = EthereumAddress(token_address_or_name)
            return token_address
        except ValueError:
            token_address = chain.get_token_address(token_address_or_name)
            if not token_address:
                logger.error(f"Token '{token_address_or_name}' not found on chain '{chain.name}'.")
                return None
            return token_address

    def list_accounts(self, chain_name: str, balances: Optional[str] = None) -> None:
        """List accounts"""
        chain_interface = ChainInterfaces().get(chain_name)
        token_names = balances.split(",") if balances else []

        token_balances = (
            {
                account_address: {
                    token_name: self.get_erc20_balance_eth(account_address, token_name)
                    if token_name != "native"
                    else chain_interface.get_native_balance_eth(account_address)
                    for token_name in token_names
                }
                for account_address in self.key_storage.accounts.keys()
            }
            if token_names
            else None
        )

        list_accounts(self.key_storage.accounts, chain_interface, token_names, token_balances)

    def sign_and_send_transaction(
        self, transaction: dict, signer_address_or_tag: str, chain_name: str = "gnosis"
    ) -> Tuple[bool, Dict]:
        """Sign and send transaction"""
        return self.transaction_manager.sign_and_send(
            transaction, signer_address_or_tag, chain_name
        )

    def send(  # noqa: C901
        self,
        from_address_or_tag: str,
        to_address_or_tag: str,
        token_address_or_name: str,
        amount_wei: int,
        chain_name: str = "gnosis",
    ) -> str:
        """Send native currency or ERC20 tokens to an address"""
        from_account = self.key_storage.get_account(from_address_or_tag)
        to_account = self.key_storage.get_account(to_address_or_tag)
        to_address = to_account.address if to_account else to_address_or_tag

        if not from_account:
            logger.error(f"From account '{from_address_or_tag}' not found in wallet.")
            return

        # Whitelist Check
        config = Config()
        if config.core and config.core.whitelist:
            # Check if to_address is one of the whitelisted addresses
            is_allowed = False
            try:
                target_addr = EthereumAddress(to_address)
                if target_addr in config.core.whitelist.values():
                    is_allowed = True
            except ValueError:
                pass

            if not is_allowed:
                logger.error(
                    f"Address '{to_address}' is not in the whitelist. Transaction blocked."
                )
                return

        chain_interface = ChainInterfaces().get(chain_name)

        token_address = self.get_token_address(token_address_or_name, chain_interface.chain)
        if not token_address:
            return

        # Resolve tags and symbols for logging
        from_tag = self.key_storage.get_tag_by_address(from_account.address)

        to_tag = getattr(to_account, "tag", None)
        if not to_tag:
            try:
                # Check whitelist
                if config.core and config.core.whitelist:
                    target_addr = EthereumAddress(to_address)
                    for name, addr in config.core.whitelist.items():
                        if addr == target_addr:
                            to_tag = name
                            break
            except ValueError:
                pass

        token_symbol = None
        if token_address == NATIVE_CURRENCY_ADDRESS:
            token_symbol = chain_interface.chain.native_currency
        else:
            if not token_address_or_name.startswith("0x"):
                token_symbol = token_address_or_name
            else:
                # Try reverse lookup
                for name, addr in chain_interface.tokens.items():
                    if addr == token_address:
                        token_symbol = name
                        break

        is_safe = isinstance(from_account, StoredSafeAccount)

        if token_address == NATIVE_CURRENCY_ADDRESS:
            logger.info(
                f"Sending {chain_interface.web3.from_wei(amount_wei, 'ether'):.4f} {chain_interface.chain.native_currency} from {from_address_or_tag} to {to_address_or_tag}"
            )
            if is_safe:
                safe = SafeMultisig(from_account, chain_name)
                tx_hash = safe.send_tx(
                    to=to_address,
                    value=amount_wei,
                    signers_private_keys=self.key_storage.get_safe_signer_keys(from_address_or_tag),
                )
                log_transaction(
                    tx_hash,
                    from_account.address,
                    to_address,
                    token_symbol,
                    amount_wei,
                    chain_name,
                    from_tag,
                    to_tag,
                    token_symbol,
                )
                return tx_hash

            else:
                success, tx_hash = chain_interface.send_native_transfer(
                    from_account=from_account,
                    to_address=to_address,
                    value_wei=amount_wei,
                )
                if success and tx_hash:
                    log_transaction(
                        tx_hash,
                        from_account.address,
                        to_address,
                        token_symbol,
                        amount_wei,
                        chain_name,
                        from_tag,
                        to_tag,
                        token_symbol,
                    )
                    return tx_hash
            return None

        erc20 = ERC20Contract(token_address)
        transaction = erc20.prepare_transfer_tx(
            from_account.address,
            to_address,
            amount_wei,
        )
        if not transaction:
            return

        amount_eth = chain_interface.web3.from_wei(amount_wei, "ether")
        logger.info(
            f"Sending {amount_eth:.4f} {token_address_or_name} from {from_address_or_tag} to {to_address_or_tag}"
        )

        if is_safe:
            safe = SafeMultisig(from_account, chain_name)
            tx_hash = safe.send_tx(
                to=erc20.address,
                value=0,
                signers_private_keys=self.key_storage.get_safe_signer_keys(from_address_or_tag),
                data=transaction["data"],
            )
            log_transaction(
                tx_hash,
                from_account.address,
                to_address,
                token_address_or_name,
                amount_wei,
                chain_name,
                from_tag,
                to_tag,
                token_symbol,
            )
            return tx_hash
        else:
            success, receipt = self.sign_and_send_transaction(
                transaction, from_address_or_tag, chain_name
            )
            if success and receipt:
                tx_hash = receipt["transactionHash"].hex()
                log_transaction(
                    tx_hash,
                    from_account.address,
                    to_address,
                    token_address_or_name,
                    amount_wei,
                    chain_name,
                    from_tag,
                    to_tag,
                    token_symbol,
                )
                return tx_hash

    def multi_send(
        self,
        from_address_or_tag: str,
        transactions: list,
        chain_name: str = "gnosis",
    ):
        """Send multiple transactions in a single multisend transaction"""
        from_account = self.key_storage.get_account(from_address_or_tag)
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
            to = self.key_storage.get_account(tx["to"])
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
                token_address = self.get_token_address(token_address_or_tag, chain_interface.chain)
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
            address=MULTISEND_ADDRESS_GNOSIS, chain_name=chain_name
        )
        multi_send_call_only_contract = MultiSendCallOnlyContract(
            address=MULTISEND_CALL_ONLY_ADDRESS_GNOSIS, chain_name=chain_name
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
            safe = SafeMultisig(from_account, chain_name)
            safe.send_tx(
                to=multi_send_contract.address,
                value=transaction["value"],
                signers_private_keys=self.key_storage.get_safe_signer_keys(from_address_or_tag),
                data=transaction["data"],
                operation=SafeOperationEnum.DELEGATE_CALL.value,
            )
        else:
            self.sign_and_send_transaction(transaction, from_address_or_tag, chain_name)

    def get_native_balance_eth(
        self, account_address: str, chain_name: str = "gnosis"
    ) -> Optional[float]:
        """Get native currency balance"""
        chain_interface = ChainInterfaces().get(chain_name)
        return chain_interface.get_native_balance_eth(account_address)

    def get_native_balance_wei(
        self, account_address: str, chain_name: str = "gnosis"
    ) -> Optional[int]:
        """Get native currency balance"""
        chain_interface = ChainInterfaces().get(chain_name)
        return chain_interface.get_native_balance_wei(account_address)

    def get_erc20_balance_eth(
        self, account_address_or_tag: str, token_address_or_name: str, chain_name: str = "gnosis"
    ) -> Optional[float]:
        """Get ERC20 token balance"""
        chain = ChainInterfaces().get(chain_name)

        token_address = self.get_token_address(token_address_or_name, chain.chain)
        if not token_address:
            return None

        account = self.key_storage.get_account(account_address_or_tag)
        if not account:
            return None

        contract = ERC20Contract(chain_name=chain_name, address=token_address)
        return contract.balance_of_eth(account.address)

    def get_erc20_balance_wei(
        self, account_address_or_tag: str, token_address_or_name: str, chain_name: str = "gnosis"
    ) -> Optional[int]:
        """Get ERC20 token balance"""
        chain = ChainInterfaces().get(chain_name)

        token_address = self.get_token_address(token_address_or_name, chain.chain)
        if not token_address:
            return None

        account = self.key_storage.get_account(account_address_or_tag)
        if not account:
            return None

        contract = ERC20Contract(chain_name=chain_name, address=token_address)
        return contract.balance_of_wei(account.address)

    def get_erc20_allowance(
        self,
        owner_address_or_tag: str,
        spender_address: str,
        token_address_or_name: str,
        chain_name: str = "gnosis",
    ) -> Optional[float]:
        """Get ERC20 token allowance"""
        chain = ChainInterfaces().get(chain_name)

        token_address = self.get_token_address(token_address_or_name, chain.chain)
        if not token_address:
            return None

        owner_account = self.key_storage.get_account(owner_address_or_tag)
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
    ):
        """Approve ERC20 token allowance"""
        owner_account = self.key_storage.get_account(owner_address_or_tag)
        spender_account = self.key_storage.get_account(spender_address_or_tag)
        spender_address = spender_account.address if spender_account else spender_address_or_tag

        if not owner_account:
            logger.error(f"Owner account '{owner_address_or_tag}' not found in wallet.")
            return None

        chain_interface = ChainInterfaces().get(chain_name)

        token_address = self.get_token_address(token_address_or_name, chain_interface)
        if not token_address:
            return

        erc20 = ERC20Contract(token_address, chain_name)

        allowance_wei = self.get_erc20_allowance(
            owner_address_or_tag,
            spender_address,
            token_address_or_name,
            chain_name,
        )
        if allowance_wei is not None and allowance_wei >= amount_wei:
            logger.info("Current allowance is sufficient. No need to approve.")
            return

        transaction = erc20.prepare_approve_tx(
            from_address=owner_account.address,
            spender=spender_address,
            amount_wei=amount_wei,
        )
        if not transaction:
            return

        is_safe = isinstance(owner_account, StoredSafeAccount)
        amount_eth = chain_interface.web3.from_wei(amount_wei, "ether")

        logger.info(
            f"Approving {spender_address} to spend {amount_eth:.4f} {token_address_or_name} from {owner_address_or_tag}"
        )

        if is_safe:
            safe = SafeMultisig(owner_account, chain_name)
            safe.send_tx(
                to=erc20.address,
                value=0,
                signers_private_keys=self.key_storage.get_safe_signer_keys(owner_address_or_tag),
                data=transaction["data"],
            )
        else:
            self.sign_and_send_transaction(transaction, owner_address_or_tag, chain_name)

    def transfer_from_erc20(
        self,
        from_address_or_tag: str,
        sender_address_or_tag: str,
        recipient_address_or_tag: str,
        token_address_or_name: str,
        amount_wei: int,
        chain_name: str = "gnosis",
    ):
        """TransferFrom ERC20 tokens"""
        from_account = self.key_storage.get_account(from_address_or_tag)
        sender_account = self.key_storage.get_account(sender_address_or_tag)
        recipient_account = self.key_storage.get_account(recipient_address_or_tag)
        recipient_address = (
            recipient_account.address if recipient_account else recipient_address_or_tag
        )

        if not sender_account:
            logger.error(f"Sender account '{sender_address_or_tag}' not found in wallet.")
            return None

        chain_interface = ChainInterfaces().get(chain_name)

        token_address = self.get_token_address(token_address_or_name, chain_interface)
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
            safe = SafeMultisig(from_account, chain_name)
            safe.send_tx(
                to=erc20.address,
                value=0,
                signers_private_keys=self.key_storage.get_safe_signer_keys(from_address_or_tag),
                data=transaction["data"],
            )
        else:
            self.sign_and_send_transaction(transaction, from_address_or_tag, chain_name)

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
            amount_wei = self.get_erc20_balance_wei(
                account_address_or_tag, sell_token_name, chain_name
            )
        else:
            amount_wei = Web3.to_wei(amount_eth, "ether")

        chain = ChainInterfaces().get(chain_name).chain
        account = self.key_storage.get_account(account_address_or_tag)

        retries = 1
        max_retries = 3
        while retries < max_retries + 1:
            # CowSwap SDK requires private key. Using unsafe access as per requirements.
            unsafe_key = self.key_storage.get_private_key_unsafe(account.address)
            if not unsafe_key:
                logger.error(f"Could not retrieve private key for {account_address_or_tag}")
                return False

            cow = CowSwap(
                private_key=unsafe_key,
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
        """Drain entire balance of an account to another account"""
        from_account = self.key_storage.get_account(from_address_or_tag)

        if not from_account:
            logger.error(f"From account '{from_address_or_tag}' not found in wallet.")
            return

        is_safe = isinstance(from_account, StoredSafeAccount)
        chain_interface = ChainInterfaces().get(chain_name)

        # ERC-20 tokens
        for token_name in chain_interface.chain.tokens.keys():
            balance_wei = self.get_erc20_balance_wei(from_address_or_tag, token_name, chain_name)
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
        native_balance_wei = self.get_native_balance_wei(from_account.address)
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
