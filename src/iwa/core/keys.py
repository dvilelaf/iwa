"""Wallet management"""

import base64
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, Union

from bip_utils import (
    Bip39MnemonicGenerator,
    Bip39SeedGenerator,
    Bip39WordsNum,
    Bip44,
    Bip44Changes,
    Bip44Coins,
)
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
from eth_account import Account
from eth_account.signers.local import LocalAccount
from pydantic import BaseModel, PrivateAttr, model_validator

from iwa.core.constants import WALLET_PATH
from iwa.core.models import EncryptedData, EthereumAddress, StoredAccount, StoredSafeAccount
from iwa.core.secrets import secrets
from iwa.core.utils import (
    configure_logger,
)

logger = configure_logger()

# Mnemonic constants
MNEMONIC_WORD_NUMBER = Bip39WordsNum.WORDS_NUM_24
SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_LEN = 32
AES_NONCE_LEN = 12
SALT_LEN = 16


class EncryptedAccount(StoredAccount, EncryptedData):
    """EncryptedAccount"""

    # We do NOT define 'salt' here to avoid serialization duplication.
    # Legacy 'salt' is handled in the validator.

    @model_validator(mode="before")
    @classmethod
    def upgrade_legacy_format(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        """Upgrade legacy account format to new EncryptedData structure."""
        if isinstance(data, dict):
            # Check if this is a legacy format (has 'salt')
            if "salt" in data:
                # Map to kdf_salt if missing
                if "kdf_salt" not in data:
                    data["kdf_salt"] = data["salt"]

                # Remove 'salt' to avoid "extra fields" error and duplication
                data.pop("salt")

                # Default KDF params for legacy accounts were:
                # n=2**14 (16384), r=8, p=1, len=32
                data.setdefault("kdf_n", SCRYPT_N)
                data.setdefault("kdf_r", SCRYPT_R)
                data.setdefault("kdf_p", SCRYPT_P)
                data.setdefault("kdf_len", SCRYPT_LEN)
                data.setdefault("kdf", "scrypt")
                data.setdefault("cipher", "aesgcm")
        return data

    @staticmethod
    def derive_key(
        password: str,
        salt: bytes,
        n: int = SCRYPT_N,
        r: int = SCRYPT_R,
        p: int = SCRYPT_P,
        length: int = SCRYPT_LEN,
    ) -> bytes:
        """Derive key"""
        kdf = Scrypt(
            salt=salt,
            length=length,
            n=n,
            r=r,
            p=p,
        )
        return kdf.derive(password.encode())

    def decrypt_private_key(self, password: Optional[str] = None) -> str:
        """decrypt_private_key"""
        if not password and not secrets.wallet_password:
            raise ValueError("Password must be provided or set in secrets.env (WALLET_PASSWORD)")
        if not password:
            password = secrets.wallet_password.get_secret_value()

        # Use kdf_salt (populated by upgrade_legacy_format if needed)
        salt_bytes = base64.b64decode(self.kdf_salt)
        nonce_bytes = base64.b64decode(self.nonce)
        ciphertext_bytes = base64.b64decode(self.ciphertext)

        key = EncryptedAccount.derive_key(
            password,
            salt_bytes,
            n=self.kdf_n,
            r=self.kdf_r,
            p=self.kdf_p,
            length=self.kdf_len,
        )
        aesgcm = AESGCM(key)
        return aesgcm.decrypt(nonce_bytes, ciphertext_bytes, None).decode()

    @staticmethod
    def encrypt_private_key(
        private_key: str, password: str, tag: Optional[str] = None
    ) -> "EncryptedAccount":
        """Encrypt private key"""
        # Generate new random salt
        salt = os.urandom(SALT_LEN)

        # Use standard constants for new encryptions
        kdf_n = SCRYPT_N
        kdf_r = SCRYPT_R
        kdf_p = SCRYPT_P
        kdf_len = SCRYPT_LEN

        key = EncryptedAccount.derive_key(password, salt, n=kdf_n, r=kdf_r, p=kdf_p, length=kdf_len)
        aesgcm = AESGCM(key)
        nonce = os.urandom(AES_NONCE_LEN)
        ciphertext = aesgcm.encrypt(nonce, private_key.encode(), None)

        acct = Account.from_key(private_key)

        return EncryptedAccount(
            address=acct.address,
            tag=tag or "",
            # EncryptedData fields
            kdf="scrypt",
            kdf_salt=base64.b64encode(salt).decode("utf-8"),
            kdf_n=kdf_n,
            kdf_r=kdf_r,
            kdf_p=kdf_p,
            kdf_len=kdf_len,
            cipher="aesgcm",
            nonce=base64.b64encode(nonce).decode("utf-8"),
            ciphertext=base64.b64encode(ciphertext).decode("utf-8"),
            # NO redundant 'salt' field
        )


class KeyStorage(BaseModel):
    """KeyStorage"""

    accounts: Dict[EthereumAddress, Union[EncryptedAccount, StoredSafeAccount]] = {}
    encrypted_mnemonic: Optional[dict] = None  # Encrypted BIP-39 mnemonic for master
    _path: Path = PrivateAttr()  # not stored nor validated
    _password: str = PrivateAttr()
    _pending_mnemonic: Optional[str] = PrivateAttr(default=None)  # Temp storage for display

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
            password = secrets.wallet_password.get_secret_value()
        self._password = password

        if os.path.exists(path):
            try:
                with open(path, "r") as f:
                    data = json.load(f)
                    self.accounts = {
                        EthereumAddress(k): EncryptedAccount(**v)
                        if "signers" not in v
                        else StoredSafeAccount(**v)
                        for k, v in data.get("accounts", {}).items()
                    }
                    self.encrypted_mnemonic = data.get("encrypted_mnemonic")
            except json.JSONDecodeError:
                logger.error(f"Failed to load wallet from {path}: File is corrupted.")
                self.accounts = {}
        else:
            self.accounts = {}

        # Ensure 'master' account exists
        if not self.get_address_by_tag("master"):
            logger.info("Master account not found. Creating new 'master' account...")
            try:
                self.generate_new_account("master")
            except Exception as e:
                logger.error(f"Failed to create master account: {e}")

    @property
    def master_account(self) -> Optional[Union[EncryptedAccount, StoredSafeAccount]]:
        """Get the master account"""
        master_account = self.find_stored_account("master")

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
            try:
                os.chmod(backup_dir, 0o700)
            except OSError as e:
                logger.debug(f"Could not chmod backup dir (expected in some Docker setups): {e}")
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = backup_dir / f"wallet.json.{timestamp}.bkp"
            shutil.copy2(self._path, backup_path)
            try:
                os.chmod(backup_path, 0o600)
            except OSError as e:
                logger.debug(f"Could not chmod backup file: {e}")
            logger.debug(f"Backed up wallet to {backup_path}")

        # Ensure directory exists
        self._path.parent.mkdir(parents=True, exist_ok=True)

        with open(self._path, "w", encoding="utf-8") as f:
            # Use mode='json' to ensure all types (EthereumAddress) are correctly serialized
            json.dump(self.model_dump(mode="json"), f, indent=4)
            f.flush()
            os.fsync(f.fileno())  # Force write to disk (critical for Docker volumes)

        try:
            os.chmod(self._path, 0o600)
        except OSError as e:
            logger.debug(f"Could not chmod wallet file: {e}")

        logger.info(f"[KeyStorage] Wallet saved to {self._path} ({len(self.accounts)} accounts)")

    @staticmethod
    def _encrypt_mnemonic(mnemonic: str, password: str) -> dict:
        """Encrypt a mnemonic with AES-GCM using a scrypt-derived key."""
        password_b = password.encode("utf-8")
        salt = os.urandom(SALT_LEN)
        kdf = Scrypt(salt=salt, length=SCRYPT_LEN, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P)
        key = kdf.derive(password_b)
        aesgcm = AESGCM(key)
        nonce = os.urandom(AES_NONCE_LEN)
        ct = aesgcm.encrypt(nonce, mnemonic.encode("utf-8"), None)
        return {
            "kdf": "scrypt",
            "kdf_salt": base64.b64encode(salt).decode(),
            "kdf_n": SCRYPT_N,
            "kdf_r": SCRYPT_R,
            "kdf_p": SCRYPT_P,
            "kdf_len": SCRYPT_LEN,
            "cipher": "aesgcm",
            "nonce": base64.b64encode(nonce).decode(),
            "ciphertext": base64.b64encode(ct).decode(),
        }

    @staticmethod
    def _decrypt_mnemonic(encobj: dict, password: str) -> str:
        """Decrypt a mnemonic previously created by `_encrypt_mnemonic`."""
        if encobj.get("kdf") != "scrypt":
            raise ValueError(f"Unsupported kdf: {encobj.get('kdf')}")
        if encobj.get("cipher") != "aesgcm":
            raise ValueError(f"Unsupported cipher: {encobj.get('cipher')}")

        salt = base64.b64decode(encobj["kdf_salt"])
        nonce = base64.b64decode(encobj["nonce"])
        ct = base64.b64decode(encobj["ciphertext"])

        n = encobj.get("kdf_n", SCRYPT_N)
        r = encobj.get("kdf_r", SCRYPT_R)
        p = encobj.get("kdf_p", SCRYPT_P)
        length = encobj.get("kdf_len", SCRYPT_LEN)

        kdf = Scrypt(salt=salt, length=length, n=n, r=r, p=p)
        key = kdf.derive(password.encode("utf-8"))
        aesgcm = AESGCM(key)
        pt = aesgcm.decrypt(nonce, ct, None)
        return pt.decode("utf-8")

    def decrypt_mnemonic(self) -> str:
        """Decrypt the stored mnemonic using the wallet password."""
        if not self.encrypted_mnemonic:
            raise ValueError("No encrypted mnemonic found in wallet.")
        return self._decrypt_mnemonic(self.encrypted_mnemonic, self._password)

    @staticmethod
    def _derive_private_key_from_mnemonic(mnemonic: str, index: int = 0) -> str:
        """Derive ETH private key from mnemonic using BIP-44 path."""
        seed_bytes = Bip39SeedGenerator(mnemonic).Generate()
        bip44_ctx = Bip44.FromSeed(seed_bytes, Bip44Coins.ETHEREUM)
        addr_ctx = (
            bip44_ctx.Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(index)
        )
        return addr_ctx.PrivateKey().Raw().ToHex()

    def _create_master_from_mnemonic(self) -> Tuple[EncryptedAccount, str]:
        """Create master account from a new BIP-39 mnemonic.

        Returns:
            Tuple of (EncryptedAccount, plaintext_mnemonic).
            The mnemonic should be shown to user ONCE and never stored in plaintext.

        """
        # Generate 24-word mnemonic
        mnemonic = Bip39MnemonicGenerator().FromWordsNumber(MNEMONIC_WORD_NUMBER)
        mnemonic_str = mnemonic.ToStr()

        # Derive first account (index 0)
        private_key_hex = self._derive_private_key_from_mnemonic(mnemonic_str, 0)

        # Encrypt mnemonic for storage
        self.encrypted_mnemonic = self._encrypt_mnemonic(mnemonic_str, self._password)

        # Encrypt private key and create account
        encrypted_acct = EncryptedAccount.encrypt_private_key(
            private_key_hex, self._password, "master"
        )
        self.register_account(encrypted_acct)
        return encrypted_acct, mnemonic_str

    def generate_new_account(self, tag: str) -> EncryptedAccount:
        """Generate a brand new EOA account and register it with the given tag."""
        # Note: register_account(tag) check is inside, but we handle 'master' logic here
        tags = [acct.tag for acct in self.accounts.values()]
        if not tags:
            tag = "master"  # First account is always master

        # Master account: derive from mnemonic
        if tag == "master":
            if "master" in tags:
                raise ValueError("Master account already exists in wallet.")
            encrypted_acct, mnemonic = self._create_master_from_mnemonic()
            self._pending_mnemonic = mnemonic  # Store temporarily for display
            return encrypted_acct

        # Non-master: random key as before
        acct = Account.create()
        encrypted = EncryptedAccount.encrypt_private_key(acct.key.hex(), self._password, tag)
        self.register_account(encrypted)
        return encrypted

    def register_account(self, account: Union[EncryptedAccount, StoredSafeAccount]):
        """Register an account (EOA or Safe) in the storage with strict tag uniqueness checks."""
        if not account.tag:
            # Allow untagged accounts (rare but possible)
            pass
        else:
            # Check for duplicate tags
            for existing in self.accounts.values():
                if existing.tag == account.tag and existing.address != account.address:
                    raise ValueError(
                        f"Tag '{account.tag}' is already used by address {existing.address}"
                    )

        self.accounts[account.address] = account
        logger.info(
            f"[KeyStorage] Registering account: tag='{account.tag}', address={account.address}"
        )
        self.save()

    def get_pending_mnemonic(self) -> Optional[str]:
        """Get and clear the pending mnemonic (for one-time display).

        Returns:
            The mnemonic string if available, None otherwise.
            Clears the pending mnemonic after returning.

        """
        mnemonic = self._pending_mnemonic
        self._pending_mnemonic = None
        return mnemonic

    def display_pending_mnemonic(self) -> bool:
        """Display the pending mnemonic to the user and wait for confirmation.

        Returns:
            True if a mnemonic was displayed, False otherwise.

        """
        # SECURITY: Do NOT print mnemonic if not in an interactive terminal (avoids Docker logs)
        if not sys.stdout.isatty():
            if self._pending_mnemonic:
                print("\n" + "!" * 60)
                print("⚠️  SECURITY WARNING: MASTER ACCOUNT CREATED FROM MNEMONIC")
                print("!" * 60)
                print("\nSince this is a non-interactive terminal (e.g. Docker background),")
                print("the mnemonic is NOT displayed here to prevent it from being")
                print("stored in log files.")
                print("\nTo view and backup your mnemonic, run:")
                print("  just mnemonic")
                print("!" * 60 + "\n")
            return False

        mnemonic = self.get_pending_mnemonic()
        if not mnemonic:
            return False

        print("\n" + "=" * 60)
        print("⚠️  NEW MASTER ACCOUNT CREATED - BACKUP YOUR MNEMONIC!")
        print("=" * 60)
        print("\nWrite down these 24 words and store them in a safe place.")
        print("This is the ONLY time they will be shown.\n")
        print("-" * 60)
        words = mnemonic.split()
        for i in range(0, 24, 4):
            print(
                f"  {i + 1:2}. {words[i]:12}  {i + 2:2}. {words[i + 1]:12}  "
                f"{i + 3:2}. {words[i + 2]:12}  {i + 4:2}. {words[i + 3]:12}"
            )
        print("-" * 60)
        print("\n⚠️  If you lose this mnemonic, you CANNOT recover your funds!")
        print("=" * 60)
        input("\nPress ENTER after you have saved your mnemonic...")
        print()
        return True

    def remove_account(self, address_or_tag: str):
        """Remove account"""
        account = self.find_stored_account(address_or_tag)
        if not account:
            return

        del self.accounts[account.address]
        self.save()

    def rename_account(self, address_or_tag: str, new_tag: str):
        """Rename an account's tag with uniqueness check."""
        account = self.find_stored_account(address_or_tag)
        if not account:
            raise ValueError(f"Account '{address_or_tag}' not found.")

        # Check if new tag is already used by a DIFFERENT account
        for existing in self.accounts.values():
            if existing.tag == new_tag and existing.address != account.address:
                raise ValueError(f"Tag '{new_tag}' is already used by address {existing.address}")

        old_tag = account.tag
        account.tag = new_tag
        logger.info(
            f"[KeyStorage] Renaming account: '{old_tag}' -> '{new_tag}' (address={account.address})"
        )
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
