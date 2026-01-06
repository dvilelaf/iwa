"""Wallet management"""

import base64
import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Union

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
from eth_account import Account
from eth_account.signers.local import LocalAccount
from pydantic import BaseModel, PrivateAttr

from iwa.core.constants import WALLET_PATH
from iwa.core.models import EthereumAddress, StoredAccount, StoredSafeAccount
from iwa.core.settings import settings
from iwa.core.utils import (
    configure_logger,
)

logger = configure_logger()


class EncryptedAccount(StoredAccount):
    """EncryptedAccount"""

    salt: str
    nonce: str
    ciphertext: str

    @staticmethod
    def derive_key(password: str, salt: bytes) -> bytes:
        """Derive key"""
        kdf = Scrypt(
            salt=salt,
            length=32,
            n=2**14,
            r=8,
            p=1,
        )
        return kdf.derive(password.encode())

    def decrypt_private_key(self, password: Optional[str] = None) -> str:
        """decrypt_private_key"""
        if not password and not settings.wallet_password:
            raise ValueError("Password must be provided or set in secrets.env (WALLET_PASSWORD)")
        if not password:
            password = settings.wallet_password.get_secret_value()
        salt_bytes = base64.b64decode(self.salt)
        nonce_bytes = base64.b64decode(self.nonce)
        ciphertext_bytes = base64.b64decode(self.ciphertext)
        key = EncryptedAccount.derive_key(password, salt_bytes)
        aesgcm = AESGCM(key)
        return aesgcm.decrypt(nonce_bytes, ciphertext_bytes, None).decode()

    @staticmethod
    def encrypt_private_key(
        private_key: str, password: str, tag: Optional[str] = None
    ) -> "EncryptedAccount":
        """Encrypt private key"""
        salt = os.urandom(16)
        key = EncryptedAccount.derive_key(password, salt)
        aesgcm = AESGCM(key)
        nonce = os.urandom(12)
        ciphertext = aesgcm.encrypt(nonce, private_key.encode(), None)

        acct = Account.from_key(private_key)
        return EncryptedAccount(
            address=acct.address,
            salt=base64.b64encode(salt).decode(),
            nonce=base64.b64encode(nonce).decode(),
            ciphertext=base64.b64encode(ciphertext).decode(),
            tag=tag,
        )


class KeyStorage(BaseModel):
    """KeyStorage"""

    accounts: Dict[EthereumAddress, Union[EncryptedAccount, StoredSafeAccount]] = {}
    _path: Path = PrivateAttr()  # not stored nor validated
    _password: str = PrivateAttr()

    def __init__(self, path: Path = Path(WALLET_PATH), password: Optional[str] = None):
        """Initialize key storage."""
        super().__init__()

        # PROTECTION: Prevent tests from accidentally using real wallet.json
        import sys

        is_test = "pytest" in sys.modules or "unittest" in sys.modules
        if is_test:
            real_wallet = Path(WALLET_PATH).resolve()
            given_path = Path(path).resolve()
            # Block if path points to the real wallet (even if mocked)
            if given_path == real_wallet or str(given_path).endswith("wallet.json"):
                # Check if we're in a temp directory (allowed)
                import tempfile

                temp_base = Path(tempfile.gettempdir()).resolve()
                if not str(given_path).startswith(str(temp_base)):
                    raise RuntimeError(
                        f"SECURITY: Tests cannot use real wallet path '{path}'. "
                        f"Use tmp_path fixture instead: KeyStorage(tmp_path / 'wallet.json')"
                    )

        self._path = path
        if password is None:
            password = settings.wallet_password.get_secret_value()
        self._password = password

        if os.path.exists(path):
            try:
                with open(path, "r") as f:
                    data = json.load(f)
                    self.accounts = {
                        k: EncryptedAccount(**v) if "signers" not in v else StoredSafeAccount(**v)
                        for k, v in data.get("accounts", {}).items()
                    }
            except json.JSONDecodeError:
                logger.error(f"Failed to load wallet from {path}: File is corrupted.")
                self.accounts = {}
        else:
            self.accounts = {}

        # Ensure 'master' account exists
        if not self.get_address_by_tag("master"):
            logger.info("Master account not found. Creating new 'master' account...")
            try:
                self.create_account("master")
            except Exception as e:
                logger.error(f"Failed to create master account: {e}")

    @property
    def master_account(self) -> EncryptedAccount:
        """Get the master account"""
        master_account = self.get_account("master")

        if not master_account:
            return list(self.accounts.values())[0]

        return master_account

    def save(self):
        """Save with automatic backup."""
        # Backup existing file before overwriting
        if self._path.exists():
            # Use backup directory relative to wallet path (supports tests with tmp_path)
            backup_dir = self._path.parent / "backup"
            backup_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = backup_dir / f"wallet.json.{timestamp}.bkp"
            shutil.copy2(self._path, backup_path)
            logger.debug(f"Backed up wallet to {backup_path}")

        # Ensure directory exists
        self._path.parent.mkdir(parents=True, exist_ok=True)

        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(self.model_dump(), f, indent=4)

        # Enforce read/write only for the owner
        os.chmod(self._path, 0o600)

    def create_account(self, tag: str) -> EncryptedAccount:
        """Create account"""
        tags = [acct.tag for acct in self.accounts.values()]
        if not tags:
            tag = "master"  # First account is always master
        if tag in tags:
            raise ValueError(f"Tag '{tag}' already exists in wallet.")

        acct = Account.create()

        encrypted = EncryptedAccount.encrypt_private_key(acct.key.hex(), self._password, tag)
        self.accounts[acct.address] = encrypted
        self.save()
        return encrypted

    def remove_account(self, address_or_tag: str):
        """Remove account"""
        account = self.find_stored_account(address_or_tag)
        if not account:
            return

        del self.accounts[account.address]
        self.save()

    def _get_private_key(self, address: str) -> Optional[str]:
        """Get private key (Internal)"""
        account = self.accounts.get(EthereumAddress(address))
        if not account:
            return None
        if isinstance(account, StoredSafeAccount):
            raise ValueError(f"Cannot get private key for Safe account {address}")

        return account.decrypt_private_key(self._password)

    # NOTE: get_private_key_unsafe() was removed for security reasons.
    # Use sign_transaction(), sign_message(), or get_signer() instead.

    def sign_message(self, message: bytes, signer_address_or_tag: str) -> bytes:
        """Sign a message internally without exposing the private key.

        Args:
            message: The message bytes to sign
            signer_address_or_tag: The address or tag of the signer

        Returns:
            The signature bytes

        """
        signer_account = self.find_stored_account(signer_address_or_tag)
        if not signer_account:
            raise ValueError(f"Signer account '{signer_address_or_tag}' not found.")

        if isinstance(signer_account, StoredSafeAccount):
            raise ValueError("Direct message signing not supported for Safe accounts.")

        private_key = self._get_private_key(signer_account.address)
        if not private_key:
            raise ValueError(f"Private key not found for {signer_address_or_tag}")

        from eth_account.messages import encode_defunct

        message_hash = encode_defunct(primitive=message)
        signed = Account.sign_message(message_hash, private_key=private_key)
        return signed.signature

    def sign_typed_data(self, typed_data: dict, signer_address_or_tag: str) -> bytes:
        """Sign EIP-712 typed data internally without exposing the private key.

        Args:
            typed_data: EIP-712 typed data dictionary
            signer_address_or_tag: The address or tag of the signer

        Returns:
            The signature bytes

        """
        signer_account = self.find_stored_account(signer_address_or_tag)
        if not signer_account:
            raise ValueError(f"Signer account '{signer_address_or_tag}' not found.")

        if isinstance(signer_account, StoredSafeAccount):
            raise ValueError("Direct message signing not supported for Safe accounts.")

        private_key = self._get_private_key(signer_account.address)
        if not private_key:
            raise ValueError(f"Private key not found for {signer_address_or_tag}")

        signed = Account.sign_typed_data(private_key=private_key, full_message=typed_data)
        return signed.signature

    def get_signer(self, address_or_tag: str) -> Optional[LocalAccount]:
        """Get a LocalAccount signer for the address or tag.

        ⚠️ SECURITY WARNING: This method returns a LocalAccount object which
        encapsulates the private key. The private key is accessible via the
        .key property on the returned object.

        USE CASES:
        - Only use this when an external library requires a signer object
          (e.g., CowSwap SDK, safe-eth-py for certain operations)

        DO NOT:
        - Log or serialize the returned LocalAccount object
        - Store the returned object longer than necessary
        - Pass the .key property to any external system

        ALTERNATIVES:
        - For signing transactions: use sign_transaction() instead
        - For message signing: use sign_message() or sign_typed_data()

        Args:
            address_or_tag: Address or tag of the account to get signer for.

        Returns:
            LocalAccount if found and is an EOA, None otherwise.
            Returns None for Safe accounts (they cannot sign directly).

        """
        account = self.find_stored_account(address_or_tag)
        if not account:
            return None

        # Safe accounts cannot be signers directly in this context (usually)
        if isinstance(account, StoredSafeAccount):
            return None

        private_key = self._get_private_key(account.address)
        if not private_key:
            return None

        return Account.from_key(private_key)

    def sign_transaction(self, transaction: dict, signer_address_or_tag: str):
        """Sign a transaction"""
        signer_account = self.find_stored_account(signer_address_or_tag)
        if not signer_account:
            raise ValueError(f"Signer account '{signer_address_or_tag}' not found.")

        if isinstance(signer_account, StoredSafeAccount):
            raise ValueError("Direct transaction signing not supported for Safe accounts.")

        private_key = self._get_private_key(signer_account.address)
        if not private_key:
            raise ValueError(f"Private key not found for {signer_address_or_tag}")

        signed = Account.sign_transaction(transaction, private_key)
        return signed

    # ... (create_safe omitted for brevity, but I should log there too if needed)

    def find_stored_account(
        self, address_or_tag: str
    ) -> Optional[Union[EncryptedAccount, StoredSafeAccount]]:
        """Find a stored account by address or tag."""
        # Try tag first
        for acc in self.accounts.values():
            if acc.tag == address_or_tag:
                return acc

        # Then try address
        try:
            addr = EthereumAddress(address_or_tag)
            return self.accounts.get(addr)
        except ValueError:
            return None

    def get_account(self, address_or_tag: str) -> Optional[Union[StoredAccount, StoredSafeAccount]]:
        """Get basic account info without exposing any possibility of private key access."""
        stored = self.find_stored_account(address_or_tag)
        if not stored:
            return None
        if isinstance(stored, StoredSafeAccount):
            return stored
        return StoredAccount(address=stored.address, tag=stored.tag)

    def get_account_info(
        self, address_or_tag: str
    ) -> Optional[Union[StoredAccount, StoredSafeAccount]]:
        """Alias for get_account for clarity when specifically requesting metadata."""
        return self.get_account(address_or_tag)

    def get_tag_by_address(self, address: EthereumAddress) -> Optional[str]:
        """Get tag by address"""
        account = self.accounts.get(EthereumAddress(address))
        if account:
            return account.tag
        return None

    def get_address_by_tag(self, tag: str) -> Optional[EthereumAddress]:
        """Get address by tag"""
        for account in self.accounts.values():
            if account.tag == tag:
                return EthereumAddress(account.address)
        return None
