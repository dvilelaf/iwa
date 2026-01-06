import base64
import json
from pathlib import Path
from unittest.mock import mock_open, patch

import pytest
from cryptography.exceptions import InvalidTag

from iwa.core.mnemonic import (
    WALLET_PATH,
    EncryptedMnemonic,
    MnemonicManager,
    MnemonicStorage,
)


@pytest.fixture
def mock_scrypt():
    with patch("iwa.core.mnemonic.Scrypt") as mock:
        mock.return_value.derive.return_value = b"derived_key"
        yield mock


@pytest.fixture
def mock_aesgcm():
    with patch("iwa.core.mnemonic.AESGCM") as mock:
        mock.return_value.encrypt.return_value = b"ciphertext"
        mock.return_value.decrypt.return_value = b"plaintext"
        yield mock


@pytest.fixture
def mock_bip39_generator():
    with patch("iwa.core.mnemonic.Bip39MnemonicGenerator") as mock:
        mock.return_value.FromWordsNumber.return_value.ToStr.return_value = "word1 word2 word3"
        yield mock


@pytest.fixture
def mock_bip39_seed_generator():
    with patch("iwa.core.mnemonic.Bip39SeedGenerator") as mock:
        mock.return_value.Generate.return_value = b"seed"
        yield mock


@pytest.fixture
def mock_bip44():
    with patch("iwa.core.mnemonic.Bip44") as mock:
        mock.FromSeed.return_value.Purpose.return_value.Coin.return_value.Account.return_value.Change.return_value.AddressIndex.return_value.PrivateKey.return_value.Raw.return_value.ToHex.return_value = "1234"
        yield mock


@pytest.fixture
def mock_console():
    with patch("iwa.core.mnemonic.Console") as mock:
        yield mock.return_value


def test_encrypted_mnemonic_derive_key(mock_scrypt):
    em = EncryptedMnemonic(kdf_salt="salt", nonce="nonce", ciphertext="ciphertext")
    key = em.derive_key(b"password")
    assert key == b"derived_key"
    mock_scrypt.assert_called_once()


def test_encrypted_mnemonic_decrypt_success(mock_scrypt, mock_aesgcm):
    em = EncryptedMnemonic(
        kdf_salt=base64.b64encode(b"salt").decode(),
        nonce=base64.b64encode(b"nonce").decode(),
        ciphertext=base64.b64encode(b"ciphertext").decode(),
    )
    plaintext = em.decrypt("password")
    assert plaintext == "plaintext"


def test_encrypted_mnemonic_decrypt_unsupported_kdf():
    em = EncryptedMnemonic(
        kdf="unsupported", kdf_salt="salt", nonce="nonce", ciphertext="ciphertext"
    )
    with pytest.raises(ValueError, match="Unsupported kdf"):
        em.decrypt("password")


def test_encrypted_mnemonic_decrypt_unsupported_cipher():
    em = EncryptedMnemonic(
        cypher="unsupported", kdf_salt="salt", nonce="nonce", ciphertext="ciphertext"
    )
    with pytest.raises(ValueError, match="Unsupported cipher"):
        em.decrypt("password")


def test_encrypted_mnemonic_encrypt(mock_scrypt, mock_aesgcm):
    with patch("os.urandom", return_value=b"random"):
        data = EncryptedMnemonic.encrypt("mnemonic", "password")
        assert data["kdf"] == "scrypt"
        assert data["cipher"] == "aesgcm"
        assert data["ciphertext"] == base64.b64encode(b"ciphertext").decode()


def test_mnemonic_storage_load():
    data = {
        "encrypted_mnemonic": {"kdf_salt": "salt", "nonce": "nonce", "ciphertext": "ciphertext"},
        "accounts": {},
    }
    with patch("builtins.open", mock_open(read_data=json.dumps(data))):
        storage = MnemonicStorage.load(Path("test.json"))
        assert isinstance(storage.encrypted_mnemonic, EncryptedMnemonic)


def test_mnemonic_storage_save():
    storage = MnemonicStorage(
        encrypted_mnemonic=EncryptedMnemonic(
            kdf_salt="salt", nonce="nonce", ciphertext="ciphertext"
        )
    )
    with patch("builtins.open", mock_open()) as mock_file, patch("os.chmod") as mock_chmod:
        storage.save(Path("test.json"))
        mock_file.assert_called_once()
        mock_chmod.assert_called_once()


def test_mnemonic_manager_init():
    mgr = MnemonicManager()
    assert mgr.mnemonic_file == WALLET_PATH


def test_mnemonic_manager_derive_key(mock_scrypt):
    mgr = MnemonicManager()
    key = mgr.derive_key(b"password", b"salt")
    assert key == b"derived_key"


def test_mnemonic_manager_encrypt_mnemonic(mock_scrypt, mock_aesgcm):
    mgr = MnemonicManager()
    with patch("os.urandom", return_value=b"random"):
        data = mgr.encrypt_mnemonic("mnemonic", "password")
        assert data["kdf"] == "scrypt"
        assert data["cipher"] == "aesgcm"


def test_mnemonic_manager_decrypt_mnemonic_success(mock_scrypt, mock_aesgcm):
    mgr = MnemonicManager()
    encobj = {
        "kdf": "scrypt",
        "kdf_salt": base64.b64encode(b"salt").decode(),
        "nonce": base64.b64encode(b"nonce").decode(),
        "ciphertext": base64.b64encode(b"ciphertext").decode(),
        "cipher": "aesgcm",
    }
    plaintext = mgr.decrypt_mnemonic(encobj, "password")
    assert plaintext == "plaintext"


def test_mnemonic_manager_decrypt_mnemonic_unsupported_kdf():
    mgr = MnemonicManager()
    encobj = {"kdf": "unsupported"}
    with pytest.raises(ValueError, match="Unsupported kdf"):
        mgr.decrypt_mnemonic(encobj, "password")


def test_mnemonic_manager_decrypt_mnemonic_unsupported_cipher():
    mgr = MnemonicManager()
    encobj = {"kdf": "scrypt", "cipher": "unsupported"}
    with pytest.raises(ValueError, match="Unsupported cipher"):
        mgr.decrypt_mnemonic(encobj, "password")


def test_mnemonic_manager_generate_and_store_mnemonic(
    mock_bip39_generator, mock_scrypt, mock_aesgcm
):
    mgr = MnemonicManager()
    with patch("builtins.open", mock_open()) as mock_file, patch("os.chmod") as mock_chmod:
        mnemonic = mgr.generate_and_store_mnemonic("password", "test.json")
        mock_file.assert_called_once()
        mock_chmod.assert_called_once()
        assert mnemonic == "word1 word2 word3"


def test_mnemonic_manager_load_and_decrypt_mnemonic_invalid_tag(mock_scrypt, mock_aesgcm):
    mgr = MnemonicManager()
    mock_aesgcm.return_value.decrypt.side_effect = InvalidTag()
    encobj = {
        "kdf": "scrypt",
        "kdf_salt": base64.b64encode(b"salt").decode(),
        "nonce": base64.b64encode(b"nonce").decode(),
        "ciphertext": base64.b64encode(b"ciphertext").decode(),
        "cipher": "aesgcm",
    }
    with patch("builtins.open", mock_open(read_data=json.dumps(encobj))):
        with pytest.raises(ValueError, match="Incorrect password"):
            mgr.load_and_decrypt_mnemonic("password", "test.json")


def test_mnemonic_manager_derive_eth_accounts_from_mnemonic(
    mock_scrypt, mock_aesgcm, mock_bip39_seed_generator, mock_bip44
):
    mgr = MnemonicManager()
    # Mock load_and_decrypt_mnemonic to return a mnemonic
    with (
        patch.object(mgr, "load_and_decrypt_mnemonic", return_value="mnemonic"),
        patch("iwa.core.mnemonic.Account") as mock_account,
    ):
        mock_account.from_key.return_value.address = "0xAddress"

        accounts = mgr.derive_eth_accounts_from_mnemonic("password", n_accounts=1)
        assert len(accounts) == 1
        assert accounts[0]["address"] == "0xAddress"
        assert accounts[0]["private_key_hex"] == "1234"


def test_mnemonic_manager_derive_eth_accounts_from_mnemonic_none(mock_scrypt, mock_aesgcm):
    mgr = MnemonicManager()
    with (
        patch.object(mgr, "load_and_decrypt_mnemonic", return_value=None),
    ):
        accounts = mgr.derive_eth_accounts_from_mnemonic("password")
        assert accounts is None
