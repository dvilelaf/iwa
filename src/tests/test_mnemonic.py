import pytest
from unittest.mock import MagicMock, patch, mock_open
import base64
import json
from pathlib import Path
from cryptography.exceptions import InvalidTag
from iwa.core.mnemonic import (
    EncryptedMnemonic,
    MnemonicStorage,
    MnemonicManager,
    main,
    WALLET_PATH,
    MNEMONIC_WORD_NUMBER,
    SCRYPT_N,
    SCRYPT_R,
    SCRYPT_P,
    SCRYPT_LEN,
    AES_NONCE_LEN,
    SALT_LEN,
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
    em = EncryptedMnemonic(
        kdf_salt="salt",
        nonce="nonce",
        ciphertext="ciphertext"
    )
    key = em.derive_key(b"password")
    assert key == b"derived_key"
    mock_scrypt.assert_called_once()

def test_encrypted_mnemonic_decrypt_success(mock_scrypt, mock_aesgcm):
    em = EncryptedMnemonic(
        kdf_salt=base64.b64encode(b"salt").decode(),
        nonce=base64.b64encode(b"nonce").decode(),
        ciphertext=base64.b64encode(b"ciphertext").decode()
    )
    plaintext = em.decrypt("password")
    assert plaintext == "plaintext"

def test_encrypted_mnemonic_decrypt_unsupported_kdf():
    em = EncryptedMnemonic(
        kdf="unsupported",
        kdf_salt="salt",
        nonce="nonce",
        ciphertext="ciphertext"
    )
    with pytest.raises(ValueError, match="Unsupported kdf"):
        em.decrypt("password")

def test_encrypted_mnemonic_decrypt_unsupported_cipher():
    em = EncryptedMnemonic(
        cypher="unsupported",
        kdf_salt="salt",
        nonce="nonce",
        ciphertext="ciphertext"
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
        "encrypted_mnemonic": {
            "kdf_salt": "salt",
            "nonce": "nonce",
            "ciphertext": "ciphertext"
        },
        "accounts": {}
    }
    with patch("builtins.open", mock_open(read_data=json.dumps(data))):
        storage = MnemonicStorage.load(Path("test.json"))
        assert isinstance(storage.encrypted_mnemonic, EncryptedMnemonic)

def test_mnemonic_storage_save():
    storage = MnemonicStorage(
        encrypted_mnemonic=EncryptedMnemonic(
            kdf_salt="salt",
            nonce="nonce",
            ciphertext="ciphertext"
        )
    )
    with patch("builtins.open", mock_open()) as mock_file:
        storage.save(Path("test.json"))
        mock_file.assert_called_once()

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
        "cipher": "aesgcm"
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

def test_mnemonic_manager_generate_and_store_mnemonic(mock_bip39_generator, mock_scrypt, mock_aesgcm, mock_console):
    mgr = MnemonicManager()
    with patch("builtins.open", mock_open()) as mock_file, \
         patch("os.chmod") as mock_chmod:
        mgr.generate_and_store_mnemonic("password", "test.json")
        mock_file.assert_called_once()
        mock_chmod.assert_called_once()
        mock_console.print.assert_called()

def test_mnemonic_manager_prompt_and_store_mnemonic_file_exists(mock_console):
    mgr = MnemonicManager()
    with patch("os.path.exists", return_value=True):
        mgr.prompt_and_store_mnemonic("test.json")
        # Should print warning and return None
        # We can't easily check print with built-in print, but we can check it didn't ask for password
        with patch("getpass.getpass") as mock_getpass:
            mgr.prompt_and_store_mnemonic("test.json")
            mock_getpass.assert_not_called()

def test_mnemonic_manager_prompt_and_store_mnemonic_success(mock_bip39_generator, mock_scrypt, mock_aesgcm, mock_console):
    mgr = MnemonicManager()
    with patch("os.path.exists", return_value=False), \
         patch("getpass.getpass", side_effect=["password", "password"]), \
         patch("builtins.open", mock_open()), \
         patch("os.chmod"):
        mgr.prompt_and_store_mnemonic("test.json")
        # Should succeed

def test_mnemonic_manager_prompt_and_store_mnemonic_mismatch(mock_console):
    mgr = MnemonicManager()
    with patch("os.path.exists", return_value=False), \
         patch("getpass.getpass", side_effect=["p1", "p2", "p1", "p2", "p1", "p2"]):
        with pytest.raises(ValueError, match="Maximum password attempts exceeded"):
            mgr.prompt_and_store_mnemonic("test.json")

def test_mnemonic_manager_prompt_and_store_mnemonic_empty(mock_console):
    mgr = MnemonicManager()
    with patch("os.path.exists", return_value=False), \
         patch("getpass.getpass", side_effect=["", "", "", "", "", ""]):
        with pytest.raises(ValueError, match="Maximum password attempts exceeded"):
            mgr.prompt_and_store_mnemonic("test.json")

def test_mnemonic_manager_display_mnemonic(mock_console):
    mgr = MnemonicManager()
    mgr.display_mnemonic("word1 word2 word3")
    mock_console.print.assert_called()

def test_mnemonic_manager_load_and_decrypt_mnemonic_success(mock_scrypt, mock_aesgcm):
    mgr = MnemonicManager()
    encobj = {
        "kdf": "scrypt",
        "kdf_salt": base64.b64encode(b"salt").decode(),
        "nonce": base64.b64encode(b"nonce").decode(),
        "ciphertext": base64.b64encode(b"ciphertext").decode(),
        "cipher": "aesgcm"
    }
    with patch("builtins.open", mock_open(read_data=json.dumps(encobj))):
        mnemonic = mgr.load_and_decrypt_mnemonic("password", "test.json")
        assert mnemonic == "plaintext"

def test_mnemonic_manager_load_and_decrypt_mnemonic_invalid_tag(mock_scrypt, mock_aesgcm):
    mgr = MnemonicManager()
    mock_aesgcm.return_value.decrypt.side_effect = InvalidTag()
    encobj = {
        "kdf": "scrypt",
        "kdf_salt": base64.b64encode(b"salt").decode(),
        "nonce": base64.b64encode(b"nonce").decode(),
        "ciphertext": base64.b64encode(b"ciphertext").decode(),
        "cipher": "aesgcm"
    }
    with patch("builtins.open", mock_open(read_data=json.dumps(encobj))):
        mnemonic = mgr.load_and_decrypt_mnemonic("password", "test.json")
        assert mnemonic is None

def test_mnemonic_manager_derive_eth_accounts_from_mnemonic(mock_scrypt, mock_aesgcm, mock_bip39_seed_generator, mock_bip44):
    mgr = MnemonicManager()
    # Mock load_and_decrypt_mnemonic to return a mnemonic
    with patch.object(mgr, "load_and_decrypt_mnemonic", return_value="mnemonic"), \
         patch("getpass.getpass", return_value="password"), \
         patch("iwa.core.mnemonic.Account") as mock_account:
        mock_account.from_key.return_value.address = "0xAddress"

        accounts = mgr.derive_eth_accounts_from_mnemonic(n_accounts=1)
        assert len(accounts) == 1
        assert accounts[0]["address"] == "0xAddress"
        assert accounts[0]["private_key_hex"] == "1234"

def test_mnemonic_manager_derive_eth_accounts_from_mnemonic_none(mock_scrypt, mock_aesgcm):
    mgr = MnemonicManager()
    with patch.object(mgr, "load_and_decrypt_mnemonic", return_value=None), \
         patch("getpass.getpass", return_value="password"):
        accounts = mgr.derive_eth_accounts_from_mnemonic()
        assert accounts is None

def test_main(mock_scrypt, mock_aesgcm, mock_bip39_seed_generator, mock_bip44):
    with patch("iwa.core.mnemonic.MnemonicManager") as mock_mgr:
        mock_mgr.return_value.derive_eth_accounts_from_mnemonic.return_value = [{"index": 0, "address": "0xAddress"}]
        main()
        mock_mgr.return_value.derive_eth_accounts_from_mnemonic.assert_called_once()

def test_main_none(mock_scrypt, mock_aesgcm):
    with patch("iwa.core.mnemonic.MnemonicManager") as mock_mgr:
        mock_mgr.return_value.derive_eth_accounts_from_mnemonic.return_value = None
        main()
        mock_mgr.return_value.derive_eth_accounts_from_mnemonic.assert_called_once()
