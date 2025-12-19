"""Account service module."""

from typing import TYPE_CHECKING, Dict, Optional, Union

from loguru import logger

from iwa.core.chain import SupportedChain
from iwa.core.constants import NATIVE_CURRENCY_ADDRESS
from iwa.core.models import EthereumAddress, StoredSafeAccount

if TYPE_CHECKING:
    from iwa.core.keys import EncryptedAccount, KeyStorage


class AccountService:
    """Service for account resolution and management."""

    def __init__(self, key_storage: "KeyStorage"):
        """Initialize AccountService."""
        self.key_storage = key_storage

    @property
    def master_account(self) -> Optional[StoredSafeAccount]:
        """Get master account."""
        return self.key_storage.master_account

    def get_token_address(
        self, token_address_or_name: str, chain: SupportedChain
    ) -> Optional[EthereumAddress]:
        """Get token address from address or name."""
        if token_address_or_name == "native":
            return EthereumAddress(NATIVE_CURRENCY_ADDRESS)

        try:
            return EthereumAddress(token_address_or_name)
        except ValueError:
            token_address = chain.get_token_address(token_address_or_name)
            if not token_address:
                logger.error(f"Token '{token_address_or_name}' not found on chain '{chain.name}'.")
                return None
            return token_address

    def resolve_account(
        self, address_or_tag: str
    ) -> Optional[Union[StoredSafeAccount, "EncryptedAccount"]]:
        """Resolve account from address or tag."""
        return self.key_storage.get_account(address_or_tag)

    def get_tag_by_address(self, address: str) -> Optional[str]:
        """Get tag for a given address."""
        return self.key_storage.get_tag_by_address(address)

    def get_account_data(
        self,
    ) -> Dict[EthereumAddress, Union[StoredSafeAccount, "EncryptedAccount"]]:
        """Get all accounts data."""
        return self.key_storage.accounts
