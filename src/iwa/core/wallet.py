"""Wallet management"""

import os
import base64
import json
from typing import Dict, Optional, List
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from eth_account import Account
from pydantic import BaseModel, PrivateAttr
from iwa.core.models import EthereumAddress
from iwa.core.constants import WALLET_PATH
from iwa.core.models import Secrets
from pathlib import Path
from loguru import logger
from rich.console import Console
from rich.table import Table


class EncryptedAccount(BaseModel):
    """EncryptedAccount"""
    address: EthereumAddress
    salt: str
    nonce: str
    ciphertext: str
    tags: List[str] = []

    def decrypt_private_key(self, password: Optional[str] = None) -> str:
        """decrypt_private_key"""
        password = password or Secrets().wallet_password.get_secret_value()
        salt_bytes = base64.b64decode(self.salt)
        nonce_bytes = base64.b64decode(self.nonce)
        ciphertext_bytes = base64.b64decode(self.ciphertext)
        key = Wallet.derive_key(password, salt_bytes)
        aesgcm = AESGCM(key)
        return aesgcm.decrypt(nonce_bytes, ciphertext_bytes, None).decode()


class Wallet(BaseModel):
    """Wallet"""

    accounts: Dict[EthereumAddress, EncryptedAccount] = {}
    _path: Path = PrivateAttr()  # not stored nor validated
    _password: str = PrivateAttr()

    def __init__(self, path: Path = Path(WALLET_PATH), password: Optional[str] = None):
        super().__init__()
        self._path = path
        self._password = password or Secrets().wallet_password.get_secret_value()

        if os.path.exists(path):
            with open(path, "r") as f:
                data = json.load(f)
                self.accounts = {k: EncryptedAccount(**v) for k, v in data.get("accounts", {}).items()}

    @property
    def master_account(self) -> EncryptedAccount:
        """Get the master account, which is the first account in the wallet."""
        return list(self.accounts.values())[0]

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

    @staticmethod
    def encrypt_private_key(private_key: str, password: str) -> EncryptedAccount:
        """Encrypt private key"""
        salt = os.urandom(16)
        key = Wallet.derive_key(password, salt)
        aesgcm = AESGCM(key)
        nonce = os.urandom(12)
        ciphertext = aesgcm.encrypt(nonce, private_key.encode(), None)

        acct = Account.from_key(private_key)
        return EncryptedAccount(
            address=acct.address,
            salt=base64.b64encode(salt).decode(),
            nonce=base64.b64encode(nonce).decode(),
            ciphertext=base64.b64encode(ciphertext).decode()
        )

    @classmethod
    def load(cls, path: str) -> "Wallet":
        """Load"""
        if not os.path.exists(path):
            return cls(accounts={})
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return cls.model_validate(data)

    def save(self):
        """Save"""
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(self.model_dump(), f, indent=4)

    def create_new_account(self) -> EncryptedAccount:
        """Create new account"""
        acct = Account.create()
        encrypted = self.encrypt_private_key(acct.key.hex(), self._password)
        self.accounts[acct.address] = encrypted
        self.save()
        return encrypted

    def remove_account(self, address: str) -> None:
        """Remove account"""
        if address not in self.accounts:
            return
        del self.accounts[address]

    def get_private_key(self, address: str) -> Optional[str]:
        """Get all pkeys"""
        if address not in self.accounts:
            return None
        return self.accounts[address].decrypt_private_key(self._password)

    def get_account(self, address: str) -> Optional[Account]:
        """Get account"""
        if address not in self.accounts:
            return None
        return Account.from_key(self.get_private_key(address))

    def list_accounts(self) -> None:
        """List accounts"""
        console = Console()
        table = Table(
            title="Ejemplo de tabla con Rich",
            show_header=True,
        )
        table.add_column("Address", style="dim", width=42)
        table.add_column("Tags", style="dim", width=30)

        for acct in self.accounts.values():
            tags = ", ".join(acct.tags) if acct.tags else "-"
            table.add_row(acct.address, tags)

        console.print(table)
