"""Tests for KeyStorage - all tests use tmp_path to avoid touching real wallet.json."""

import base64
import json
from unittest.mock import MagicMock, patch

import pytest

from iwa.core.keys import EncryptedAccount, KeyStorage, StoredSafeAccount


@pytest.fixture
def mock_secrets():
    """Mock secrets to provide test password."""
    with patch("iwa.core.keys.secrets") as mock:
        mock.wallet_password.get_secret_value.return_value = "test_password"
        mock.gnosis_rpc.get_secret_value.return_value = "http://rpc"
        yield mock


@pytest.fixture
def mock_aesgcm():
    """Mock AESGCM for predictable encryption/decryption."""
    with patch("iwa.core.keys.AESGCM") as mock:
        mock.return_value.encrypt.return_value = b"ciphertext"
        mock.return_value.decrypt.return_value = b"private_key"
        yield mock


@pytest.fixture
def mock_scrypt():
    """Mock Scrypt for predictable key derivation."""
    with patch("iwa.core.keys.Scrypt") as mock:
        mock.return_value.derive.return_value = b"key" * 11  # 32 bytes
        yield mock


@pytest.fixture
def mock_account():
    """Mock eth_account.Account for predictable account creation."""
    with patch("iwa.core.keys.Account") as mock:
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
            # Skip the first address if it's reserved for the master account
            # (to avoid overwriting master if generate_new_account is called immediately)
            addr = next(addresses)
            if addr == "0x5B38Da6a701c568545dCfcB03FcB875f56beddC4":
                addr = next(addresses)

            m = MagicMock()
            m.key.hex.return_value = f"0xPrivateKey{addr}"
            m.address = addr
            return m

        mock.create.side_effect = create_side_effect

        def from_key_side_effect(private_key):
            # 1. Handle the master private key
            if (
                private_key
                == "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"  # gitleaks:allow
            ):
                addr = "0x5B38Da6a701c568545dCfcB03FcB875f56beddC4"
            # 2. Handle our mock key format
            elif isinstance(private_key, str) and private_key.startswith("0xPrivateKey"):
                addr = private_key.replace("0xPrivateKey", "")
            # 3. Default fallback
            else:
                addr = "0xAb5801a7D398351b8bE11C439e05C5B3259aeC9B"

            m = MagicMock()
            m.address = addr
            return m

        mock.from_key.side_effect = from_key_side_effect
        yield mock


@pytest.fixture
def mock_bip_utils():
    """Mock BIP-utils for mnemonic derivation."""
    with (
        patch("iwa.core.keys.Bip39MnemonicGenerator") as mock_gen,
        patch("iwa.core.keys.Bip39SeedGenerator") as mock_seed,
        patch("iwa.core.keys.Bip44") as mock_bip44,
    ):
        # Generator
        mock_gen.return_value.FromWordsNumber.return_value.ToStr.return_value = (
            "word " * 23 + "word"
        )

        # Derivation chain
        mock_bip44.FromSeed.return_value.Purpose.return_value.Coin.return_value.Account.return_value.Change.return_value.AddressIndex.return_value.PrivateKey.return_value.Raw.return_value.ToHex.return_value = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"

        yield {
            "gen": mock_gen,
            "seed": mock_seed,
            "bip44": mock_bip44,
        }


# --- EncryptedAccount tests (no file I/O needed) ---


def test_encrypted_account_derive_key(mock_scrypt):
    """Test key derivation."""
    key = EncryptedAccount.derive_key("password", b"salt")
    assert key == b"key" * 11
    mock_scrypt.assert_called_once()


def test_encrypted_account_encrypt_private_key(mock_scrypt, mock_aesgcm, mock_account):
    """Test private key encryption."""
    enc_account = EncryptedAccount.encrypt_private_key(
        "0xPrivateKey0x5B38Da6a701c568545dCfcB03FcB875f56beddC4", "password", "tag"
    )
    assert enc_account.address == "0x5B38Da6a701c568545dCfcB03FcB875f56beddC4"
    assert enc_account.tag == "tag"
    assert enc_account.ciphertext == base64.b64encode(b"ciphertext").decode()


def test_encrypted_account_decrypt_private_key(mock_scrypt, mock_aesgcm, mock_secrets):
    """Test private key decryption."""
    enc_account = EncryptedAccount(
        address="0x1111111111111111111111111111111111111111",
        salt=base64.b64encode(b"salt").decode(),
        nonce=base64.b64encode(b"nonce").decode(),
        ciphertext=base64.b64encode(b"ciphertext").decode(),
        tag="tag",
    )
    pkey = enc_account.decrypt_private_key()
    assert pkey == "private_key"


# --- KeyStorage tests using tmp_path ---


def test_keystorage_init_new(
    tmp_path, mock_secrets, mock_account, mock_aesgcm, mock_scrypt, mock_bip_utils
):
    """Test initialization of new KeyStorage creates master account."""
    wallet_path = tmp_path / "wallet.json"
    storage = KeyStorage(wallet_path, password="test_password")

    # Master account should be created automatically
    assert len(storage.accounts) == 1
    assert storage.get_account("master") is not None


def test_keystorage_init_existing(tmp_path, mock_secrets):
    """Test loading existing wallet file."""
    wallet_path = tmp_path / "wallet.json"
    data = {
        "accounts": {
            "0x1111111111111111111111111111111111111111": {
                "address": "0x1111111111111111111111111111111111111111",
                "salt": base64.b64encode(b"salt").decode(),
                "nonce": base64.b64encode(b"nonce").decode(),
                "ciphertext": base64.b64encode(b"ciphertext").decode(),
                "tag": "master",
            }
        }
    }
    wallet_path.write_text(json.dumps(data))

    storage = KeyStorage(wallet_path, password="test_password")
    assert "0x1111111111111111111111111111111111111111" in storage.accounts
    assert storage.get_account("master") is not None


def test_keystorage_init_corrupted(
    tmp_path, mock_secrets, mock_account, mock_aesgcm, mock_scrypt, mock_bip_utils
):
    """Test handling of corrupted wallet file."""
    wallet_path = tmp_path / "wallet.json"
    wallet_path.write_text("{invalid json")

    with patch("iwa.core.keys.logger") as mock_logger:
        storage = KeyStorage(wallet_path, password="test_password")
        # Corrupted file -> empty accounts -> auto create master
        assert len(storage.accounts) == 1
        assert storage.get_account("master") is not None
        mock_logger.error.assert_called()


def test_keystorage_save(
    tmp_path, mock_secrets, mock_account, mock_aesgcm, mock_scrypt, mock_bip_utils
):
    """Test saving wallet to file."""
    wallet_path = tmp_path / "wallet.json"
    storage = KeyStorage(wallet_path, password="test_password")
    storage.save()

    # Verify file was created
    assert wallet_path.exists()
    data = json.loads(wallet_path.read_text())
    assert "accounts" in data


def test_keystorage_generate_new_account(
    tmp_path, mock_secrets, mock_account, mock_aesgcm, mock_scrypt, mock_bip_utils
):
    """Test creating additional accounts."""
    wallet_path = tmp_path / "wallet.json"
    storage = KeyStorage(wallet_path, password="test_password")

    # Master created in init
    enc_account = storage.generate_new_account("tag")
    assert enc_account.tag == "tag"
    assert len(storage.accounts) == 2  # master + tag


def test_keystorage_generate_new_account_duplicate_tag(
    tmp_path, mock_secrets, mock_account, mock_aesgcm, mock_scrypt, mock_bip_utils
):
    """Test creating account with duplicate tag raises error."""
    wallet_path = tmp_path / "wallet.json"
    storage = KeyStorage(wallet_path, password="test_password")
    storage.generate_new_account("tag")

    with pytest.raises(ValueError, match="already used"):
        storage.generate_new_account("tag")


def test_keystorage_get_private_key(tmp_path, mock_secrets, mock_account, mock_aesgcm, mock_scrypt):
    """Test internal private key retrieval."""
    wallet_path = tmp_path / "wallet.json"
    storage = KeyStorage(wallet_path, password="test_password")

    master = storage.get_account("master")
    pkey = storage._get_private_key(master.address)
    assert pkey == "private_key"


def test_keystorage_sign_message(tmp_path, mock_secrets, mock_account, mock_aesgcm, mock_scrypt):
    """Test message signing."""
    wallet_path = tmp_path / "wallet.json"
    storage = KeyStorage(wallet_path, password="test_password")
    storage.generate_new_account("tag")

    mock_signed_msg = MagicMock()
    mock_signed_msg.signature = b"signature"
    mock_account.sign_message.return_value = mock_signed_msg

    result = storage.sign_message(b"test message", "tag")
    assert result == b"signature"


def test_keystorage_sign_transaction(
    tmp_path, mock_secrets, mock_account, mock_aesgcm, mock_scrypt
):
    """Test transaction signing."""
    wallet_path = tmp_path / "wallet.json"
    storage = KeyStorage(wallet_path, password="test_password")
    storage.generate_new_account("tag")

    tx = {
        "to": "0x0000000000000000000000000000000000000000",
        "value": 0,
        "gas": 21000,
        "gasPrice": 1,
        "nonce": 0,
        "chainId": 1,
    }

    mock_signed_tx = MagicMock()
    mock_account.sign_transaction.return_value = mock_signed_tx

    result = storage.sign_transaction(tx, "tag")
    assert result == mock_signed_tx
    mock_account.sign_transaction.assert_called_once()


def test_keystorage_get_private_key_not_found(
    tmp_path, mock_secrets, mock_account, mock_aesgcm, mock_scrypt
):
    """Test private key retrieval for non-existent account."""
    wallet_path = tmp_path / "wallet.json"
    storage = KeyStorage(wallet_path, password="test_password")

    assert storage._get_private_key("0x0000000000000000000000000000000000000000") is None


def test_keystorage_get_account(tmp_path, mock_secrets, mock_account, mock_aesgcm, mock_scrypt):
    """Test getting account by address or tag."""
    wallet_path = tmp_path / "wallet.json"
    storage = KeyStorage(wallet_path, password="test_password")
    acc1 = storage.generate_new_account("tag")

    # Get by address
    acct = storage.get_account(acc1.address)
    assert acct.address == acc1.address

    # Get by tag
    acct = storage.get_account("tag")
    assert acct.address == acc1.address


def test_keystorage_get_tag_by_address(
    tmp_path, mock_secrets, mock_account, mock_aesgcm, mock_scrypt, mock_bip_utils
):
    """Test getting tag by address."""
    wallet_path = tmp_path / "wallet.json"
    storage = KeyStorage(wallet_path, password="test_password")
    acc = storage.generate_new_account("tag")

    assert storage.get_tag_by_address(acc.address) == "tag"
    master = storage.get_account("master")
    assert storage.get_tag_by_address(master.address) == "master"
    assert storage.get_tag_by_address("0x3333333333333333333333333333333333333333") is None


def test_keystorage_get_address_by_tag(
    tmp_path, mock_secrets, mock_account, mock_aesgcm, mock_scrypt
):
    """Test getting address by tag."""
    wallet_path = tmp_path / "wallet.json"
    storage = KeyStorage(wallet_path, password="test_password")
    acc = storage.generate_new_account("tag")

    assert storage.get_address_by_tag("tag") == acc.address
    assert storage.get_address_by_tag("unknown") is None


def test_keystorage_master_account_fallback(tmp_path, mock_secrets):
    """Test master_account property fallback when no master tag."""
    wallet_path = tmp_path / "wallet.json"

    # Create a wallet with an account that doesn't have "master" tag
    enc_account = EncryptedAccount(
        address="0x5B38Da6a701c568545dCfcB03FcB875f56beddC4",
        salt=base64.b64encode(b"salt").decode(),
        nonce=base64.b64encode(b"nonce").decode(),
        ciphertext=base64.b64encode(b"ciphertext").decode(),
        tag="other",
    )

    data = {"accounts": {enc_account.address: enc_account.model_dump()}}
    wallet_path.write_text(json.dumps(data))

    # Patch generate_new_account to prevent auto-creation of master
    with patch.object(KeyStorage, "generate_new_account"):
        storage = KeyStorage(wallet_path, password="test_password")
        # Manually add the account since generate_new_account is mocked
        storage.accounts[enc_account.address] = enc_account

        # Should return the first account if master not found
        assert storage.master_account.tag == "other"


def test_keystorage_master_account_success(
    tmp_path, mock_secrets, mock_account, mock_aesgcm, mock_scrypt, mock_bip_utils
):
    """Test master_account property returns master."""
    wallet_path = tmp_path / "wallet.json"
    storage = KeyStorage(wallet_path, password="test_password")

    assert storage.master_account.tag == "master"
    assert storage.master_account.address is not None


def test_keystorage_generate_new_account_default_tag(
    tmp_path, mock_secrets, mock_account, mock_aesgcm, mock_scrypt, mock_bip_utils
):
    """Test creating account with custom tag."""
    wallet_path = tmp_path / "wallet.json"
    storage = KeyStorage(wallet_path, password="test_password")

    acc = storage.generate_new_account("foo")
    assert acc.tag == "foo"
    assert len(storage.accounts) == 2


def test_keystorage_remove_account_not_found(
    tmp_path, mock_secrets, mock_account, mock_aesgcm, mock_scrypt, mock_bip_utils
):
    """Test removing non-existent account doesn't raise."""
    wallet_path = tmp_path / "wallet.json"
    storage = KeyStorage(wallet_path, password="test_password")

    # Should not raise
    storage.remove_account("0x0000000000000000000000000000000000000000")


def test_keystorage_get_account_auto_load_safe(
    tmp_path, mock_secrets, mock_account, mock_aesgcm, mock_scrypt, mock_bip_utils
):
    """Test getting StoredSafeAccount."""
    wallet_path = tmp_path / "wallet.json"
    storage = KeyStorage(wallet_path, password="test_password")

    safe_addr = "0x61a4f49e9dD1f90EB312889632FA956a21353720"
    safe = StoredSafeAccount(
        tag="safe", address=safe_addr, chains=["gnosis"], threshold=1, signers=[]
    )
    storage.accounts[safe_addr] = safe

    acc = storage.get_account(safe_addr)
    assert isinstance(acc, StoredSafeAccount)
    assert acc.tag == "safe"


def test_keystorage_get_account_none(tmp_path, mock_secrets):
    """Test getting non-existent account returns None."""
    wallet_path = tmp_path / "wallet.json"

    # Create empty wallet
    data = {"accounts": {}}
    wallet_path.write_text(json.dumps(data))

    # Patch generate_new_account to prevent auto-creation
    with patch.object(KeyStorage, "generate_new_account"):
        storage = KeyStorage(wallet_path, password="test_password")
        assert storage.get_account("0x5B38Da6a701c568545dCfcB03FcB875f56beddC4") is None
        assert storage.get_account("tag") is None


def test_get_account_info(tmp_path, mock_secrets, mock_account, mock_aesgcm, mock_scrypt):
    """Test get_account_info alias."""
    wallet_path = tmp_path / "wallet.json"
    storage = KeyStorage(wallet_path, password="test_password")
    storage.generate_new_account("tag1")

    info = storage.get_account_info("tag1")
    assert info.address == storage.find_stored_account("tag1").address
    assert info.tag == "tag1"
    assert not hasattr(info, "key")


def test_get_signer(tmp_path, mock_secrets, mock_account, mock_aesgcm, mock_scrypt):
    """Test get_signer method."""
    wallet_path = tmp_path / "wallet.json"
    storage = KeyStorage(wallet_path, password="test_password")
    storage.generate_new_account("tag")

    # Test valid signer retrieval
    signer = storage.get_signer("tag")
    assert signer is not None
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


def test_keystorage_edge_cases_with_real_storage(tmp_path):
    """Test KeyStorage edge cases with real file storage."""
    wallet_path = tmp_path / "wallet.json"
    storage = KeyStorage(wallet_path, password="password")

    # Create account
    encrypted_acc = storage.generate_new_account("acc1")
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
    encrypted_acc2 = storage.generate_new_account("acc2")
    pk = storage._get_private_key(encrypted_acc2.address)
    assert pk is not None

    # Sign transaction unknown account
    with pytest.raises(ValueError):
        storage.sign_transaction({}, "0xUnknown")
