from typing import Optional

from loguru import logger

from iwa.core.chain import ChainInterfaces, SupportedChain
from iwa.core.constants import NATIVE_CURRENCY_ADDRESS
from iwa.core.contracts.ERC20 import ERC20Contract
from iwa.core.keys import KeyStorage
from iwa.core.models import EthereumAddress, StoredSafeAccount
from iwa.core.tables import list_accounts
from iwa.protocols.gnosis.safe import SafeMultisig
from iwa.core.contracts.multisend import (
    MultiSendContract,
    MULTISEND_CALL_ONLY_ADDRESS_GNOSIS,
    MULTISEND_ADDRESS_GNOSIS,
    MultiSendCallOnlyContract,
)
from safe_eth.safe import SafeOperationEnum


class Wallet:
    """Wallet management"""

    def __init__(self):
        self.key_storage = KeyStorage()

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
                    token_name: self.get_erc20_balance(account_address, token_name)
                    if token_name != "native"
                    else chain_interface.get_native_balance(account_address)
                    for token_name in token_names
                }
                for account_address in self.key_storage.accounts.keys()
            }
            if token_names
            else None
        )

        list_accounts(self.key_storage.accounts, chain_interface, token_names, token_balances)

    def send(
        self,
        from_address_or_tag: str,
        to_address_or_tag: str,
        token_address_or_name: str,
        amount_eth: float,
        chain_name: str = "gnosis",
    ):
        """Send native currency or ERC20 tokens to an address"""
        from_account = self.key_storage.get_account(from_address_or_tag)
        to_account = self.key_storage.get_account(to_address_or_tag)

        if not from_account:
            logger.error(f"From account '{from_address_or_tag}' not found in wallet.")
            return

        if not to_account:
            logger.error(f"To account '{to_address_or_tag}' not found in wallet.")
            return

        chain_interface = ChainInterfaces().get(chain_name)
        amount_wei = chain_interface.web3.to_wei(amount_eth, "ether")

        token_address = self.get_token_address(token_address_or_name, chain_interface.chain)
        if not token_address:
            return

        is_safe = isinstance(from_account, StoredSafeAccount)

        if token_address == NATIVE_CURRENCY_ADDRESS:
            if is_safe:
                safe = SafeMultisig(from_account, chain_name)
                safe.send_tx(
                    to=to_account.address,
                    value=amount_wei,
                    signers_private_keys=self.key_storage.get_safe_signer_keys(from_address_or_tag),
                )

            else:
                chain_interface.send_native_transaction(
                    from_account,
                    to_account.address,
                    amount_wei,
                )
            return

        erc20 = ERC20Contract(token_address)
        transaction = erc20.prepare_transfer_tx(
            from_account.address,
            to_account.address,
            amount_wei,
        )
        if not transaction:
            return

        if is_safe:
            safe = SafeMultisig(from_account, chain_name)
            safe.send_tx(
                to=erc20.address,
                value=0,
                signers_private_keys=self.key_storage.get_safe_signer_keys(from_address_or_tag),
                data=transaction["data"],
            )
        else:
            chain_interface.sign_and_send_transaction(transaction, from_account.key)

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
            chain_interface.sign_and_send_transaction(transaction, from_account.key)

    def get_erc20_balance(
        self, account_address: str, token_address_or_name: str, chain_name: str = "gnosis"
    ) -> float:
        """Get ERC20 token balance"""
        chain = ChainInterfaces().get(chain_name)

        try:
            token_address = EthereumAddress(token_address_or_name)
        except ValueError:
            token_address = self.get_token_address(token_address_or_name, chain)
            if not token_address:
                logger.error(f"Token '{token_address_or_name}' not found on chain '{chain_name}'.")
                return None

        contract = ERC20Contract(chain_name=chain_name, address=token_address)
        return contract.balance_of_eth(account_address)

    def approve_erc20(
        self,
        owner_address_or_tag: str,
        spender_address_or_tag: str,
        token_address_or_name: str,
        amount: int,
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
        amount_wei = chain_interface.web3.to_wei(amount, "ether")

        token_address = self.get_token_address(token_address_or_name, chain_interface)
        if not token_address:
            return

        erc20 = ERC20Contract(token_address, chain_name)
        transaction = erc20.prepare_approve_tx(
            from_address=owner_account.address,
            spender=spender_address,
            amount_wei=amount_wei,
        )
        if not transaction:
            return

        is_safe = isinstance(owner_account, StoredSafeAccount)

        if is_safe:
            safe = SafeMultisig(owner_account, chain_name)
            safe.send_tx(
                to=erc20.address,
                value=0,
                signers_private_keys=self.key_storage.get_safe_signer_keys(owner_address_or_tag),
                data=transaction["data"],
            )
        else:
            chain_interface.sign_and_send_transaction(transaction, owner_account.key)

    def transfer_from_erc20(
        self,
        from_address_or_tag: str,
        sender_address_or_tag: str,
        recipient_address_or_tag: str,
        token_address_or_name: str,
        amount: int,
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
        amount_wei = chain_interface.web3.to_wei(amount, "ether")

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

        if is_safe:
            safe = SafeMultisig(from_account, chain_name)
            safe.send_tx(
                to=erc20.address,
                value=0,
                signers_private_keys=self.key_storage.get_safe_signer_keys(from_address_or_tag),
                data=transaction["data"],
            )
        else:
            chain_interface.sign_and_send_transaction(transaction, from_account.key)
