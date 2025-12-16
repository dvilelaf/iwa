import base64
import json
from pathlib import Path
from unittest.mock import MagicMock, mock_open, patch

import pytest

from iwa.core.keys import EncryptedAccount, KeyStorage, StoredSafeAccount


@pytest.fixture
def mock_secrets():
    with patch("iwa.core.keys.Secrets") as mock:
        mock.return_value.wallet_password.get_secret_value.return_value = "password"
        mock.return_value.gnosis_rpc.get_secret_value.return_value = "http://rpc"
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

        mock.from_key.return_value.address = "0x5B38Da6a701c568545dCfcB03FcB875f56beddC4"
        mock.from_key.return_value.key = b"private_key"
        yield mock


@pytest.fixture
def mock_safe():
    with patch("iwa.core.keys.Safe") as mock:
        mock.create.return_value.tx_hash.hex.return_value = "0xHash"
        # Use a distinct checksummed address for safe (corrected checksum)
        mock.create.return_value.contract_address = "0x61a4f49e9dD1f90EB312889632FA956a21353720"
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
    enc_account = EncryptedAccount.encrypt_private_key("0xPrivateKey", "password", "tag")
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


def test_keystorage_init_new(mock_secrets):
    with patch("os.path.exists", return_value=False):
        storage = KeyStorage(Path("wallet.json"))
        assert storage.accounts == {}


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
    ):
        storage = KeyStorage(Path("wallet.json"))
        assert "0x1111111111111111111111111111111111111111" in storage.accounts
        assert isinstance(
            storage.accounts["0x1111111111111111111111111111111111111111"], EncryptedAccount
        )


def test_keystorage_init_corrupted(mock_secrets):
    with (
        patch("os.path.exists", return_value=True),
        patch("builtins.open", mock_open(read_data="{invalid json")),
        patch("iwa.core.keys.logger") as mock_logger,
    ):
        storage = KeyStorage(Path("wallet.json"))
        assert storage.accounts == {}
        mock_logger.error.assert_called()


def test_keystorage_save(mock_secrets):
    storage = KeyStorage(Path("wallet.json"))
    with (
        patch("builtins.open", mock_open()) as mock_file,
        patch("os.chmod") as mock_chmod,
        patch("pathlib.Path.mkdir"),
    ):
        storage.save()
        mock_file.assert_called_once()
        mock_chmod.assert_called_once()


def test_keystorage_create_account(mock_secrets, mock_account, mock_aesgcm, mock_scrypt):
    storage = KeyStorage(Path("wallet.json"))
    with patch("builtins.open", mock_open()), patch("os.chmod"), patch("pathlib.Path.mkdir"):
        enc_account = storage.create_account("tag")
        assert enc_account.tag == "tag"
        assert "0x5B38Da6a701c568545dCfcB03FcB875f56beddC4" in storage.accounts


def test_keystorage_create_account_duplicate_tag(
    mock_secrets, mock_account, mock_aesgcm, mock_scrypt
):
    storage = KeyStorage(Path("wallet.json"))
    with patch("builtins.open", mock_open()), patch("os.chmod"), patch("pathlib.Path.mkdir"):
        storage.create_account("tag")
        with pytest.raises(ValueError, match="already exists"):
            storage.create_account("tag")


def test_keystorage_create_safe(
    mock_secrets, mock_safe, mock_ethereum_client, mock_account, mock_aesgcm, mock_scrypt
):
    storage = KeyStorage(Path("wallet.json"))
    # Create deployer and owner
    with patch("builtins.open", mock_open()), patch("os.chmod"), patch("pathlib.Path.mkdir"):
        storage.create_account("deployer")
        storage.create_account("owner")

        safe = storage.create_safe(
            deployer_tag_or_address="deployer",
            owner_tags_or_addresses=["owner"],
            threshold=1,
            chain_name="gnosis",
            tag="safe",
        )
        assert safe.address == "0x61a4f49e9dD1f90EB312889632FA956a21353720"
        assert "0x61a4f49e9dD1f90EB312889632FA956a21353720" in storage.accounts


def test_keystorage_get_private_key(mock_secrets, mock_account, mock_aesgcm, mock_scrypt):
    storage = KeyStorage(Path("wallet.json"))
    with patch("builtins.open", mock_open()), patch("os.chmod"), patch("pathlib.Path.mkdir"):
        storage.create_account("tag")
        pkey = storage._get_private_key("0x5B38Da6a701c568545dCfcB03FcB875f56beddC4")
        assert pkey == "private_key"


def test_keystorage_get_private_key_unsafe(mock_secrets, mock_account, mock_aesgcm, mock_scrypt):
    storage = KeyStorage(Path("wallet.json"))
    with patch("builtins.open", mock_open()), patch("os.chmod"), patch("pathlib.Path.mkdir"):
        storage.create_account("tag")
        pkey = storage.get_private_key_unsafe("0x5B38Da6a701c568545dCfcB03FcB875f56beddC4")
        assert pkey == "private_key"


def test_keystorage_sign_transaction(mock_secrets, mock_account, mock_aesgcm, mock_scrypt):
    storage = KeyStorage(Path("wallet.json"))
    with patch("builtins.open", mock_open()), patch("os.chmod"), patch("pathlib.Path.mkdir"):
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


def test_keystorage_get_private_key_safe_error(
    mock_secrets, mock_safe, mock_ethereum_client, mock_account, mock_aesgcm, mock_scrypt
):
    storage = KeyStorage(Path("wallet.json"))
    with patch("builtins.open", mock_open()), patch("os.chmod"), patch("pathlib.Path.mkdir"):
        storage.create_account("deployer")
        storage.create_account("owner")
        storage.create_safe("deployer", ["owner"], 1, "gnosis", "safe")

        with pytest.raises(ValueError, match="Cannot get private key"):
            storage._get_private_key("0x61a4f49e9dD1f90EB312889632FA956a21353720")


def test_keystorage_get_safe_signer_keys(
    mock_secrets, mock_safe, mock_ethereum_client, mock_account, mock_aesgcm, mock_scrypt
):
    storage = KeyStorage(Path("wallet.json"))
    with patch("builtins.open", mock_open()), patch("os.chmod"), patch("pathlib.Path.mkdir"):
        storage.create_account("deployer")
        storage.create_account("owner")
        storage.create_safe("deployer", ["owner"], 1, "gnosis", "safe")

        keys = storage.get_safe_signer_keys("safe")
        assert len(keys) == 1
        assert keys[0] == "private_key"


def test_keystorage_get_account(mock_secrets, mock_account, mock_aesgcm, mock_scrypt):
    storage = KeyStorage(Path("wallet.json"))
    with patch("builtins.open", mock_open()), patch("os.chmod"), patch("pathlib.Path.mkdir"):
        storage.create_account("tag")

        # Get by address
        acct = storage.get_account("0x5B38Da6a701c568545dCfcB03FcB875f56beddC4")
        assert acct.address == "0x5B38Da6a701c568545dCfcB03FcB875f56beddC4"

        # Get by tag
        acct = storage.get_account("tag")
        assert acct.address == "0x5B38Da6a701c568545dCfcB03FcB875f56beddC4"


def test_keystorage_get_tag_by_address(mock_secrets, mock_account, mock_aesgcm, mock_scrypt):
    storage = KeyStorage(Path("wallet.json"))
    with patch("builtins.open", mock_open()), patch("os.chmod"), patch("pathlib.Path.mkdir"):
        storage.create_account("tag")
        assert storage.get_tag_by_address("0x5B38Da6a701c568545dCfcB03FcB875f56beddC4") == "tag"
        assert storage.get_tag_by_address("0x3333333333333333333333333333333333333333") is None


def test_keystorage_get_address_by_tag(mock_secrets, mock_account, mock_aesgcm, mock_scrypt):
    storage = KeyStorage(Path("wallet.json"))
    with patch("builtins.open", mock_open()), patch("os.chmod"), patch("pathlib.Path.mkdir"):
        storage.create_account("tag")
        assert storage.get_address_by_tag("tag") == "0x5B38Da6a701c568545dCfcB03FcB875f56beddC4"
        assert storage.get_address_by_tag("unknown") is None


def test_keystorage_master_account_fallback(mock_secrets, mock_account, mock_aesgcm, mock_scrypt):
    with (
        patch("os.path.exists", return_value=False),
        patch("builtins.open", mock_open()),
        patch("os.chmod"),
        patch("pathlib.Path.mkdir"),
    ):
        storage = KeyStorage(Path("wallet.json"))
        # Manually inject an account with a non-master tag to test fallback
        # create_account would force "master" tag for the first account
        enc_account = EncryptedAccount(
            address="0x5B38Da6a701c568545dCfcB03FcB875f56beddC4",
            salt="salt",
            nonce="nonce",
            ciphertext="ciphertext",
            tag="other",
        )
        storage.accounts["0x5B38Da6a701c568545dCfcB03FcB875f56beddC4"] = enc_account

        # Should return the first account if master not found
        assert storage.master_account.tag == "other"


def test_keystorage_master_account_success(mock_secrets, mock_account, mock_aesgcm, mock_scrypt):
    with (
        patch("os.path.exists", return_value=False),
        patch("builtins.open", mock_open()),
        patch("os.chmod"),
        patch("pathlib.Path.mkdir"),
    ):
        storage = KeyStorage(Path("wallet.json"))
        storage.create_account("master")
        assert storage.master_account.address == "0x5B38Da6a701c568545dCfcB03FcB875f56beddC4"


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
        acc = storage.create_account("foo")
        assert acc.tag == "master"


def test_keystorage_create_safe_deployer_not_found(mock_secrets):
    with patch("os.path.exists", return_value=False):
        storage = KeyStorage(Path("wallet.json"))
        with pytest.raises(ValueError, match="Deployer account 'deployer' not found"):
            storage.create_safe("deployer", [], 1, "gnosis")


def test_keystorage_create_safe_owner_not_found(
    mock_secrets, mock_account, mock_aesgcm, mock_scrypt
):
    with (
        patch("os.path.exists", return_value=False),
        patch("builtins.open", mock_open()),
        patch("os.chmod"),
        patch("pathlib.Path.mkdir"),
    ):
        storage = KeyStorage(Path("wallet.json"))
        storage.create_account("master")  # Create master first
        storage.create_account("deployer")
        with pytest.raises(ValueError, match="Owner account 'owner' not found"):
            storage.create_safe("deployer", ["owner"], 1, "gnosis")


def test_keystorage_remove_account_not_found(mock_secrets):
    with patch("os.path.exists", return_value=False):
        storage = KeyStorage(Path("wallet.json"))
        # Should not raise
        storage.remove_account("0x5B38Da6a701c568545dCfcB03FcB875f56beddC4")


def test_keystorage_get_private_key_not_found(mock_secrets):
    with patch("os.path.exists", return_value=False):
        storage = KeyStorage(Path("wallet.json"))
        assert storage._get_private_key("0x5B38Da6a701c568545dCfcB03FcB875f56beddC4") is None


def test_keystorage_get_safe_signer_keys_safe_not_found(mock_secrets):
    with patch("os.path.exists", return_value=False):
        storage = KeyStorage(Path("wallet.json"))
        with pytest.raises(ValueError, match="Safe account 'safe' not found"):
            storage.get_safe_signer_keys("safe")


def test_keystorage_get_safe_signer_keys_not_enough_signers(
    mock_secrets, mock_safe, mock_ethereum_client, mock_account, mock_aesgcm, mock_scrypt
):
    with (
        patch("os.path.exists", return_value=False),
        patch("builtins.open", mock_open()),
        patch("os.chmod"),
        patch("pathlib.Path.mkdir"),
    ):
        storage = KeyStorage(Path("wallet.json"))
        storage.create_account("master")  # Create master first
        storage.create_account("deployer")
        owner = storage.create_account("owner")
        storage.create_safe("deployer", ["owner"], 1, "gnosis", "safe")

        storage.remove_account(owner.address)

        with pytest.raises(ValueError, match="Not enough signer private keys"):
            storage.get_safe_signer_keys("safe")


def test_keystorage_get_account_safe(
    mock_secrets, mock_safe, mock_ethereum_client, mock_account, mock_aesgcm, mock_scrypt
):
    with (
        patch("os.path.exists", return_value=False),
        patch("builtins.open", mock_open()),
        patch("os.chmod"),
        patch("pathlib.Path.mkdir"),
    ):
        storage = KeyStorage(Path("wallet.json"))
        storage.create_account("master")  # Create master first
        storage.create_account("deployer")
        storage.create_account("owner")
        safe = storage.create_safe("deployer", ["owner"], 1, "gnosis", "safe")

        # Get by address
        acc = storage.get_account(safe.address)
        assert isinstance(acc, StoredSafeAccount)

        # Get by tag
        acc = storage.get_account("safe")
        assert isinstance(acc, StoredSafeAccount)


def test_keystorage_get_account_none(mock_secrets):
    with patch("os.path.exists", return_value=False):
        storage = KeyStorage(Path("wallet.json"))
        assert storage.get_account("0x5B38Da6a701c568545dCfcB03FcB875f56beddC4") is None
        assert storage.get_account("tag") is None


def test_keystorage_redeploy_safes(
    mock_secrets, mock_safe, mock_ethereum_client, mock_account, mock_aesgcm, mock_scrypt
):
    with (
        patch("os.path.exists", return_value=False),
        patch("builtins.open", mock_open()),
        patch("os.chmod"),
        patch("pathlib.Path.mkdir"),
    ):
        storage = KeyStorage(Path("wallet.json"))
        storage.create_account("master")  # Create master first
        storage.create_account("deployer")
        storage.create_account("owner")
        storage.create_safe("deployer", ["owner"], 1, "gnosis", "safe")

        # Mock get_code to return empty bytes (not deployed)
        mock_ethereum_client.return_value.w3.eth.get_code.return_value = b""

        # Patch create_safe on the CLASS or use a different approach
        with patch(
            "iwa.core.keys.KeyStorage.create_safe", wraps=storage.create_safe
        ) as mock_create_safe:
            storage.redeploy_safes()
            assert mock_create_safe.call_count > 0


def test_keystorage_redeploy_safes_already_deployed(
    mock_secrets, mock_safe, mock_ethereum_client, mock_account, mock_aesgcm, mock_scrypt
):
    with (
        patch("os.path.exists", return_value=False),
        patch("builtins.open", mock_open()),
        patch("os.chmod"),
        patch("pathlib.Path.mkdir"),
    ):
        storage = KeyStorage(Path("wallet.json"))
        storage.create_account("master")  # Create master first
        storage.create_account("deployer")
        storage.create_account("owner")
        storage.create_safe("deployer", ["owner"], 1, "gnosis", "safe")

        # Mock get_code to return code (deployed)
        mock_ethereum_client.return_value.w3.eth.get_code.return_value = b"code"

        with patch(
            "iwa.core.keys.KeyStorage.create_safe", wraps=storage.create_safe
        ) as mock_create_safe:
            storage.redeploy_safes()
            # Should NOT be called again (except the initial one we did manually, but mock was set up AFTER)
            mock_create_safe.assert_not_called()
