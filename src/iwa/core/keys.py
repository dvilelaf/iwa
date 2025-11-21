"""Wallet management"""

import base64
import json
import os
from pathlib import Path
from typing import Dict, List, Optional, Union

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
from eth_account import Account
from pydantic import BaseModel, PrivateAttr
from safe_eth.eth import EthereumClient
from safe_eth.safe import Safe

from iwa.core.constants import WALLET_PATH
from iwa.core.models import EthereumAddress, Secrets, StoredAccount, StoredSafeAccount
from iwa.core.utils import configure_logger, get_safe_master_copy_address

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
        password = password or Secrets().wallet_password.get_secret_value()
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
        self._path = path
        self._password = password or Secrets().wallet_password.get_secret_value()

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

    @property
    def master_account(self) -> EncryptedAccount:
        """Get the master account"""
        master_account = self.get_account("master")

        if not master_account:
            return list(self.accounts.values())[0]

        return master_account

    def save(self):
        """Save"""
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

    # ... (create_safe omitted for brevity, but I should log there too if needed)

    def get_account(self, address_or_tag) -> Optional[Union[Account, StoredSafeAccount]]:
        """Get account"""
        try:
            address = EthereumAddress(address_or_tag)
            account = self.accounts.get(address)

            if isinstance(account, StoredSafeAccount):
                return account

            if account is None:
                return None

            return Account.from_key(self.get_private_key(address))

        except ValueError:
            for account in self.accounts.values():
                if address_or_tag == account.tag:
                    if isinstance(account, StoredSafeAccount):
                        return account

                    return Account.from_key(self.get_private_key(account.address))
            return None

    def create_safe(
        self,
        deployer_tag_or_address: str,
        owner_tags_or_addresses: List[str],
        threshold: int,
        chain_name: str,
        tag: Optional[str] = None,
    ) -> StoredSafeAccount:
        """Add a Safe to the KeyStorage"""
        deployer_account = self.get_account(deployer_tag_or_address)
        if not deployer_account:
            raise ValueError(f"Deployer account '{deployer_tag_or_address}' not found in wallet.")

        owner_addresses = []
        for tag_or_address in owner_tags_or_addresses:
            owner_account = self.get_account(tag_or_address)
            if not owner_account:
                raise ValueError(f"Owner account '{tag_or_address}' not found in wallet.")
            owner_addresses.append(owner_account.address)

        rpc_secret = getattr(Secrets(), f"{chain_name}_rpc")

        create_tx = Safe.create(
            ethereum_client=EthereumClient(rpc_secret.get_secret_value()),
            deployer_account=deployer_account,
            master_copy_address=get_safe_master_copy_address("1.4.1"),
            owners=owner_addresses,
            threshold=threshold,
        )

        tx_hash = create_tx.tx_hash.hex()
        logger.info(
            f"Safe {tag} [{create_tx.contract_address}] deployed on {chain_name} on transaction: {tx_hash}"
        )

        safe_account = StoredSafeAccount(
            address=create_tx.contract_address,
            tag=tag,
            signers=owner_addresses,
            threshold=threshold,
            chains=[chain_name],
        )
        self.accounts[safe_account.address] = safe_account
        self.save()
        return safe_account

    def redeploy_safes(self):
        """Redeploy all safes to ensure they exist on all chains"""
        for account in self.accounts.copy().values():
            if not isinstance(account, StoredSafeAccount):
                continue

            for chain in account.chains:
                rpc_secret = getattr(Secrets(), f"{chain}_rpc")
                ethereum_client = EthereumClient(rpc_secret.get_secret_value())

                code = ethereum_client.w3.eth.get_code(account.address)

                if code and code != b"":
                    continue

                self.remove_account(account.address)

                self.create_safe(
                    deployer_tag_or_address="master",
                    owner_tags_or_addresses=account.signers,
                    threshold=account.threshold,
                    chain_name=chain,
                    tag=account.tag,
                )

    def remove_account(self, address: str) -> None:
        """Remove account"""
        if address not in self.accounts:
            return
        del self.accounts[address]

    def get_private_key(self, address: str) -> Optional[str]:
        """Get all pkeys"""
        if address not in self.accounts:
            return None

        account = self.accounts[address]

        if isinstance(account, StoredSafeAccount):
            raise ValueError("Cannot get private key for StoredSafeAccount.")

        return account.decrypt_private_key(self._password)

    def get_safe_signer_keys(self, safe_address_or_tag: str) -> List[str]:
        """Get all signer private keys for a safe"""
        safe_account = self.get_account(safe_address_or_tag)
        if not safe_account:
            raise ValueError(f"Safe account '{safe_address_or_tag}' not found in wallet.")

        signer_pkeys = []
        for signer_address in safe_account.signers:
            pkey = self.get_private_key(signer_address)
            if pkey:
                signer_pkeys.append(pkey)

        if len(signer_pkeys) < safe_account.threshold:
            raise ValueError(
                "Not enough signer private keys in wallet to meet the Safe's threshold."
            )

        return signer_pkeys



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
