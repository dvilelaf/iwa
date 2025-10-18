"""BIP-39 mnemonic generator, encrypt/decrypt, ETH account derivation and keystore saving."""

import base64
import getpass
import json
import os

from bip_utils import (
    Bip39MnemonicGenerator,
    Bip39SeedGenerator,
    Bip39WordsNum,
    Bip44,
    Bip44Changes,
    Bip44Coins,
)
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
from eth_account import Account
from pydantic import BaseModel
from rich import box
from rich.align import Align
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from iwa.core.constants import WALLET_PATH

MNEMONIC_WORD_NUMBER = Bip39WordsNum.WORDS_NUM_24
SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_LEN = 32
AES_NONCE_LEN = 12
SALT_LEN = 16


class EncryptedMnemonic(BaseModel):
    """EncryptedMnemonic"""

    kdf: str = "scrypt"
    kdf_salt: str
    kdf_n: int = SCRYPT_N
    kdf_r: int = SCRYPT_R
    kdf_p: int = SCRYPT_P
    kdf_len: int = SCRYPT_LEN
    cypher: str = "aesgcm"
    nonce: str
    ciphertext: str

    def derive_key(self, password: bytes) -> bytes:
        """Derive a key from a password and salt using scrypt."""
        kdf = Scrypt(
            salt=self.kdf_salt,
            length=self.kdf_len,
            n=self.kdf_n,
            r=self.kdf_r,
            p=self.kdf_p,
        )
        return kdf.derive(password)

    def decrypt(self, password: str) -> str:
        """Decrypt an object."""
        # validate expected algorithms
        if self.kdf != "scrypt":
            raise ValueError(f"Unsupported kdf: {self.kdf}")
        if self.cypher != "aesgcm":
            raise ValueError("Unsupported cipher, expected 'aesgcm'")

        salt = base64.b64decode(self.kdf.kdf_salt)
        nonce = base64.b64decode(self.nonce)
        ct = base64.b64decode(self.ciphertext)

        # derive key using the parameters from the file
        key = self.derive_key(
            password.encode("utf-8"),
            salt,
            n=self.kdf_n,
            r=self.kdf_r,
            p=self.kdf_p,
            length=self.kdf_len,
        )
        aesgcm = AESGCM(key)
        pt = aesgcm.decrypt(nonce, ct, None)
        return pt.decode("utf-8")

    @classmethod
    def encrypt(cls, mnemonic: str, password: str) -> dict:
        """Encrypt a mnemonic with AES-GCM using a scrypt-derived key."""
        password_b = password.encode("utf-8")
        salt = os.urandom(cls.salt_len)
        key = cls.derive_key(password_b, salt)
        aesgcm = AESGCM(key)
        nonce = os.urandom(cls.aes_nonce_len)
        ct = aesgcm.encrypt(nonce, mnemonic.encode("utf-8"), None)
        return {
            "kdf": "scrypt",
            "kdf_salt": base64.b64encode(salt).decode(),
            "kdf_n": cls.scrypt_n,
            "kdf_r": cls.scrypt_r,
            "kdf_p": cls.scrypt_p,
            "kdf_len": cls.scrypt_len,
            "cipher": "aesgcm",
            "nonce": base64.b64encode(nonce).decode(),
            "ciphertext": base64.b64encode(ct).decode(),
        }


class MnemonicStorage(BaseModel):
    """MnemonicStorage"""

    encrypted_mnemonic: EncryptedMnemonic
    accounts: Dict[EthereumAddress, StoredAccount] = {}

    @staticmethod
    def load(file_path: Path = WALLET_PATH) -> "MnemonicStorage":
        """Load"""
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        data["encrypted_mnemonic"] = EncryptedMnemonic(**data["encrypted_mnemonic"])
        data["accounts"] = {k: StoredAccount(**v) for k, v in data.get("accounts", {}).items()}
        return MnemonicStorage(**data)

    def save(self, file_path: Path = WALLET_PATH) -> None:
        """Save"""
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(self.model_dump(), f, indent=4)


class MnemonicManager:
    """Manager for BIP-39 mnemonics and keystore operations.

    Provides methods to generate mnemonics, encrypt/decrypt them using
    scrypt + AES-GCM, derive Ethereum accounts (BIP-44), and save
    keystores to disk.

    Attributes:
        mnemonic_file (str): Default file path for the encrypted mnemonic.
        mnemonic_word_number (Bip39WordsNum): Number of words in the mnemonic.
        scrypt_*: Parameters for the scrypt KDF.
        aes_nonce_len (int): Nonce length for AES-GCM.
        salt_len (int): Salt length for scrypt.

    """

    def __init__(
        self,
        mnemonic_file: str = WALLET_PATH,
        mnemonic_word_number: Bip39WordsNum = MNEMONIC_WORD_NUMBER,
        scrypt_n: int = SCRYPT_N,
        scrypt_r: int = SCRYPT_R,
        scrypt_p: int = SCRYPT_P,
        scrypt_len: int = SCRYPT_LEN,
        aes_nonce_len: int = AES_NONCE_LEN,
        salt_len: int = SALT_LEN,
    ):
        """Initialize MnemonicManager with configuration parameters."""
        self.mnemonic_file = mnemonic_file
        self.mnemonic_word_number = mnemonic_word_number
        self.scrypt_n = scrypt_n
        self.scrypt_r = scrypt_r
        self.scrypt_p = scrypt_p
        self.scrypt_len = scrypt_len
        self.aes_nonce_len = aes_nonce_len
        self.salt_len = salt_len

    def derive_key(
        self,
        password: bytes,
        salt: bytes,
        n: int | None = None,
        r: int | None = None,
        p: int | None = None,
        length: int | None = None,
    ) -> bytes:
        """Derive a key from a password and salt using scrypt.

        Args:
            password (bytes): The password in bytes.
            salt (bytes): A random salt.

        Returns:
            bytes: The derived key of length `self.scrypt_len`.

        """
        # use provided parameters or fall back to instance defaults
        n = n if n is not None else self.scrypt_n
        r = r if r is not None else self.scrypt_r
        p = p if p is not None else self.scrypt_p
        length = length if length is not None else self.scrypt_len

        kdf = Scrypt(
            salt=salt,
            length=length,
            n=n,
            r=r,
            p=p,
        )
        return kdf.derive(password)

    def encrypt_mnemonic(self, mnemonic: str, password: str) -> dict:
        """Encrypt a mnemonic with AES-GCM using a scrypt-derived key.

        Args:
            mnemonic (str): The mnemonic as plain text.
            password (str): Password used to derive the encryption key.

        Returns:
            dict: JSON-serializable object containing KDF params, nonce,
                  and ciphertext (all base64-encoded).

        """
        password_b = password.encode("utf-8")
        salt = os.urandom(self.salt_len)
        key = self.derive_key(password_b, salt)
        aesgcm = AESGCM(key)
        nonce = os.urandom(self.aes_nonce_len)
        ct = aesgcm.encrypt(nonce, mnemonic.encode("utf-8"), None)
        return {
            "kdf": "scrypt",
            "kdf_salt": base64.b64encode(salt).decode(),
            "kdf_n": self.scrypt_n,
            "kdf_r": self.scrypt_r,
            "kdf_p": self.scrypt_p,
            "kdf_len": self.scrypt_len,
            "cipher": "aesgcm",
            "nonce": base64.b64encode(nonce).decode(),
            "ciphertext": base64.b64encode(ct).decode(),
        }

    def decrypt_mnemonic(self, encobj: dict, password: str) -> str:
        """Decrypt an object previously created by `encrypt_mnemonic`.

        Args:
            encobj (dict): Object with KDF params, nonce and ciphertext
                           encoded in base64.
            password (str): Password to derive the decryption key.

        Returns:
            str: The mnemonic in plain text.

        """
        # validate expected algorithms
        kdf_name = encobj.get("kdf", "scrypt")
        if kdf_name != "scrypt":
            raise ValueError(f"Unsupported kdf: {kdf_name}")
        if encobj.get("cipher", "aesgcm") != "aesgcm":
            raise ValueError("Unsupported cipher, expected 'aesgcm'")

        salt = base64.b64decode(encobj["kdf_salt"])
        nonce = base64.b64decode(encobj["nonce"])
        ct = base64.b64decode(encobj["ciphertext"])

        # read kdf params from the encoded object, falling back to defaults
        n = int(encobj.get("kdf_n", self.scrypt_n))
        r = int(encobj.get("kdf_r", self.scrypt_r))
        p = int(encobj.get("kdf_p", self.scrypt_p))
        length = int(encobj.get("kdf_len", self.scrypt_len))

        # derive key using the parameters from the file
        key = self.derive_key(password.encode("utf-8"), salt, n=n, r=r, p=p, length=length)
        aesgcm = AESGCM(key)
        pt = aesgcm.decrypt(nonce, ct, None)
        return pt.decode("utf-8")

    def generate_and_store_mnemonic(
        self,
        password: str,
        out_file: str = None,
    ) -> None:
        """Generate a BIP-39 mnemonic, encrypt it and save to disk.

        Args:
            password (str): Password to encrypt the mnemonic.
            out_file (str): Destination file. Optional; if None this method
                            uses `self.mnemonic_file`.

        Returns:
            str: The plaintext mnemonic (returned so the user can back it
                 up securely).

        """
        out_file = out_file or self.mnemonic_file
        mnemonic = Bip39MnemonicGenerator().FromWordsNumber(self.mnemonic_word_number)
        mnemonic_str = mnemonic.ToStr()
        enc = self.encrypt_mnemonic(mnemonic_str, password)
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(enc, f, indent=2)
        os.chmod(out_file, 0o600)
        self.display_mnemonic(mnemonic_str)
        del mnemonic, enc, mnemonic_str  # clean up sensitive data

    def prompt_and_store_mnemonic(self, out_file: str = None, max_attempts: int = 3) -> None:
        """Prompt for a password twice, verify they match, and store mnemonic.

        This helper asks the user to enter a password twice and checks that
        both entries match. If they do, it generates, encrypts and stores
        the mnemonic using `generate_and_store_mnemonic`.

        Args:
            out_file (str): Optional destination file for the encrypted object.
            max_attempts (int): Number of attempts allowed for confirmation.

        Returns:
            str | None: The plaintext mnemonic if successful, otherwise None.

        """
        if os.path.exists(out_file or self.mnemonic_file):
            print(f"Mnemonic file '{out_file or self.mnemonic_file}' already exists.")
            return None

        for _ in range(max_attempts):
            p1 = getpass.getpass("Enter a strong password to encrypt the mnemonic: ").strip()
            if not p1:
                print("Empty password not allowed.")
                continue
            p2 = getpass.getpass("Confirm password: ").strip()
            if p1 != p2:
                print("Passwords do not match. Please try again.")
                continue
            # Passwords match — generate and store mnemonic
            self.generate_and_store_mnemonic(p1, out_file)
            return None
        raise ValueError("Maximum password attempts exceeded.")

    def display_mnemonic(
        self,
        mnemonic: str,
        columns: int = 6,
        rows: int = 4,
    ) -> None:
        """Format and print a mnemonic as a numbered table wrapped in a Panel.

        Args:
            mnemonic (str): The plaintext mnemonic (space separated words).
            columns (int): Number of columns per row (default 6).
            rows (int): Number of rows (default 4).

        """
        words = mnemonic.split()
        console = Console()
        # build table without internal borders; we'll wrap it in a Panel
        table = Table(
            show_header=False,
            box=None,
            show_lines=False,
            expand=False,
        )
        # add columns
        for _ in range(columns):
            table.add_column(justify="left")
        # warning: advise user to create a paper backup
        console.print(
            "[bold yellow]Warning:[/bold yellow] Make a paper backup of "
            "your mnemonic and store it in a safe place:"
        )
        # prepare numbered cells (colored green) with padded indices
        cells = []
        for i, w in enumerate(words):
            cells.append(f"[green]{i + 1:2d}. {w}[/green]")
        # add rows of `columns` columns
        for r in range(rows):
            start = r * columns
            row = cells[start : start + columns]
            # if row shorter than columns, pad with empty strings
            if len(row) < columns:
                row += [""] * (columns - len(row))
            table.add_row(*row)
        # wrap table in a panel to draw only the outer border
        panel = Panel(
            table,
            box=box.ROUNDED,
            border_style="bright_blue",
            padding=(0, 1),
            expand=False,
        )
        console.print(Align.center(panel))

    def load_and_decrypt_mnemonic(
        self,
        password: str,
        in_file: str = None,
    ) -> str:
        """Load and decrypt a mnemonic from a file.

        Args:
            password (str): Password to decrypt the mnemonic.
            in_file (str): File path with the encrypted object. Optional;
                           if None `self.mnemonic_file` is used.

        Returns:
            str: The plaintext mnemonic.

        """
        in_file = in_file or self.mnemonic_file
        with open(in_file, "r", encoding="utf-8") as f:
            enc = json.load(f)
        try:
            mnemonic = self.decrypt_mnemonic(enc, password)
            return mnemonic
        except InvalidTag:
            print("Incorrect password")
            return None

    def derive_eth_accounts_from_mnemonic(
        self,
        n_accounts: int = 5,
    ):
        """Derive Ethereum accounts (BIP-44) from a BIP-39 mnemonic.

        Args:
            mnemonic (str): The mnemonic as plain text.
            n_accounts (int): Number of accounts to derive.

        Returns:
            list: Dicts with keys 'index', 'address' and 'private_key_hex'.

        """
        mnemonic = self.load_and_decrypt_mnemonic(getpass.getpass("Enter password: "))

        if mnemonic is None:
            return None

        accounts = []
        for i in range(n_accounts):
            # obtain private key (hex) for this index using helper
            priv_hex = self.derive_private_key_hex_from_mnemonic(mnemonic, i)
            priv_bytes = bytes.fromhex(priv_hex)
            acct = Account.from_key(priv_bytes)
            accounts.append(
                {
                    "index": i,
                    "address": acct.address,
                    "private_key_hex": priv_hex,
                }
            )
            del priv_bytes, acct, priv_hex  # clean up sensitive data
        return accounts

    def derive_private_key_hex_from_mnemonic(
        self,
        mnemonic: str,
        index: int,
        account: int = 0,
        change: Bip44Changes = Bip44Changes.CHAIN_EXT,
    ) -> str:
        """Derive the private key (hex) for a given account index from a mnemonic.

        Args:
            mnemonic (str): The plaintext BIP-39 mnemonic.
            index (int): Address index to derive.
            account (int): BIP-44 account index (default 0).
            change (Bip44Changes): Change chain (external/internal).

        Returns:
            str: Private key as a hex string (no 0x prefix).

        """
        seed_bytes = Bip39SeedGenerator(mnemonic).Generate()
        bip44_mst = Bip44.FromSeed(seed_bytes, Bip44Coins.ETHEREUM)
        # Build the context step by step to avoid long lines
        ctx = bip44_mst.Purpose().Coin().Account(account)
        ctx = ctx.Change(change)
        addr_ctx = ctx.AddressIndex(index)
        return addr_ctx.PrivateKey().Raw().ToHex()


def main():
    """Demosntrate MnemonicManager usage."""
    mgr = MnemonicManager()

    # mgr.prompt_and_store_mnemonic()

    accounts = mgr.derive_eth_accounts_from_mnemonic()

    if accounts is None:
        return

    print(f"\nDerived {len(accounts)} accounts:")
    for a in accounts:
        print(f"  index {a['index']:>2} -> {a['address']}")


if __name__ == "__main__":
    main()
