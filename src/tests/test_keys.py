import os
import stat
import json
import pytest
from iwa.core.keys import KeyStorage, EncryptedAccount
from iwa.core.models import Secrets

def test_encrypted_account_encryption_decryption():
    """Test that private keys can be encrypted and decrypted."""
    password = "strong_password"
    private_key = "0x" + "1" * 64

    encrypted = EncryptedAccount.encrypt_private_key(private_key, password, tag="test_tag")

    assert encrypted.tag == "test_tag"
    assert encrypted.address is not None

    decrypted = encrypted.decrypt_private_key(password)
    assert decrypted == private_key

def test_keystorage_create_account(temp_wallet_file):
    """Test creating a new account in KeyStorage."""
    storage = KeyStorage(path=temp_wallet_file, password="test_password")

    # Should be empty initially
    assert len(storage.accounts) == 0

    # Create first account (master)
    account = storage.create_account("master")
    assert account.tag == "master"
    assert len(storage.accounts) == 1

    # Create second account
    account2 = storage.create_account("secondary")
    assert account2.tag == "secondary"
    assert len(storage.accounts) == 2

def test_keystorage_persistence(temp_wallet_file):
    """Test that accounts are saved to disk and can be loaded."""
    storage = KeyStorage(path=temp_wallet_file, password="test_password")
    storage.create_account("master")

    # Load from same file
    storage2 = KeyStorage(path=temp_wallet_file, password="test_password")
    assert len(storage2.accounts) == 1
    assert "master" in [a.tag for a in storage2.accounts.values()]

def test_keystorage_permissions(temp_wallet_file):
    """Test that the wallet file has 600 permissions."""
    storage = KeyStorage(path=temp_wallet_file, password="test_password")
    storage.create_account("master")

    # Check permissions
    mode = os.stat(temp_wallet_file).st_mode
    permissions = stat.S_IMODE(mode)
    assert permissions == 0o600

def test_keystorage_corrupted_file(temp_wallet_file):
    """Test that KeyStorage handles corrupted files gracefully."""
    # Create corrupted file
    with open(temp_wallet_file, "w") as f:
        f.write("{ invalid json }")

    # Should not raise exception
    storage = KeyStorage(path=temp_wallet_file, password="test_password")
    assert len(storage.accounts) == 0

def test_duplicate_tag_error(temp_wallet_file):
    """Test that creating an account with a duplicate tag raises ValueError."""
    storage = KeyStorage(path=temp_wallet_file, password="test_password")
    storage.create_account("master")

    with pytest.raises(ValueError, match="Tag 'master' already exists"):
        storage.create_account("master")
