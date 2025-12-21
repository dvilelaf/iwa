import base64
import json
from pathlib import Path
from unittest.mock import MagicMock, mock_open, patch

import pytest

from iwa.core.keys import EncryptedAccount, KeyStorage, StoredSafeAccount


@pytest.fixture
def mock_secrets():
    with patch("iwa.core.keys.settings") as mock:
        mock.wallet_password.get_secret_value.return_value = "password"
        mock.gnosis_rpc.get_secret_value.return_value = "http://rpc"
        yield mock


@pytest.fixture
def mock_aesgcm():
    with patch("iwa.core.keys.AESGCM") as mock:
        mock.return_value.encrypt.return_value = b"ciphertext"
        mock.return_value.decrypt.return_value = b"private_key"
        yield mock


@pytest.fixture
def mock_scrypt():
    with patch("iwa.core.keys.Scrypt") as mock:
        mock.return_value.derive.return_value = b"key"
        yield mock


@pytest.fixture
def mock_account():
    with patch("iwa.core.keys.Account") as mock:
        # Use valid checksummed addresses to avoid mismatch between key and value in self.accounts
        from itertools import cycle

        addresses = cycle(
            [
                "0x5B38Da6a701c568545dCfcB03FcB875f56beddC4",
                "0xAb5801a7D398351b8bE11C439e05C5B3259aeC9B",
                "0x4B20993Bc481177ec7E8f571ceCaE8A9e22C02db",
                "0x78731D3Ca6b7E34aC0F824c42a7cC18A495cabaB",
            ]
        )

        def create_side_effect():
            addr = next(addresses)
            m = MagicMock()
            m.key.hex.return_value = f"0xPrivateKey{addr}"
            m.address = addr
            return m

        mock.create.side_effect = create_side_effect

        def from_key_side_effect(private_key):
            # Extract address from the mocked key format if possible
            if isinstance(private_key, str) and "0xPrivateKey" in private_key:
                addr = private_key.replace("0xPrivateKey", "")
            else:
                # Default fallback if key format is unexpected
                addr = "0x5B38Da6a701c568545dCfcB03FcB875f56beddC4"

            m = MagicMock()
            m.address = addr
            m.key = private_key.encode() if isinstance(private_key, str) else private_key
            return m

        mock.from_key.side_effect = from_key_side_effect
        yield mock


@pytest.fixture
def mock_ethereum_client():
    with patch("iwa.core.keys.EthereumClient") as mock:
        yield mock


def test_encrypted_account_derive_key(mock_scrypt):
    key = EncryptedAccount.derive_key("password", b"salt")
    assert key == b"key"
    mock_scrypt.assert_called_once()


def test_encrypted_account_encrypt_private_key(mock_scrypt, mock_aesgcm, mock_account):
    enc_account = EncryptedAccount.encrypt_private_key("0xPrivateKey0x5B38Da6a701c568545dCfcB03FcB875f56beddC4", "password", "tag")
    assert enc_account.address == "0x5B38Da6a701c568545dCfcB03FcB875f56beddC4"
    assert enc_account.tag == "tag"
    assert enc_account.ciphertext == base64.b64encode(b"ciphertext").decode()


def test_encrypted_account_decrypt_private_key(mock_scrypt, mock_aesgcm, mock_secrets):
    enc_account = EncryptedAccount(
        address="0x1111111111111111111111111111111111111111",
        salt=base64.b64encode(b"salt").decode(),
        nonce=base64.b64encode(b"nonce").decode(),
        ciphertext=base64.b64encode(b"ciphertext").decode(),
        tag="tag",
    )
    pkey = enc_account.decrypt_private_key()
    assert pkey == "private_key"


def test_keystorage_init_new(mock_secrets, mock_account, mock_aesgcm, mock_scrypt):
    """Test initialization of new KeyStorage automatically creates master account."""
    with (
        patch("os.path.exists", return_value=False),
        patch("builtins.open", mock_open()),
        patch("os.chmod"),
        patch("pathlib.Path.mkdir"),
    ):
        storage = KeyStorage(Path("wallet.json"))
        # Master account should be created automatically
        assert len(storage.accounts) == 1
        assert storage.get_account("master") is not None


def test_keystorage_init_existing(mock_secrets):
    data = {
        "accounts": {
            "0x1111111111111111111111111111111111111111": {
                "address": "0x1111111111111111111111111111111111111111",
                "salt": "salt",
                "nonce": "nonce",
                "ciphertext": "ciphertext",
                "tag": "tag",
            }
        }
    }
    with (
        patch("os.path.exists", return_value=True),
        patch("builtins.open", mock_open(read_data=json.dumps(data))),
        patch("iwa.core.keys.KeyStorage.create_account") as mock_create_master,
    ):
        storage = KeyStorage(Path("wallet.json"))
        assert "0x1111111111111111111111111111111111111111" in storage.accounts
        # Master creation triggered because 'master' tag is missing
        mock_create_master.assert_called_with("master")


def test_keystorage_init_corrupted(mock_secrets, mock_account, mock_aesgcm, mock_scrypt):
    with (
        patch("os.path.exists", return_value=True),
        patch("builtins.open", mock_open(read_data="{invalid json")),
        patch("iwa.core.keys.logger") as mock_logger,
        patch("os.chmod"),
        patch("pathlib.Path.mkdir"),
    ):
        storage = KeyStorage(Path("wallet.json"))
        # Corrupted file -> empty accounts -> auto create master
        assert len(storage.accounts) == 1
        assert storage.get_account("master") is not None
        mock_logger.error.assert_called()


def test_keystorage_save(mock_secrets, mock_account, mock_aesgcm, mock_scrypt):
    with (
        patch("os.path.exists", return_value=False),
        patch("builtins.open", mock_open()) as mock_file,
        patch("os.chmod") as mock_chmod,
        patch("pathlib.Path.mkdir"),
    ):
        storage = KeyStorage(Path("wallet.json"))
        storage.save()
        mock_file.assert_called()
        mock_chmod.assert_called()


def test_keystorage_create_account(mock_secrets, mock_account, mock_aesgcm, mock_scrypt):
    with (
        patch("os.path.exists", return_value=False),
        patch("builtins.open", mock_open()),
        patch("os.chmod"),
        patch("pathlib.Path.mkdir"),
    ):
        storage = KeyStorage(Path("wallet.json"))
        # Master created in init
        enc_account = storage.create_account("tag")
        assert enc_account.tag == "tag"
        assert len(storage.accounts) == 2  # master + tag


def test_keystorage_create_account_duplicate_tag(
    mock_secrets, mock_account, mock_aesgcm, mock_scrypt
):
    with (
        patch("os.path.exists", return_value=False),
        patch("builtins.open", mock_open()),
        patch("os.chmod"),
        patch("pathlib.Path.mkdir"),
    ):
        storage = KeyStorage(Path("wallet.json"))
        storage.create_account("tag")
        with pytest.raises(ValueError, match="already exists"):
            storage.create_account("tag")


def test_keystorage_get_private_key(mock_secrets, mock_account, mock_aesgcm, mock_scrypt):
    with (
        patch("os.path.exists", return_value=False),
        patch("builtins.open", mock_open()),
        patch("os.chmod"),
        patch("pathlib.Path.mkdir"),
    ):
        storage = KeyStorage(Path("wallet.json"))
        # Just use master account for check
        master = storage.get_account("master")
        # _get_private_key is internal but used by tests
        pkey = storage._get_private_key(master.address)
        assert pkey == "private_key"


def test_keystorage_sign_message(mock_secrets, mock_account, mock_aesgcm, mock_scrypt):
    """Test sign_message method signs messages without exposing private key."""
    with (
        patch("os.path.exists", return_value=False),
        patch("builtins.open", mock_open()),
        patch("os.chmod"),
        patch("pathlib.Path.mkdir"),
    ):
        storage = KeyStorage(Path("wallet.json"))
        storage.create_account("tag")

        # Mock the sign_message on Account
        mock_signed_msg = MagicMock()
        mock_signed_msg.signature = b"signature"
        mock_account.sign_message.return_value = mock_signed_msg

        result = storage.sign_message(b"test message", "tag")
        assert result == b"signature"


def test_keystorage_sign_transaction(mock_secrets, mock_account, mock_aesgcm, mock_scrypt):
    with (
        patch("os.path.exists", return_value=False),
        patch("builtins.open", mock_open()),
        patch("os.chmod"),
        patch("pathlib.Path.mkdir"),
    ):
        storage = KeyStorage(Path("wallet.json"))
        storage.create_account("tag")

        tx = {
            "to": "0x0000000000000000000000000000000000000000",
            "value": 0,
            "gas": 21000,
            "gasPrice": 1,
            "nonce": 0,
            "chainId": 1,
        }

        # Configure the mock_account (which mocks iwa.core.keys.Account)
        mock_signed_tx = MagicMock()
        mock_account.sign_transaction.return_value = mock_signed_tx

        result = storage.sign_transaction(tx, "tag")
        assert result == mock_signed_tx

        # Verify it was called with the private key (which is mocked as "private_key" in mock_aesgcm)
        mock_account.sign_transaction.assert_called_once()
        args, _ = mock_account.sign_transaction.call_args
        assert args[0] == tx
        assert args[1] == "private_key"


def test_keystorage_get_private_key_not_found(mock_secrets, mock_account, mock_aesgcm, mock_scrypt):
    with (
        patch("os.path.exists", return_value=False),
        patch("builtins.open", mock_open()),
        patch("os.chmod"),
        patch("pathlib.Path.mkdir"),
    ):
        storage = KeyStorage(Path("wallet.json"))
        # Master exists at 0x5B..., so check an unknown address
        assert storage._get_private_key("0x0000000000000000000000000000000000000000") is None


def test_keystorage_get_account(mock_secrets, mock_account, mock_aesgcm, mock_scrypt):
    with (
        patch("os.path.exists", return_value=False),
        patch("builtins.open", mock_open()),
        patch("os.chmod"),
        patch("pathlib.Path.mkdir"),
    ):
        storage = KeyStorage(Path("wallet.json"))
        # create_account("tag") creates a second account
        acc1 = storage.create_account("tag")

        # Get by address
        acct = storage.get_account(acc1.address)
        assert acct.address == acc1.address

        # Get by tag
        acct = storage.get_account("tag")
        assert acct.address == acc1.address


def test_keystorage_get_tag_by_address(mock_secrets, mock_account, mock_aesgcm, mock_scrypt):
    with (
        patch("os.path.exists", return_value=False),
        patch("builtins.open", mock_open()),
        patch("os.chmod"),
        patch("pathlib.Path.mkdir"),
    ):
        storage = KeyStorage(Path("wallet.json"))
        acc = storage.create_account("tag")
        assert storage.get_tag_by_address(acc.address) == "tag"
        # Master
        master = storage.get_account("master")
        assert storage.get_tag_by_address(master.address) == "master"
        assert storage.get_tag_by_address("0x3333333333333333333333333333333333333333") is None


def test_keystorage_get_address_by_tag(mock_secrets, mock_account, mock_aesgcm, mock_scrypt):
    with (
        patch("os.path.exists", return_value=False),
        patch("builtins.open", mock_open()),
        patch("os.chmod"),
        patch("pathlib.Path.mkdir"),
    ):
        storage = KeyStorage(Path("wallet.json"))
        acc = storage.create_account("tag")
        assert storage.get_address_by_tag("tag") == acc.address
        assert storage.get_address_by_tag("unknown") is None


def test_keystorage_master_account_fallback(mock_secrets, mock_account, mock_aesgcm, mock_scrypt):
    with (
        patch("os.path.exists", return_value=False),
        patch("builtins.open", mock_open()),
        patch("os.chmod"),
        patch("pathlib.Path.mkdir"),
        # Mock default creation of master to verify fallback logic if master was missing
        patch("iwa.core.keys.KeyStorage.create_account")
    ):
        storage = KeyStorage(Path("wallet.json"))
        # IMPORTANT: because we patched create_account, master wasn't actually added to storage.accounts
        # Manual injection
        enc_account = EncryptedAccount(
            address="0x5B38Da6a701c568545dCfcB03FcB875f56beddC4",
            salt="salt",
            nonce="nonce",
            ciphertext="ciphertext",
            tag="other",
        )
        storage.accounts["0x5B38Da6a701c568545dCfcB03FcB875f56beddC4"] = enc_account

        # Should return the first account if master not found in get_account("master")
        # Wait, get_account("master") calls find_stored_account("master").
        # If "master" tag doesn't exist, master_account property logic kicks in: returns first value.
        assert storage.master_account.tag == "other"


def test_keystorage_master_account_success(mock_secrets, mock_account, mock_aesgcm, mock_scrypt):
    with (
        patch("os.path.exists", return_value=False),
        patch("builtins.open", mock_open()),
        patch("os.chmod"),
        patch("pathlib.Path.mkdir"),
    ):
        storage = KeyStorage(Path("wallet.json"))
        # Master created in init, just check it
        assert storage.master_account.tag == "master"
        assert storage.master_account.address is not None


def test_keystorage_create_account_default_tag(
    mock_secrets, mock_account, mock_aesgcm, mock_scrypt
):
    with (
        patch("os.path.exists", return_value=False),
        patch("builtins.open", mock_open()),
        patch("os.chmod"),
        patch("pathlib.Path.mkdir"),
    ):
        storage = KeyStorage(Path("wallet.json"))
        # Master already exists, so create_account("foo") returns account with tag "foo"
        # The original test checked if creating *without* arguments or similar defaulted to master,
        # but create_account requires a tag argument.
        # The code inside create_account handles `if not tags: tag="master"`.
        # Since tags is not empty (contains master), that logic is skipped.
        # So we just test that we can create a regular account.
        acc = storage.create_account("foo")
        assert acc.tag == "foo"
        assert len(storage.accounts) == 2


def test_keystorage_remove_account_not_found(
    mock_secrets, mock_account, mock_aesgcm, mock_scrypt
):
    with (
        patch("os.path.exists", return_value=False),
        patch("builtins.open", mock_open()),
        patch("os.chmod"),
        patch("pathlib.Path.mkdir"),
    ):
        storage = KeyStorage(Path("wallet.json"))
        # Should not raise
        storage.remove_account("0x5B38Da6a701c568545dCfcB03FcB875f56beddC4")




def test_keystorage_get_account_auto_load_safe(
    mock_secrets, mock_account, mock_aesgcm, mock_scrypt
):
    """Test that get_account handles StoredSafeAccount if manually injected."""
    with (
        patch("os.path.exists", return_value=False),
        patch("builtins.open", mock_open()),
        patch("os.chmod"),
        patch("pathlib.Path.mkdir"),
    ):
        storage = KeyStorage(Path("wallet.json"))
        # Use a valid checksum address
        safe_addr = "0x61a4f49e9dD1f90EB312889632FA956a21353720"

        safe = StoredSafeAccount(
            tag="safe", address=safe_addr, chains=["gnosis"], threshold=1, signers=[]
        )
        storage.accounts[safe_addr] = safe

        # Get by address
        acc = storage.get_account(safe_addr)
        assert isinstance(acc, StoredSafeAccount)
        assert acc.tag == "safe"


def test_keystorage_get_account_none(mock_secrets):
    with patch("os.path.exists", return_value=False):
        storage = KeyStorage(Path("wallet.json"))
        assert storage.get_account("0x5B38Da6a701c568545dCfcB03FcB875f56beddC4") is None
        assert storage.get_account("tag") is None


def test_get_account_info(mock_secrets, mock_account, mock_aesgcm, mock_scrypt):
    with (
        patch("os.path.exists", return_value=False),
        patch("builtins.open", mock_open()),
        patch("os.chmod"),
        patch("pathlib.Path.mkdir"),
    ):
        storage = KeyStorage(Path("wallet.json"))
        # Master created in init

        storage.create_account("tag1")

        info = storage.get_account_info("tag1")
        assert info.address == storage.find_stored_account("tag1").address
        assert info.tag == "tag1"
        assert not hasattr(info, "key")


def test_get_signer(mock_secrets, mock_account, mock_aesgcm, mock_scrypt):
    storage = KeyStorage(Path("wallet.json"))
    with patch("builtins.open", mock_open()), patch("os.chmod"), patch("pathlib.Path.mkdir"):
        storage.create_account("tag")

        # Test valid signer retrieval
        signer = storage.get_signer("tag")
        assert signer is not None
        # mock_account.from_key returns a mock, so we check if it was called
        mock_account.from_key.assert_called_with("private_key")

        # Test non-existent account
        assert storage.get_signer("unknown") is None

        # Test safe account (should return None)
        safe = StoredSafeAccount(
            tag="safe",
            address="0x61a4f49e9dD1f90EB312889632FA956a21353720",
            chains=["gnosis"],
            threshold=1,
            signers=[],
        )
        storage.accounts["0x61a4f49e9dD1f90EB312889632FA956a21353720"] = safe
        assert storage.get_signer("safe") is None


# --- Tests migrated from test_keystorage_edge_cases.py ---


def test_keystorage_edge_cases_with_real_storage(tmp_path):
    """Test KeyStorage edge cases with real file storage."""
    wallet_path = tmp_path / "wallet.json"
    storage = KeyStorage(wallet_path, password="password")

    # Create account
    encrypted_acc = storage.create_account("acc1")
    assert encrypted_acc is not None

    # Get by address
    acc_by_addr = storage.get_account(encrypted_acc.address)
    assert acc_by_addr is not None

    # Remove account
    storage.remove_account(encrypted_acc.address)

    # Verify removal
    assert storage.get_account(encrypted_acc.address) is None
    assert storage.get_account("acc1") is None

    # Get private key via internal method
    encrypted_acc2 = storage.create_account("acc2")
    pk = storage._get_private_key(encrypted_acc2.address)
    assert pk is not None

    # Sign transaction unknown account
    with pytest.raises(ValueError):
        storage.sign_transaction({}, "0xUnknown")
