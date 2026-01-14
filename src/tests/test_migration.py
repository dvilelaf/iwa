from iwa.core.keys import EncryptedAccount
from iwa.core.models import EncryptedData


def test_legacy_account_migration():
    """Test that a legacy account dict is correctly upgraded."""
    legacy_data = {
        "address": "0xCD0184079fb3Bd15ddE5Bcbc248d81a893482280",
        "tag": "master",
        "salt": "FW19o5XPRxinb18TuQroxg==",
        "nonce": "s1K+wNb24JY2BGeH",
        "ciphertext": "i5BYYBjR7jiSW6OTNFuXJ03FaNQjlgbXMSo8uEgz71jtWQ24MAOZqJYckEjEqPFv4GX/Dwi5QVZFWV+tqECNh7AK0zY3/po4FDL7DU3s5ms=",
    }

    # Load into model
    account = EncryptedAccount(**legacy_data)

    # Verify legacy fields are mapped
    assert account.kdf_salt == legacy_data["salt"]
    assert account.nonce == legacy_data["nonce"]
    assert account.ciphertext == legacy_data["ciphertext"]

    # Verify default KDF params are set
    assert account.kdf == "scrypt"
    assert account.kdf_n == 16384
    assert account.kdf_r == 8
    assert account.kdf_p == 1
    assert account.cipher == "aesgcm"

    # Verify it is an instance of EncryptedData (implicitly checking inheritance)
    assert isinstance(account, EncryptedData)


def test_new_account_format():
    """Test that a new account is created with explicit params."""
    # We use a mocked password and private key
    # This just tests structure, not actual crypto (covered by other tests)
    account = EncryptedAccount.encrypt_private_key(
        "0x0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        "password",
        tag="new_test",
    )

    data = account.model_dump()

    assert data["kdf"] == "scrypt"
    assert "kdf_salt" in data
    assert data["kdf_n"] == 16384
    assert data["cipher"] == "aesgcm"

    # Ensure legacy salt is NOT present (avoid duplication)
    assert "salt" not in data
