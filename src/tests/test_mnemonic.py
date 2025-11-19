import pytest
import json
from iwa.core.mnemonic import MnemonicManager

def test_mnemonic_encryption_decryption():
    """Test encrypting and decrypting a mnemonic."""
    manager = MnemonicManager()
    mnemonic = "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about"
    password = "test_password"

    # Encrypt
    encrypted = manager.encrypt_mnemonic(mnemonic, password)
    assert "ciphertext" in encrypted
    assert "kdf_salt" in encrypted

    # Decrypt
    decrypted = manager.decrypt_mnemonic(encrypted, password)
    assert decrypted == mnemonic

def test_mnemonic_decryption_wrong_password():
    """Test that decrypting with wrong password fails."""
    manager = MnemonicManager()
    mnemonic = "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about"
    password = "test_password"

    encrypted = manager.encrypt_mnemonic(mnemonic, password)

    # Decrypt with wrong password should raise or return garbage/fail tag check
    # The current implementation uses AESGCM which raises InvalidTag on failure
    from cryptography.exceptions import InvalidTag

    with pytest.raises(InvalidTag):
        manager.decrypt_mnemonic(encrypted, "wrong_password")

def test_mnemonic_manager_defaults():
    """Test default values of MnemonicManager."""
    manager = MnemonicManager()
    assert manager.scrypt_n == 2**14
    assert manager.scrypt_r == 8
    assert manager.scrypt_p == 1
