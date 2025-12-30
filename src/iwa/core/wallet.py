"""Wallet module."""

from concurrent.futures import ThreadPoolExecutor
from typing import List, Optional, Tuple

from web3.types import Wei

from iwa.core.chain import SupportedChain
from iwa.core.db import init_db
from iwa.core.keys import KeyStorage
from iwa.core.models import EthereumAddress, StoredSafeAccount
from iwa.core.services import (
    AccountService,
    BalanceService,
    PluginService,
    SafeService,
    TransactionService,
    TransferService,
)
from iwa.core.utils import configure_logger
from iwa.plugins.gnosis.cow import OrderType

logger = configure_logger()


class Wallet:
    """Wallet management coordinator."""

    def __init__(self):
        """Initialize wallet."""
        self.key_storage = KeyStorage()
        self.account_service = AccountService(self.key_storage)
        self.balance_service = BalanceService(self.key_storage, self.account_service)
        self.safe_service = SafeService(self.key_storage, self.account_service)
        # self.transaction_manager = TransactionManager(self.key_storage, self.account_service)
        self.transaction_service = TransactionService(self.key_storage, self.account_service)

        self.transfer_service = TransferService(
            self.key_storage,
            self.account_service,
            self.balance_service,
            self.safe_service,
            self.transaction_service,
        )
        self.plugin_service = PluginService()

        init_db()

    @property
    def master_account(self) -> Optional[StoredSafeAccount]:
        """Get master account"""
        return self.account_service.master_account

    def get_token_address(
        self, token_address_or_name: str, chain: SupportedChain
    ) -> Optional[EthereumAddress]:
        """Get token address from address or name"""
        return self.account_service.get_token_address(token_address_or_name, chain)

    def get_accounts_balances(
        self, chain_name: str, token_names: Optional[list[str]] = None
    ) -> Tuple[dict, Optional[dict]]:
        """Get accounts data and balances."""
        accounts_data = self.account_service.get_account_data()
        token_names = token_names or []

        if not token_names:
            return accounts_data, None

        token_balances = {addr: {} for addr in accounts_data.keys()}

        def fetch_balance(addr, t_name):
            try:
                if t_name == "native":
                    return (
                        addr,
                        t_name,
                        self.balance_service.get_native_balance_eth(addr, chain_name),
                    )
                else:
                    return (
                        addr,
                        t_name,
                        self.balance_service.get_erc20_balance_eth(addr, t_name, chain_name),
                    )
            except Exception as e:
                logger.error(f"Error fetching {t_name} balance for {addr}: {e}")
                return addr, t_name, 0.0

        # Use ThreadPoolExecutor for parallel balance fetching
        with ThreadPoolExecutor(max_workers=20) as executor:
            tasks = []
            for addr in accounts_data.keys():
                for t_name in token_names:
                    tasks.append(executor.submit(fetch_balance, addr, t_name))

            for future in tasks:
                addr, t_name, bal = future.result()
                token_balances[addr][t_name] = bal

        return accounts_data, token_balances

    def send_native_transfer(
        self,
        from_address: str,
        to_address: str,
        value_wei: Wei,
        chain_name: str = "gnosis",
    ) -> Tuple[bool, Optional[str]]:
        """Send a native currency transfer (e.g., ETH, xDAI).

        Args:
            from_address: Sender's address or tag.
            to_address: Recipient's address or tag.
            value_wei: Amount to send in Wei.
            chain_name: Target blockchain name (default: "gnosis").

        Returns:
            Tuple containing:
                - bool: True if transaction was successfully sent (status=1).
                - Optional[str]: Transaction hash if successful, None otherwise.

        """
        tx_hash = self.transfer_service.send(
            from_address_or_tag=from_address,
            to_address_or_tag=to_address,
            amount_wei=value_wei,
            token_address_or_name="native",
            chain_name=chain_name,
        )
        return bool(tx_hash), tx_hash

    def sign_and_send_transaction(
        self,
        transaction: dict,
        signer_address_or_tag: str,
        chain_name: str = "gnosis",
        tags: Optional[List[str]] = None,
    ) -> Tuple[bool, dict]:
        """Sign and send a raw transaction dictionary.

        Args:
            transaction: Dictionary containing transaction parameters.
            signer_address_or_tag: Address or tag of the signing account.
            chain_name: Target blockchain name (default: "gnosis").
            tags: List of tags to associate with the transaction.

        Returns:
            Tuple containing:
                - bool: True if successful.
                - dict: Transaction receipt or error details.

        """
        return self.transaction_service.sign_and_send(
            transaction, signer_address_or_tag, chain_name, tags
        )

    def send_erc20_transfer(
        self,
        from_address: str,
        to_address: str,
        amount_wei: Wei,
        token_address: str,
        chain_name: str = "gnosis",
    ) -> Tuple[bool, Optional[str]]:
        """Send an ERC20 token transfer.

        Args:
            from_address: Sender's address or tag.
            to_address: Recipient's address or tag.
            amount_wei: Amount to send in Wei.
            token_address: Token address or name (e.g., "OLAS").
            chain_name: Target blockchain name (default: "gnosis").

        Returns:
            Tuple containing:
                - bool: True if transaction was successfully sent (status=1).
                - Optional[str]: Transaction hash if successful, None otherwise.

        """
        tx_hash = self.transfer_service.send(
            from_address_or_tag=from_address,
            to_address_or_tag=to_address,
            amount_wei=amount_wei,
            token_address_or_name=token_address,
            chain_name=chain_name,
        )
        return bool(tx_hash), tx_hash

    def send(
        self,
        from_address_or_tag: str,
        to_address_or_tag: str,
        amount_wei: Wei,
        token_address_or_name: str = "native",
        chain_name: str = "gnosis",
    ) -> Optional[str]:
        """Send native currency or ERC20 tokens.

        Unified interface for transferring assets.

        Args:
            from_address_or_tag: Sender's address or tag.
            to_address_or_tag: Recipient's address or tag.
            amount_wei: Amount to send in Wei.
            token_address_or_name: Token address, name, or "native".
            chain_name: Target blockchain name.

        Returns:
            Optional[str]: Transaction hash if successful, None otherwise.

        """
        return self.transfer_service.send(
            from_address_or_tag,
            to_address_or_tag,
            amount_wei,
            token_address_or_name,
            chain_name,
        )

    def multi_send(
        self,
        from_address_or_tag: str,
        transactions: list,
        chain_name: str = "gnosis",
    ):
        """Send multiple transactions in a single multisend transaction"""
        return self.transfer_service.multi_send(from_address_or_tag, transactions, chain_name)

    def get_native_balance_eth(
        self, account_address: str, chain_name: str = "gnosis"
    ) -> Optional[float]:
        """Get native currency balance"""
        return self.balance_service.get_native_balance_eth(account_address, chain_name)

    def get_native_balance_wei(
        self, account_address: str, chain_name: str = "gnosis"
    ) -> Optional[Wei]:
        """Get native currency balance"""
        return self.balance_service.get_native_balance_wei(account_address, chain_name)

    def get_erc20_balance_eth(
        self, account_address_or_tag: str, token_address_or_name: str, chain_name: str = "gnosis"
    ) -> Optional[float]:
        """Get ERC20 token balance"""
        return self.balance_service.get_erc20_balance_eth(
            account_address_or_tag, token_address_or_name, chain_name
        )

    def get_erc20_balance_wei(
        self, account_address_or_tag: str, token_address_or_name: str, chain_name: str = "gnosis"
    ) -> Optional[Wei]:
        """Get ERC20 token balance"""
        return self.balance_service.get_erc20_balance_wei(
            account_address_or_tag, token_address_or_name, chain_name
        )

    def get_erc20_allowance(
        self,
        owner_address_or_tag: str,
        spender_address: str,
        token_address_or_name: str,
        chain_name: str = "gnosis",
    ) -> Optional[float]:
        """Get ERC20 token allowance.

        Args:
            owner_address_or_tag: Token owner's address or tag.
            spender_address: Address authorized to spend tokens.
            token_address_or_name: Token address or name.
            chain_name: Target blockchain name.

        Returns:
            Optional[float]: Allowance amount in Ether (float) or None on error.

        """
        return self.transfer_service.get_erc20_allowance(
            owner_address_or_tag, spender_address, token_address_or_name, chain_name
        )

    def approve_erc20(
        self,
        owner_address_or_tag: str,
        spender_address_or_tag: str,
        token_address_or_name: str,
        amount_wei: Wei,
        chain_name: str = "gnosis",
    ) -> Optional[str]:
        """Approve ERC20 token allowance.

        Args:
            owner_address_or_tag: Token owner's address or tag.
            spender_address_or_tag: Spender's address or tag.
            token_address_or_name: Token address or name.
            amount_wei: Amount to approve in Wei.
            chain_name: Target blockchain name.

        Returns:
            Optional[str]: Transaction hash if successful, None otherwise.

        """
        return self.transfer_service.approve_erc20(
            owner_address_or_tag,
            spender_address_or_tag,
            token_address_or_name,
            amount_wei,
            chain_name,
        )

    def transfer_from_erc20(
        self,
        from_address_or_tag: str,
        sender_address_or_tag: str,
        recipient_address_or_tag: str,
        token_address_or_name: str,
        amount_wei: Wei,
        chain_name: str = "gnosis",
    ):
        """TransferFrom ERC20 tokens"""
        return self.transfer_service.transfer_from_erc20(
            from_address_or_tag,
            sender_address_or_tag,
            recipient_address_or_tag,
            token_address_or_name,
            amount_wei,
            chain_name,
        )

    async def swap(
        self,
        account_address_or_tag: str,
        amount_eth: Optional[float],
        sell_token_name: str,
        buy_token_name: str,
        chain_name: str = "gnosis",
        order_type: OrderType = OrderType.SELL,
    ) -> bool:
        """Swap ERC-20 tokens on CowSwap.

        Args:
            account_address_or_tag: Account address or tag initiating the swap.
            amount_eth: Amount to swap (sell or buy amount depending on order_type).
            sell_token_name: Name of the token to sell.
            buy_token_name: Name of the token to buy.
            chain_name: Blockchain name (must supports CowSwap, e.g., "gnosis").
            order_type: OrderType.SELL or OrderType.BUY.

        Returns:
            bool: True if swap order was created and filled successfully.

        """
        return await self.transfer_service.swap(
            account_address_or_tag,
            amount_eth,
            sell_token_name,
            buy_token_name,
            chain_name,
            order_type,
        )

    def drain(
        self,
        from_address_or_tag: str,
        to_address_or_tag: str = "master",
        chain_name: str = "gnosis",
    ) -> Optional[str]:
        """Drain entire balance of an account to another account.

        Transfers all native currency and known ERC20 tokens.

        Args:
            from_address_or_tag: Source account address or tag.
            to_address_or_tag: Destination account address or tag (default: "master").
            chain_name: Target blockchain name.

        Returns:
            Optional[str]: Summary of the operation or transaction hash of the last transfer.

        """
        return self.transfer_service.drain(from_address_or_tag, to_address_or_tag, chain_name)
