"""Balance service module."""

import time
from typing import TYPE_CHECKING, Optional, Union

from loguru import logger
from web3.types import Wei

from iwa.core.chain import ChainInterfaces
from iwa.core.contracts.erc20 import ERC20Contract

if TYPE_CHECKING:
    from iwa.core.keys import KeyStorage
    from iwa.core.services_pkg.account import AccountService
    from iwa.core.wallet import Wallet


class BalanceService:
    """Service for fetching native and ERC20 balances."""

    def __init__(
        self,
        wallet_or_key_storage: Union["Wallet", "KeyStorage"],
        account_service: "AccountService",
    ):
        """Initialize BalanceService."""
        self.key_storage = (
            wallet_or_key_storage.key_storage
            if hasattr(wallet_or_key_storage, "key_storage")
            else wallet_or_key_storage
        )
        self.account_service = account_service

    def get_native_balance_eth(
        self, account_address_or_tag: str, chain_name: str = "gnosis"
    ) -> Optional[float]:
        """Get native currency balance in ETH."""
        account = self.account_service.resolve_account(account_address_or_tag)
        if not account:
            # If not found, try to use as raw address
            address = account_address_or_tag
        else:
            address = account.address

        chain_interface = ChainInterfaces().get(chain_name)
        return chain_interface.get_native_balance_eth(address)

    def get_native_balance_wei(
        self, account_address_or_tag: str, chain_name: str = "gnosis"
    ) -> Optional[Wei]:
        """Get native currency balance in WEI."""
        account = self.account_service.resolve_account(account_address_or_tag)
        if not account:
            # If not found, try to use as raw address
            address = account_address_or_tag
        else:
            address = account.address

        chain_interface = ChainInterfaces().get(chain_name)
        return chain_interface.get_native_balance_wei(address)

    def get_erc20_balance_eth(
        self, account_address_or_tag: str, token_address_or_name: str, chain_name: str = "gnosis"
    ) -> Optional[float]:
        """Get ERC20 token balance in ETH-like format."""
        chain = ChainInterfaces().get(chain_name)
        token_address = self.account_service.get_token_address(token_address_or_name, chain.chain)
        if not token_address:
            return None

        account = self.account_service.resolve_account(account_address_or_tag)
        if not account:
            return None

        contract = ERC20Contract(chain_name=chain_name, address=token_address)
        return contract.balance_of_eth(account.address)

    def get_erc20_balance_wei(
        self, account_address_or_tag: str, token_address_or_name: str, chain_name: str = "gnosis"
    ) -> Optional[Wei]:
        """Get ERC20 token balance in WEI."""
        chain = ChainInterfaces().get(chain_name)
        token_address = self.account_service.get_token_address(token_address_or_name, chain.chain)
        if not token_address:
            return None

        account = self.account_service.resolve_account(account_address_or_tag)
        if not account:
            return None

        contract = ERC20Contract(chain_name=chain_name, address=token_address)
        return contract.balance_of_wei(account.address)

    def get_erc20_balance_with_retry(
        self,
        account_address: str,
        token_address_or_name: str,
        chain_name: str = "gnosis",
        retries: int = 3,
    ) -> Optional[float]:
        """Fetch balance with retry logic."""
        for attempt in range(retries):
            try:
                return self.get_erc20_balance_eth(
                    account_address, token_address_or_name, chain_name
                )
            except Exception as e:
                if attempt == retries - 1:
                    logger.error(
                        f"Failed to fetch balance for {token_address_or_name} after {retries} attempts: {e}"
                    )
                time.sleep(1)
        return None
