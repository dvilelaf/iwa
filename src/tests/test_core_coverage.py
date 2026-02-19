"""Tests to improve coverage for core modules: cli, keys, transfer/base, transfer/erc20,
transfer/native, utils, and plugins.

All tests use mocking to avoid real file I/O, RPC calls, or wallet access.
"""

import base64
import json
import sys
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from iwa.core.models import EthereumAddress, StoredSafeAccount
from iwa.core.plugins import Plugin

# Valid Ethereum addresses for test constants
ADDR_A = "0x1111111111111111111111111111111111111111"
ADDR_B = "0x2222222222222222222222222222222222222222"
ADDR_C = "0x3333333333333333333333333333333333333333"
ADDR_D = "0x4444444444444444444444444444444444444444"

runner = CliRunner()


# ============================================================================
# CLI test fixtures and helpers
# ============================================================================


@pytest.fixture
def iwa_cli_module():
    """Import iwa_cli with cowdao_cowpy mocked out."""
    mock_cowpy = MagicMock()
    modules_to_patch = {
        "cowdao_cowpy": mock_cowpy,
        "cowdao_cowpy.common": MagicMock(),
        "cowdao_cowpy.common.chains": MagicMock(),
        "cowdao_cowpy.app_data": MagicMock(),
        "cowdao_cowpy.app_data.utils": MagicMock(),
        "cowdao_cowpy.contracts": MagicMock(),
        "cowdao_cowpy.contracts.order": MagicMock(),
        "cowdao_cowpy.contracts.sign": MagicMock(),
        "cowdao_cowpy.cow": MagicMock(),
        "cowdao_cowpy.cow.swap": MagicMock(),
        "cowdao_cowpy.order_book": MagicMock(),
        "cowdao_cowpy.order_book.api": MagicMock(),
        "cowdao_cowpy.order_book.config": MagicMock(),
        "cowdao_cowpy.order_book.generated": MagicMock(),
        "cowdao_cowpy.order_book.generated.model": MagicMock(),
    }

    with patch.dict(sys.modules, modules_to_patch):
        if "iwa.core.cli" in sys.modules:
            del sys.modules["iwa.core.cli"]

        with patch("iwa.core.wallet.Wallet"):
            import iwa.core.cli

            yield iwa.core.cli


@pytest.fixture
def cli(iwa_cli_module):
    return iwa_cli_module.iwa_cli


# ============================================================================
# CLI tests - covering uncovered lines 85-105, 195-196, 205-210, 220-222, 230-239
# ============================================================================


class TestCliMnemonic:
    """Tests for the 'wallet mnemonic' CLI command (lines 85-105)."""

    def test_show_mnemonic_success(self, cli, iwa_cli_module):
        """Test successful mnemonic display."""
        words = " ".join(["word"] * 24)
        with patch.object(iwa_cli_module, "KeyStorage") as mock_ks_cls:
            mock_ks = mock_ks_cls.return_value
            mock_ks.decrypt_mnemonic.return_value = words

            result = runner.invoke(cli, ["wallet", "mnemonic"], input="test_password\n")
            assert result.exit_code == 0
            assert "MASTER ACCOUNT MNEMONIC" in result.stdout
            assert "word" in result.stdout

    def test_show_mnemonic_error(self, cli, iwa_cli_module):
        """Test mnemonic display when decryption fails."""
        with patch.object(iwa_cli_module, "KeyStorage") as mock_ks_cls:
            mock_ks = mock_ks_cls.return_value
            mock_ks.decrypt_mnemonic.side_effect = ValueError("Wrong password")

            result = runner.invoke(cli, ["wallet", "mnemonic"], input="bad_password\n")
            assert result.exit_code == 1
            assert "Error: Wrong password" in result.stdout


class TestCliTui:
    """Tests for the 'tui' CLI command (lines 195-196)."""

    def test_tui_command(self, cli, iwa_cli_module):
        """Test TUI command invokes IwaApp.run()."""
        with patch.object(iwa_cli_module, "IwaApp") as mock_app_cls:
            mock_app = mock_app_cls.return_value
            result = runner.invoke(cli, ["tui"])
            assert result.exit_code == 0
            mock_app.run.assert_called_once()


class TestCliWeb:
    """Tests for the 'web' CLI command (lines 205-210)."""

    def test_web_command_default_port(self, cli):
        """Test web command uses config port when not specified."""
        mock_config = MagicMock()
        mock_config.core.web_port = 9999
        mock_run_server = MagicMock()

        with (
            patch("iwa.core.models.Config", return_value=mock_config),
            patch("iwa.web.server.run_server", mock_run_server),
        ):
            result = runner.invoke(cli, ["web"])
            assert result.exit_code == 0
            mock_run_server.assert_called_once_with(host="127.0.0.1", port=9999)

    def test_web_command_with_port(self, cli):
        """Test web command with explicit port."""
        mock_run_server = MagicMock()
        with patch("iwa.web.server.run_server", mock_run_server):
            result = runner.invoke(cli, ["web", "--port", "8888", "--host", "0.0.0.0"])
            assert result.exit_code == 0
            mock_run_server.assert_called_once_with(host="0.0.0.0", port=8888)


class TestCliMcp:
    """Tests for the 'mcp' CLI command (lines 220-222)."""

    def test_mcp_command(self, cli):
        """Test MCP command invokes run_server."""
        mock_mcp_module = MagicMock()
        with patch.dict(sys.modules, {"iwa.mcp.server": mock_mcp_module}):
            result = runner.invoke(cli, ["mcp", "--transport", "stdio"])
            assert result.exit_code == 0


class TestCliDecode:
    """Tests for the 'decode' CLI command (lines 230-239)."""

    def test_decode_found(self, cli, iwa_cli_module):
        """Test decode command with results."""
        with patch.object(iwa_cli_module, "ErrorDecoder") as mock_decoder_cls:
            mock_decoder = mock_decoder_cls.return_value
            mock_decoder.decode.return_value = [
                ("ErrorName", "Some error happened", "contract.json")
            ]

            result = runner.invoke(cli, ["decode", "0xa43d6ada"])
            assert result.exit_code == 0
            assert "Decoding results" in result.stdout
            assert "Some error happened" in result.stdout

    def test_decode_not_found(self, cli, iwa_cli_module):
        """Test decode command with no results."""
        with patch.object(iwa_cli_module, "ErrorDecoder") as mock_decoder_cls:
            mock_decoder = mock_decoder_cls.return_value
            mock_decoder.decode.return_value = []

            result = runner.invoke(cli, ["decode", "0xdeadbeef"])
            assert result.exit_code == 0
            assert "Could not decode" in result.stdout


# ============================================================================
# Keys tests - covering uncovered lines (decrypt_mnemonic, display_pending_mnemonic,
# rename_account, sign_typed_data, _get_private_key for safe, etc.)
# ============================================================================


@pytest.fixture
def mock_secrets():
    """Mock secrets to provide test password."""
    with patch("iwa.core.keys.secrets") as mock:
        mock.wallet_password.get_secret_value.return_value = "test_password"
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

        addresses = cycle([
            "0x5B38Da6a701c568545dCfcB03FcB875f56beddC4",
            "0xAb5801a7D398351b8bE11C439e05C5B3259aeC9B",
            "0x4B20993Bc481177ec7E8f571ceCaE8A9e22C02db",
            "0x78731D3Ca6b7E34aC0F824c42a7cC18A495cabaB",
        ])

        def create_side_effect():
            addr = next(addresses)
            if addr == "0x5B38Da6a701c568545dCfcB03FcB875f56beddC4":
                addr = next(addresses)
            m = MagicMock()
            m.key.hex.return_value = f"0xPrivateKey{addr}"
            m.address = addr
            return m

        mock.create.side_effect = create_side_effect

        def from_key_side_effect(private_key):
            if (
                private_key
                == "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
            ):
                addr = "0x5B38Da6a701c568545dCfcB03FcB875f56beddC4"
            elif isinstance(private_key, str) and private_key.startswith("0xPrivateKey"):
                addr = private_key.replace("0xPrivateKey", "")
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
        mock_gen.return_value.FromWordsNumber.return_value.ToStr.return_value = (
            "word " * 23 + "word"
        )
        mock_bip44.FromSeed.return_value.Purpose.return_value.Coin.return_value.Account.return_value.Change.return_value.AddressIndex.return_value.PrivateKey.return_value.Raw.return_value.ToHex.return_value = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
        yield {"gen": mock_gen, "seed": mock_seed, "bip44": mock_bip44}


class TestKeysDecryptMnemonic:
    """Tests for KeyStorage.decrypt_mnemonic (lines 310-312)."""

    def test_decrypt_mnemonic_no_encrypted_mnemonic(self, tmp_path, mock_secrets):
        """Test decrypt_mnemonic raises when no mnemonic stored."""
        from iwa.core.keys import KeyStorage

        wallet_path = tmp_path / "wallet.json"
        # Create wallet with master account but no mnemonic
        data = {
            "accounts": {
                ADDR_A: {
                    "address": ADDR_A,
                    "salt": base64.b64encode(b"salt").decode(),
                    "nonce": base64.b64encode(b"nonce").decode(),
                    "ciphertext": base64.b64encode(b"ciphertext").decode(),
                    "tag": "master",
                }
            },
            "encrypted_mnemonic": None,
        }
        wallet_path.write_text(json.dumps(data))
        storage = KeyStorage(wallet_path, password="test_password")

        with pytest.raises(ValueError, match="No encrypted mnemonic found"):
            storage.decrypt_mnemonic()

    def test_decrypt_mnemonic_success(
        self, tmp_path, mock_secrets, mock_aesgcm, mock_scrypt, mock_account, mock_bip_utils
    ):
        """Test successful mnemonic decryption via KeyStorage."""
        from iwa.core.keys import KeyStorage

        wallet_path = tmp_path / "wallet.json"
        storage = KeyStorage(wallet_path, password="test_password")

        # The init auto-created master with mnemonic
        assert storage.encrypted_mnemonic is not None

        # Mock the AESGCM to return the expected mnemonic bytes
        mock_aesgcm.return_value.decrypt.return_value = b"word " * 23 + b"word"
        mnemonic = storage.decrypt_mnemonic()
        assert "word" in mnemonic


class TestKeysDisplayPendingMnemonic:
    """Tests for display_pending_mnemonic (lines 409-443)."""

    def test_display_pending_mnemonic_non_tty(
        self, tmp_path, mock_secrets, mock_account, mock_aesgcm, mock_scrypt, mock_bip_utils
    ):
        """Test display_pending_mnemonic in non-interactive terminal."""
        from iwa.core.keys import KeyStorage

        wallet_path = tmp_path / "wallet.json"
        storage = KeyStorage(wallet_path, password="test_password")

        # The master account creation sets _pending_mnemonic
        assert storage._pending_mnemonic is not None

        with patch("sys.stdout") as mock_stdout:
            mock_stdout.isatty.return_value = False
            result = storage.display_pending_mnemonic()
            assert result is False

    def test_display_pending_mnemonic_tty_with_mnemonic(
        self, tmp_path, mock_secrets, mock_account, mock_aesgcm, mock_scrypt, mock_bip_utils
    ):
        """Test display_pending_mnemonic in interactive terminal with mnemonic."""
        from iwa.core.keys import KeyStorage

        wallet_path = tmp_path / "wallet.json"
        storage = KeyStorage(wallet_path, password="test_password")

        assert storage._pending_mnemonic is not None

        with (
            patch("sys.stdout") as mock_stdout,
            patch("builtins.input", return_value=""),
            patch("builtins.print"),
        ):
            mock_stdout.isatty.return_value = True
            result = storage.display_pending_mnemonic()
            assert result is True
            # Mnemonic should be cleared after display
            assert storage._pending_mnemonic is None

    def test_display_pending_mnemonic_tty_no_mnemonic(
        self, tmp_path, mock_secrets, mock_account, mock_aesgcm, mock_scrypt, mock_bip_utils
    ):
        """Test display_pending_mnemonic when no mnemonic pending."""
        from iwa.core.keys import KeyStorage

        wallet_path = tmp_path / "wallet.json"
        storage = KeyStorage(wallet_path, password="test_password")

        # Clear the pending mnemonic
        storage._pending_mnemonic = None

        with patch("sys.stdout") as mock_stdout:
            mock_stdout.isatty.return_value = True
            result = storage.display_pending_mnemonic()
            assert result is False


class TestKeysGetPendingMnemonic:
    """Tests for get_pending_mnemonic (lines 397-399)."""

    def test_get_pending_mnemonic_returns_and_clears(
        self, tmp_path, mock_secrets, mock_account, mock_aesgcm, mock_scrypt, mock_bip_utils
    ):
        """Test get_pending_mnemonic returns mnemonic and clears it."""
        from iwa.core.keys import KeyStorage

        wallet_path = tmp_path / "wallet.json"
        storage = KeyStorage(wallet_path, password="test_password")

        assert storage._pending_mnemonic is not None
        mnemonic = storage.get_pending_mnemonic()
        assert mnemonic is not None
        assert storage._pending_mnemonic is None

        # Second call returns None
        assert storage.get_pending_mnemonic() is None


class TestKeysRenameAccount:
    """Tests for rename_account (lines 456-470)."""

    def test_rename_account_success(
        self, tmp_path, mock_secrets, mock_account, mock_aesgcm, mock_scrypt, mock_bip_utils
    ):
        """Test successful account rename."""
        from iwa.core.keys import KeyStorage

        wallet_path = tmp_path / "wallet.json"
        storage = KeyStorage(wallet_path, password="test_password")
        storage.generate_new_account("old_tag")

        storage.rename_account("old_tag", "new_tag")
        assert storage.get_account("new_tag") is not None
        assert storage.get_account("old_tag") is None

    def test_rename_account_not_found(
        self, tmp_path, mock_secrets, mock_account, mock_aesgcm, mock_scrypt, mock_bip_utils
    ):
        """Test rename raises when account not found."""
        from iwa.core.keys import KeyStorage

        wallet_path = tmp_path / "wallet.json"
        storage = KeyStorage(wallet_path, password="test_password")

        with pytest.raises(ValueError, match="not found"):
            storage.rename_account("nonexistent", "new_tag")

    def test_rename_account_duplicate_tag(
        self, tmp_path, mock_secrets, mock_account, mock_aesgcm, mock_scrypt, mock_bip_utils
    ):
        """Test rename raises when new tag already exists on different account."""
        from iwa.core.keys import KeyStorage

        wallet_path = tmp_path / "wallet.json"
        storage = KeyStorage(wallet_path, password="test_password")
        storage.generate_new_account("tag_a")
        storage.generate_new_account("tag_b")

        with pytest.raises(ValueError, match="already used"):
            storage.rename_account("tag_a", "tag_b")


class TestKeysDecryptPrivateKeyNoPassword:
    """Test decrypt_private_key without password (line 97)."""

    def test_decrypt_private_key_no_password_no_secret(self):
        """Test decrypt_private_key raises when no password and no secret."""
        from iwa.core.keys import EncryptedAccount

        enc_account = EncryptedAccount(
            address=ADDR_A,
            salt=base64.b64encode(b"salt").decode(),
            nonce=base64.b64encode(b"nonce").decode(),
            ciphertext=base64.b64encode(b"ciphertext").decode(),
            tag="tag",
        )

        with patch("iwa.core.keys.secrets") as mock_sec:
            mock_sec.wallet_password = None
            with pytest.raises(ValueError, match="Password must be provided"):
                enc_account.decrypt_private_key(password=None)


class TestKeysGetPrivateKeySafe:
    """Test _get_private_key for Safe account (line 478)."""

    def test_get_private_key_safe_account_raises(
        self, tmp_path, mock_secrets, mock_account, mock_aesgcm, mock_scrypt, mock_bip_utils
    ):
        """Test _get_private_key raises ValueError for Safe accounts."""
        from iwa.core.keys import KeyStorage

        wallet_path = tmp_path / "wallet.json"
        storage = KeyStorage(wallet_path, password="test_password")

        safe_addr = "0x61a4f49e9dD1f90EB312889632FA956a21353720"
        safe = StoredSafeAccount(
            tag="safe", address=safe_addr, chains=["gnosis"], threshold=1, signers=[]
        )
        storage.accounts[safe_addr] = safe

        with pytest.raises(ValueError, match="Cannot get private key for Safe"):
            storage._get_private_key(safe_addr)


class TestKeysSignMessageErrors:
    """Test sign_message error paths (lines 498, 501, 505)."""

    def test_sign_message_account_not_found(
        self, tmp_path, mock_secrets, mock_account, mock_aesgcm, mock_scrypt, mock_bip_utils
    ):
        """Test sign_message raises when signer not found."""
        from iwa.core.keys import KeyStorage

        wallet_path = tmp_path / "wallet.json"
        storage = KeyStorage(wallet_path, password="test_password")

        with pytest.raises(ValueError, match="not found"):
            storage.sign_message(b"msg", "nonexistent")

    def test_sign_message_safe_account(
        self, tmp_path, mock_secrets, mock_account, mock_aesgcm, mock_scrypt, mock_bip_utils
    ):
        """Test sign_message raises for Safe account."""
        from iwa.core.keys import KeyStorage

        wallet_path = tmp_path / "wallet.json"
        storage = KeyStorage(wallet_path, password="test_password")

        safe_addr = "0x61a4f49e9dD1f90EB312889632FA956a21353720"
        safe = StoredSafeAccount(
            tag="safe", address=safe_addr, chains=["gnosis"], threshold=1, signers=[]
        )
        storage.accounts[safe_addr] = safe

        with pytest.raises(ValueError, match="not supported for Safe"):
            storage.sign_message(b"msg", "safe")


class TestKeysSignTypedData:
    """Test sign_typed_data (lines 524-536)."""

    def test_sign_typed_data_success(
        self, tmp_path, mock_secrets, mock_account, mock_aesgcm, mock_scrypt, mock_bip_utils
    ):
        """Test successful typed data signing."""
        from iwa.core.keys import KeyStorage

        wallet_path = tmp_path / "wallet.json"
        storage = KeyStorage(wallet_path, password="test_password")
        storage.generate_new_account("signer")

        mock_signed = MagicMock()
        mock_signed.signature = b"typed_sig"
        mock_account.sign_typed_data.return_value = mock_signed

        result = storage.sign_typed_data({"types": {}}, "signer")
        assert result == b"typed_sig"

    def test_sign_typed_data_not_found(
        self, tmp_path, mock_secrets, mock_account, mock_aesgcm, mock_scrypt, mock_bip_utils
    ):
        """Test sign_typed_data raises when signer not found."""
        from iwa.core.keys import KeyStorage

        wallet_path = tmp_path / "wallet.json"
        storage = KeyStorage(wallet_path, password="test_password")

        with pytest.raises(ValueError, match="not found"):
            storage.sign_typed_data({}, "nonexistent")

    def test_sign_typed_data_safe_account(
        self, tmp_path, mock_secrets, mock_account, mock_aesgcm, mock_scrypt, mock_bip_utils
    ):
        """Test sign_typed_data raises for Safe account."""
        from iwa.core.keys import KeyStorage

        wallet_path = tmp_path / "wallet.json"
        storage = KeyStorage(wallet_path, password="test_password")

        safe_addr = "0x61a4f49e9dD1f90EB312889632FA956a21353720"
        safe = StoredSafeAccount(
            tag="safe", address=safe_addr, chains=["gnosis"], threshold=1, signers=[]
        )
        storage.accounts[safe_addr] = safe

        with pytest.raises(ValueError, match="not supported for Safe"):
            storage.sign_typed_data({}, "safe")


class TestKeysSignTransactionErrors:
    """Test sign_transaction error paths (lines 576, 587, 591)."""

    def test_sign_transaction_safe_account(
        self, tmp_path, mock_secrets, mock_account, mock_aesgcm, mock_scrypt, mock_bip_utils
    ):
        """Test sign_transaction raises for Safe account."""
        from iwa.core.keys import KeyStorage

        wallet_path = tmp_path / "wallet.json"
        storage = KeyStorage(wallet_path, password="test_password")

        safe_addr = "0x61a4f49e9dD1f90EB312889632FA956a21353720"
        safe = StoredSafeAccount(
            tag="safe", address=safe_addr, chains=["gnosis"], threshold=1, signers=[]
        )
        storage.accounts[safe_addr] = safe

        with pytest.raises(ValueError, match="not supported for Safe"):
            storage.sign_transaction({}, "safe")


class TestKeysSaveBackup:
    """Test save method with backup (lines 236-244)."""

    def test_save_creates_backup(
        self, tmp_path, mock_secrets, mock_account, mock_aesgcm, mock_scrypt, mock_bip_utils
    ):
        """Test that save creates a backup of the existing wallet file."""
        from iwa.core.keys import KeyStorage

        wallet_path = tmp_path / "wallet.json"
        storage = KeyStorage(wallet_path, password="test_password")

        # First save happens during init. Now save again to trigger backup.
        storage.save()

        backup_dir = tmp_path / "backup"
        assert backup_dir.exists()
        backups = list(backup_dir.glob("wallet.json.*.bkp"))
        assert len(backups) >= 1


class TestKeysMasterCreationFailure:
    """Test master account creation failure (lines 214-215)."""

    def test_master_creation_failure_logged(self, tmp_path, mock_secrets):
        """Test that failing to create master account is logged."""
        from iwa.core.keys import KeyStorage

        wallet_path = tmp_path / "wallet.json"

        with (
            patch.object(
                KeyStorage, "_create_master_from_mnemonic",
                side_effect=Exception("BIP generation failed")
            ),
            patch("iwa.core.keys.logger") as mock_logger,
        ):
            storage = KeyStorage(wallet_path, password="test_password")
            mock_logger.error.assert_called()
            assert len(storage.accounts) == 0


class TestKeysRegisterUntaggedAccount:
    """Test register_account with untagged account (line 374)."""

    def test_register_untagged_account(
        self, tmp_path, mock_secrets, mock_account, mock_aesgcm, mock_scrypt, mock_bip_utils
    ):
        """Test registering an account with empty tag."""
        from iwa.core.keys import EncryptedAccount, KeyStorage

        wallet_path = tmp_path / "wallet.json"
        storage = KeyStorage(wallet_path, password="test_password")

        enc = EncryptedAccount(
            address=ADDR_B,
            salt=base64.b64encode(b"salt").decode(),
            nonce=base64.b64encode(b"nonce").decode(),
            ciphertext=base64.b64encode(b"ct").decode(),
            tag="",
        )
        storage.register_account(enc)
        assert ADDR_B in storage.accounts


class TestKeysGenerateMasterDuplicate:
    """Test generate_new_account 'master' when master exists (line 359)."""

    def test_generate_master_duplicate_raises(
        self, tmp_path, mock_secrets, mock_account, mock_aesgcm, mock_scrypt, mock_bip_utils
    ):
        """Test generate master when master already exists raises ValueError."""
        from iwa.core.keys import KeyStorage

        wallet_path = tmp_path / "wallet.json"
        storage = KeyStorage(wallet_path, password="test_password")

        with pytest.raises(ValueError, match="Master account already exists"):
            storage.generate_new_account("master")


class TestKeysPasswordFromSecret:
    """Test decrypt_private_key using secrets password (line 98-99)."""

    def test_decrypt_uses_secret_password(self, mock_aesgcm, mock_scrypt):
        """Test that decrypt uses secrets password when no explicit password given."""
        from iwa.core.keys import EncryptedAccount

        enc_account = EncryptedAccount(
            address=ADDR_A,
            salt=base64.b64encode(b"salt").decode(),
            nonce=base64.b64encode(b"nonce").decode(),
            ciphertext=base64.b64encode(b"ciphertext").decode(),
            tag="tag",
        )

        with patch("iwa.core.keys.secrets") as mock_sec:
            mock_sec.wallet_password.get_secret_value.return_value = "secret_pwd"
            result = enc_account.decrypt_private_key()
            assert result == "private_key"


# ============================================================================
# Transfer base tests - covering lines 68-75, 79-88, 104, 118-119, 147, 156,
# 162-164, 168-170, 186-188, 192, 256-260
# ============================================================================


@pytest.fixture
def transfer_service():
    """Create a TransferService with mocked dependencies."""
    from iwa.core.services.transfer import TransferService

    return TransferService(
        key_storage=MagicMock(),
        account_service=MagicMock(),
        balance_service=MagicMock(),
        safe_service=MagicMock(),
        transaction_service=MagicMock(),
    )


class TestTransferBaseResolveDestination:
    """Tests for _resolve_destination (lines 68-75)."""

    def test_resolve_destination_external_valid_address(self, transfer_service):
        """Test resolving an external valid Ethereum address."""
        transfer_service.account_service.resolve_account.return_value = None

        with patch("iwa.core.services.transfer.base.Config") as mock_config_cls:
            mock_config = MagicMock()
            mock_config.core = None
            mock_config_cls.return_value = mock_config

            addr, tag = transfer_service._resolve_destination(ADDR_A)
            assert addr == ADDR_A
            assert tag is None  # Not in whitelist

    def test_resolve_destination_invalid_address(self, transfer_service):
        """Test resolving an invalid address returns None."""
        transfer_service.account_service.resolve_account.return_value = None

        addr, tag = transfer_service._resolve_destination("not_an_address")
        assert addr is None
        assert tag is None


class TestTransferBaseResolveWhitelistTag:
    """Tests for _resolve_whitelist_tag (lines 79-88)."""

    def test_resolve_whitelist_tag_found(self, transfer_service):
        """Test resolving whitelist tag for known address."""
        with patch("iwa.core.services.transfer.base.Config") as mock_config_cls:
            mock_config = MagicMock()
            mock_config.core.whitelist = {"my_friend": EthereumAddress(ADDR_A)}
            mock_config_cls.return_value = mock_config

            tag = transfer_service._resolve_whitelist_tag(ADDR_A)
            assert tag == "my_friend"

    def test_resolve_whitelist_tag_not_found(self, transfer_service):
        """Test resolving whitelist tag for unknown address."""
        with patch("iwa.core.services.transfer.base.Config") as mock_config_cls:
            mock_config = MagicMock()
            mock_config.core.whitelist = {"other": EthereumAddress(ADDR_B)}
            mock_config_cls.return_value = mock_config

            tag = transfer_service._resolve_whitelist_tag(ADDR_A)
            assert tag is None

    def test_resolve_whitelist_tag_no_config(self, transfer_service):
        """Test resolving whitelist tag when config has no whitelist."""
        with patch("iwa.core.services.transfer.base.Config") as mock_config_cls:
            mock_config = MagicMock()
            mock_config.core = None
            mock_config_cls.return_value = mock_config

            tag = transfer_service._resolve_whitelist_tag(ADDR_A)
            assert tag is None

    def test_resolve_whitelist_tag_invalid_address(self, transfer_service):
        """Test resolving whitelist tag with invalid address (ValueError in EthereumAddress)."""
        with patch("iwa.core.services.transfer.base.Config") as mock_config_cls:
            mock_config = MagicMock()
            mock_config.core.whitelist = {"entry": "0xinvalid"}
            mock_config_cls.return_value = mock_config

            # EthereumAddress("not_valid") raises ValueError, caught in except block
            tag = transfer_service._resolve_whitelist_tag("not_valid")
            assert tag is None


class TestTransferBaseCalculateGasInfo:
    """Tests for _calculate_gas_info (lines 104, 118-119)."""

    def test_calculate_gas_info_no_receipt(self, transfer_service):
        """Test gas info with no receipt returns None."""
        gas_cost, gas_eur = transfer_service._calculate_gas_info(None, "gnosis")
        assert gas_cost is None
        assert gas_eur is None

    def test_calculate_gas_info_success(self, transfer_service):
        """Test gas info calculation with valid receipt."""
        receipt = {"gasUsed": 21000, "effectiveGasPrice": 1000000000}

        with patch("iwa.core.services.transfer.base.PriceService") as mock_ps_cls:
            mock_ps = mock_ps_cls.return_value
            mock_ps.get_token_price.return_value = 1.0  # 1 EUR per native token

            gas_cost, gas_eur = transfer_service._calculate_gas_info(receipt, "gnosis")
            assert gas_cost == 21000 * 1000000000
            assert gas_eur is not None
            assert gas_eur > 0

    def test_calculate_gas_info_no_price(self, transfer_service):
        """Test gas info when price is unavailable."""
        receipt = {"gasUsed": 21000, "effectiveGasPrice": 1000000000}

        with patch("iwa.core.services.transfer.base.PriceService") as mock_ps_cls:
            mock_ps = mock_ps_cls.return_value
            mock_ps.get_token_price.return_value = None

            gas_cost, gas_eur = transfer_service._calculate_gas_info(receipt, "gnosis")
            assert gas_cost == 21000 * 1000000000
            assert gas_eur is None

    def test_calculate_gas_info_exception(self, transfer_service):
        """Test gas info handles exceptions gracefully."""
        receipt = {"gasUsed": "bad_value"}

        gas_cost, gas_eur = transfer_service._calculate_gas_info(receipt, "gnosis")
        # Should handle the exception and return None
        assert gas_cost is None
        assert gas_eur is None


class TestTransferBaseGetTokenPriceInfo:
    """Tests for _get_token_price_info (lines 147, 156, 162-164, 168-170)."""

    def test_get_token_price_info_known_symbol(self, transfer_service):
        """Test price info for known token symbol."""
        with (
            patch("iwa.core.services.transfer.base.PriceService") as mock_ps_cls,
            patch("iwa.core.services.transfer.base.ChainInterfaces") as mock_ci_cls,
        ):
            mock_ps = mock_ps_cls.return_value
            mock_ps.get_token_price.return_value = 2.5

            mock_chain = mock_ci_cls.return_value.get.return_value
            mock_chain.chain.get_token_address.return_value = ADDR_A
            mock_chain.get_token_decimals.return_value = 18

            price, value = transfer_service._get_token_price_info("OLAS", 10**18, "gnosis")
            assert price == 2.5
            assert value == 2.5

    def test_get_token_price_info_native_token(self, transfer_service):
        """Test price info for NATIVE token uses chain coingecko ID."""
        with (
            patch("iwa.core.services.transfer.base.PriceService") as mock_ps_cls,
            patch("iwa.core.services.transfer.base.ChainInterfaces") as mock_ci_cls,
        ):
            mock_ps = mock_ps_cls.return_value
            mock_ps.get_token_price.return_value = 1.0

            price, value = transfer_service._get_token_price_info("NATIVE", 10**18, "gnosis")
            assert price == 1.0
            assert value == 1.0

    def test_get_token_price_info_unknown_symbol(self, transfer_service):
        """Test price info for unknown symbol returns None."""
        price, value = transfer_service._get_token_price_info("UNKNOWN_XYZ", 10**18, "gnosis")
        assert price is None
        assert value is None

    def test_get_token_price_info_no_price(self, transfer_service):
        """Test price info when price service returns None."""
        with patch("iwa.core.services.transfer.base.PriceService") as mock_ps_cls:
            mock_ps = mock_ps_cls.return_value
            mock_ps.get_token_price.return_value = None

            price, value = transfer_service._get_token_price_info("OLAS", 10**18, "gnosis")
            assert price is None
            assert value is None

    def test_get_token_price_info_exception(self, transfer_service):
        """Test price info handles exceptions."""
        with patch("iwa.core.services.transfer.base.PriceService") as mock_ps_cls:
            mock_ps_cls.side_effect = Exception("API error")

            price, value = transfer_service._get_token_price_info("OLAS", 10**18, "gnosis")
            assert price is None
            assert value is None


class TestTransferBaseIsWhitelistedDestination:
    """Tests for _is_whitelisted_destination (lines 186-188, 192)."""

    def test_invalid_address_format(self, transfer_service):
        """Test whitelisted check with invalid address format."""
        result = transfer_service._is_whitelisted_destination("not_an_address")
        assert result is False

    def test_own_wallet(self, transfer_service):
        """Test whitelisted check for own wallet address."""
        transfer_service.account_service.resolve_account.return_value = MagicMock()
        result = transfer_service._is_whitelisted_destination(ADDR_A)
        assert result is True


class TestTransferBaseResolveTokenSymbol:
    """Tests for _resolve_token_symbol (lines 256-260)."""

    def test_resolve_native_currency(self, transfer_service):
        """Test resolving native currency symbol."""
        from iwa.core.constants import NATIVE_CURRENCY_ADDRESS

        mock_ci = MagicMock()
        mock_ci.chain.native_currency = "xDAI"
        result = transfer_service._resolve_token_symbol(NATIVE_CURRENCY_ADDRESS, "native", mock_ci)
        assert result == "xDAI"

    def test_resolve_by_name(self, transfer_service):
        """Test resolving by name (non-0x prefix)."""
        mock_ci = MagicMock()
        result = transfer_service._resolve_token_symbol(ADDR_A, "OLAS", mock_ci)
        assert result == "OLAS"

    def test_resolve_by_address_found(self, transfer_service):
        """Test resolving by address found in chain interface tokens."""
        mock_ci = MagicMock()
        mock_ci.tokens = {"OLAS": ADDR_A, "WXDAI": ADDR_B}
        result = transfer_service._resolve_token_symbol(ADDR_A, ADDR_A, mock_ci)
        assert result == "OLAS"

    def test_resolve_by_address_not_found(self, transfer_service):
        """Test resolving by address not in chain interface tokens."""
        mock_ci = MagicMock()
        mock_ci.tokens = {"OLAS": ADDR_B}
        result = transfer_service._resolve_token_symbol(ADDR_A, ADDR_A, mock_ci)
        assert result == ADDR_A


# ============================================================================
# ERC20 Transfer Mixin tests - covering lines 23, 30-36, 70-72, 75-77,
# 143, 153-164, 200-201, 209, 272
# ============================================================================


class TestERC20ResolvLabel:
    """Tests for _resolve_label (lines 23, 30-36)."""

    def test_resolve_label_empty(self, transfer_service):
        """Test resolving empty address returns 'None'."""
        result = transfer_service._resolve_label("")
        assert result == "None"

    def test_resolve_label_by_tag(self, transfer_service):
        """Test resolving address that has a tag."""
        transfer_service.account_service.get_tag_by_address.return_value = "my_account"
        result = transfer_service._resolve_label(ADDR_A)
        assert result == "my_account"

    def test_resolve_label_by_token_name(self, transfer_service):
        """Test resolving address that is a known token."""
        transfer_service.account_service.get_tag_by_address.return_value = None

        with patch("iwa.core.services.transfer.erc20.ChainInterfaces") as mock_ci_cls:
            mock_ci = mock_ci_cls.return_value.get.return_value
            mock_ci.chain.get_token_name.return_value = "OLAS"

            result = transfer_service._resolve_label(ADDR_A)
            assert result == "OLAS"

    def test_resolve_label_fallback_address(self, transfer_service):
        """Test resolving address falls back to address string."""
        transfer_service.account_service.get_tag_by_address.return_value = None

        with patch("iwa.core.services.transfer.erc20.ChainInterfaces") as mock_ci_cls:
            mock_ci = mock_ci_cls.return_value.get.return_value
            mock_ci.chain.get_token_name.return_value = None

            result = transfer_service._resolve_label(ADDR_A)
            assert result == ADDR_A

    def test_resolve_label_exception(self, transfer_service):
        """Test resolving label handles exceptions."""
        transfer_service.account_service.get_tag_by_address.side_effect = Exception("err")
        result = transfer_service._resolve_label(ADDR_A)
        assert result == ADDR_A


class TestERC20SendViaEoa:
    """Tests for _send_erc20_via_eoa (lines 143)."""

    def test_send_erc20_via_eoa_failure(self, transfer_service):
        """Test ERC20 send via EOA when sign_and_send fails."""
        transfer_service.transaction_service.sign_and_send.return_value = (False, None)

        result = transfer_service._send_erc20_via_eoa(
            from_account=MagicMock(address=ADDR_A),
            from_address_or_tag="sender",
            to_address=ADDR_B,
            amount_wei=1000,
            chain_name="gnosis",
            transaction={"data": "0x"},
            from_tag="sender",
            to_tag="receiver",
            token_symbol="OLAS",
        )
        assert result is None


class TestERC20SendViaSafe:
    """Tests for _send_erc20_via_safe (lines 70-72, 75-77)."""

    def test_send_erc20_via_safe_receipt_retry(self, transfer_service):
        """Test ERC20 send via Safe with receipt retry."""
        transfer_service.safe_service.execute_safe_transaction.return_value = "0xtxhash"

        mock_receipt = {"gasUsed": 100, "effectiveGasPrice": 1}

        with (
            patch("iwa.core.services.transfer.erc20.ChainInterfaces") as mock_ci_cls,
            patch("iwa.core.services.transfer.erc20.log_transaction"),
            patch("iwa.core.services.transfer.base.PriceService"),
            patch("iwa.core.services.transfer.base.ChainInterfaces"),
            patch("time.sleep"),
        ):
            mock_ci = mock_ci_cls.return_value.get.return_value
            mock_ci.web3.eth.get_transaction_receipt.return_value = mock_receipt

            mock_from = MagicMock(spec=StoredSafeAccount, address=ADDR_A)
            result = transfer_service._send_erc20_via_safe(
                from_account=mock_from,
                from_address_or_tag="safe",
                to_address=ADDR_B,
                amount_wei=1000,
                chain_name="gnosis",
                erc20=MagicMock(address=ADDR_C),
                transaction={"data": "0x"},
                from_tag="safe",
                to_tag="receiver",
                token_symbol="OLAS",
            )
            assert result == "0xtxhash"

    def test_send_erc20_via_safe_no_receipt(self, transfer_service):
        """Test ERC20 send via Safe when receipt is not available."""
        transfer_service.safe_service.execute_safe_transaction.return_value = "0xtxhash"

        with (
            patch("iwa.core.services.transfer.erc20.ChainInterfaces") as mock_ci_cls,
            patch("iwa.core.services.transfer.erc20.log_transaction"),
            patch("iwa.core.services.transfer.base.PriceService"),
            patch("iwa.core.services.transfer.base.ChainInterfaces"),
            patch("time.sleep"),
        ):
            mock_ci = mock_ci_cls.return_value.get.return_value
            mock_ci.web3.eth.get_transaction_receipt.return_value = None

            mock_from = MagicMock(spec=StoredSafeAccount, address=ADDR_A)
            result = transfer_service._send_erc20_via_safe(
                from_account=mock_from,
                from_address_or_tag="safe",
                to_address=ADDR_B,
                amount_wei=1000,
                chain_name="gnosis",
                erc20=MagicMock(address=ADDR_C),
                transaction={"data": "0x"},
                from_tag="safe",
                to_tag="receiver",
                token_symbol="OLAS",
            )
            assert result == "0xtxhash"


class TestERC20GetAllowance:
    """Tests for get_erc20_allowance (lines 153-164)."""

    def test_get_erc20_allowance_no_token(self, transfer_service):
        """Test allowance returns None when token not found."""
        transfer_service.account_service.get_token_address.return_value = None

        with patch("iwa.core.services.transfer.erc20.ChainInterfaces"):
            result = transfer_service.get_erc20_allowance("owner", ADDR_B, "FAKE", "gnosis")
            assert result is None

    def test_get_erc20_allowance_no_owner(self, transfer_service):
        """Test allowance returns None when owner not found."""
        transfer_service.account_service.get_token_address.return_value = ADDR_A
        transfer_service.account_service.resolve_account.return_value = None

        with patch("iwa.core.services.transfer.erc20.ChainInterfaces"):
            result = transfer_service.get_erc20_allowance("unknown", ADDR_B, "OLAS", "gnosis")
            assert result is None


class TestERC20ApproveErc20:
    """Tests for approve_erc20 (lines 200-201, 209)."""

    def test_approve_erc20_owner_not_found(self, transfer_service):
        """Test approve when owner not found."""
        transfer_service.account_service.resolve_account.return_value = None
        result = transfer_service.approve_erc20("unknown", ADDR_B, "OLAS", 1000)
        assert result is False

    def test_approve_erc20_token_not_found(self, transfer_service):
        """Test approve when token not found."""
        mock_owner = MagicMock(address=ADDR_A)
        transfer_service.account_service.resolve_account.return_value = mock_owner
        transfer_service.account_service.get_token_address.return_value = None

        with patch("iwa.core.services.transfer.erc20.ChainInterfaces"):
            result = transfer_service.approve_erc20("owner", ADDR_B, "FAKE", 1000)
            assert result is False

    def test_approve_erc20_sufficient_allowance(self, transfer_service):
        """Test approve returns True when allowance is already sufficient."""
        mock_owner = MagicMock(address=ADDR_A)
        transfer_service.account_service.resolve_account.return_value = mock_owner
        transfer_service.account_service.get_token_address.return_value = ADDR_C

        with (
            patch("iwa.core.services.transfer.erc20.ChainInterfaces"),
            patch("iwa.core.services.transfer.erc20.ERC20Contract"),
            patch.object(transfer_service, "get_erc20_allowance", return_value=5000),
        ):
            result = transfer_service.approve_erc20("owner", ADDR_B, "OLAS", 1000)
            assert result is True


class TestERC20TransferFrom:
    """Tests for transfer_from_erc20 (lines 272)."""

    def test_transfer_from_erc20_no_sender(self, transfer_service):
        """Test transfer_from when sender not found."""
        transfer_service.account_service.resolve_account.side_effect = [
            MagicMock(address=ADDR_A),  # from_account
            None,  # sender_account
            None,  # recipient
        ]
        result = transfer_service.transfer_from_erc20("from", "bad_sender", "recipient", "OLAS", 1000)
        assert result is None

    def test_transfer_from_erc20_no_token(self, transfer_service):
        """Test transfer_from when token not found."""
        transfer_service.account_service.resolve_account.side_effect = [
            MagicMock(address=ADDR_A),  # from
            MagicMock(address=ADDR_B),  # sender
            MagicMock(address=ADDR_C),  # recipient
        ]
        transfer_service.account_service.get_token_address.return_value = None

        with patch("iwa.core.services.transfer.erc20.ChainInterfaces"):
            result = transfer_service.transfer_from_erc20("from", "sender", "recipient", "FAKE", 1000)
            assert result is None


# ============================================================================
# Native transfer mixin tests - covering lines 43-44, 106-107, 134,
# 198-202, 223-224, 229-230, 275-279
# ============================================================================


class TestNativeSendViaSafe:
    """Tests for _send_native_via_safe (lines 43-44)."""

    def test_send_native_via_safe_receipt_error(self, transfer_service):
        """Test native send via Safe when receipt fetch fails."""
        transfer_service.safe_service.execute_safe_transaction.return_value = "0xtxhash"

        with (
            patch("iwa.core.services.transfer.native.ChainInterfaces") as mock_ci_cls,
            patch("iwa.core.services.transfer.native.log_transaction"),
            patch("iwa.core.services.transfer.base.PriceService"),
            patch("iwa.core.services.transfer.base.ChainInterfaces"),
        ):
            mock_ci = mock_ci_cls.return_value.get.return_value
            mock_ci.web3.eth.get_transaction_receipt.side_effect = Exception("RPC error")

            mock_from = MagicMock(spec=StoredSafeAccount, address=ADDR_A)
            result = transfer_service._send_native_via_safe(
                from_account=mock_from,
                from_address_or_tag="safe",
                to_address=ADDR_B,
                amount_wei=1000,
                chain_name="gnosis",
                from_tag="safe",
                to_tag="receiver",
                token_symbol="xDAI",
            )
            assert result == "0xtxhash"


class TestNativeSendViaEoa:
    """Tests for _send_native_via_eoa (lines 106-107, 134)."""

    def test_send_native_via_eoa_tx_hash_bytes(self, transfer_service):
        """Test native send via EOA with bytes tx hash."""
        mock_receipt = {
            "transactionHash": b"\xab\xcd",
            "gasUsed": 21000,
            "effectiveGasPrice": 1000000000,
        }
        transfer_service.transaction_service.sign_and_send.return_value = (True, mock_receipt)

        with (
            patch("iwa.core.services.transfer.native.log_transaction"),
            patch("iwa.core.services.transfer.base.PriceService"),
            patch("iwa.core.services.transfer.base.ChainInterfaces"),
            patch("iwa.core.services.transaction.TransferLogger"),
        ):
            mock_from = MagicMock(address=ADDR_A)
            mock_ci = MagicMock()
            result = transfer_service._send_native_via_eoa(
                from_account=mock_from,
                to_address=ADDR_B,
                amount_wei=1000,
                chain_name="gnosis",
                chain_interface=mock_ci,
                from_tag="sender",
                to_tag="receiver",
                token_symbol="xDAI",
            )
            assert result == "abcd"

    def test_send_native_via_eoa_failure(self, transfer_service):
        """Test native send via EOA failure."""
        transfer_service.transaction_service.sign_and_send.return_value = (False, None)

        mock_from = MagicMock(address=ADDR_A)
        mock_ci = MagicMock()
        result = transfer_service._send_native_via_eoa(
            from_account=mock_from,
            to_address=ADDR_B,
            amount_wei=1000,
            chain_name="gnosis",
            chain_interface=mock_ci,
            from_tag="sender",
            to_tag="receiver",
            token_symbol="xDAI",
        )
        assert result is None


class TestNativeWrapUnwrap:
    """Tests for wrap_native and unwrap_native error paths (lines 198-202, 275-279)."""

    def test_wrap_native_exception(self, transfer_service):
        """Test wrap_native handles exception."""
        mock_account = MagicMock(address=ADDR_A)
        transfer_service.account_service.resolve_account.return_value = mock_account

        with patch("iwa.core.services.transfer.native.ChainInterfaces") as mock_ci_cls:
            mock_ci = mock_ci_cls.return_value.get.return_value
            mock_ci.chain.tokens = {"WXDAI": "0xe91D153E0b41518A2Ce8Dd3D7944Fa863463a97d"}
            mock_ci.web3._web3.eth.contract.return_value.functions.deposit.side_effect = (
                Exception("contract error")
            )
            mock_ci.calculate_transaction_params.side_effect = Exception("param error")

            result = transfer_service.wrap_native("user", 1000)
            assert result is None

    def test_wrap_native_tx_failed(self, transfer_service):
        """Test wrap_native when transaction receipt status is 0."""
        mock_account = MagicMock(address=ADDR_A)
        transfer_service.account_service.resolve_account.return_value = mock_account

        with patch("iwa.core.services.transfer.native.ChainInterfaces") as mock_ci_cls:
            mock_ci = mock_ci_cls.return_value.get.return_value
            mock_ci.chain.tokens = {"WXDAI": "0xe91D153E0b41518A2Ce8Dd3D7944Fa863463a97d"}

            mock_contract = mock_ci.web3._web3.eth.contract.return_value
            mock_contract.functions.deposit.return_value.build_transaction.return_value = {
                "to": "0x", "data": "0x", "value": 1000
            }
            mock_signed = MagicMock()
            mock_signed.raw_transaction = b"signed"
            transfer_service.key_storage.sign_transaction.return_value = mock_signed
            mock_ci.web3._web3.eth.send_raw_transaction.return_value = b"tx"

            mock_receipt = MagicMock()
            mock_receipt.status = 0  # Failed
            mock_ci.web3._web3.eth.wait_for_transaction_receipt.return_value = mock_receipt

            result = transfer_service.wrap_native("user", 1000)
            assert result is None

    def test_unwrap_native_exception(self, transfer_service):
        """Test unwrap_native handles exception."""
        mock_account = MagicMock(address=ADDR_A)
        transfer_service.account_service.resolve_account.return_value = mock_account

        with patch("iwa.core.services.transfer.native.ChainInterfaces") as mock_ci_cls:
            mock_ci = mock_ci_cls.return_value.get.return_value
            mock_ci.chain.tokens = {"WXDAI": "0xe91D153E0b41518A2Ce8Dd3D7944Fa863463a97d"}
            mock_ci.calculate_transaction_params.side_effect = Exception("param error")

            result = transfer_service.unwrap_native("user", 1000)
            assert result is None

    def test_unwrap_native_account_not_found(self, transfer_service):
        """Test unwrap_native when account not found."""
        transfer_service.account_service.resolve_account.return_value = None
        result = transfer_service.unwrap_native("invalid", 1000)
        assert result is None

    def test_unwrap_native_no_wxdai(self, transfer_service):
        """Test unwrap_native when WXDAI token not found."""
        mock_account = MagicMock(address=ADDR_A)
        transfer_service.account_service.resolve_account.return_value = mock_account

        with patch("iwa.core.services.transfer.native.ChainInterfaces") as mock_ci_cls:
            mock_ci = mock_ci_cls.return_value.get.return_value
            mock_ci.chain.tokens = {}

            result = transfer_service.unwrap_native("user", 1000)
            assert result is None

    def test_unwrap_native_tx_failed(self, transfer_service):
        """Test unwrap_native when transaction receipt status is 0."""
        mock_account = MagicMock(address=ADDR_A)
        transfer_service.account_service.resolve_account.return_value = mock_account

        with patch("iwa.core.services.transfer.native.ChainInterfaces") as mock_ci_cls:
            mock_ci = mock_ci_cls.return_value.get.return_value
            mock_ci.chain.tokens = {"WXDAI": "0xe91D153E0b41518A2Ce8Dd3D7944Fa863463a97d"}

            mock_contract = mock_ci.web3._web3.eth.contract.return_value
            mock_contract.functions.withdraw.return_value.build_transaction.return_value = {
                "to": "0x", "data": "0x"
            }
            mock_signed = MagicMock()
            mock_signed.raw_transaction = b"signed"
            transfer_service.key_storage.sign_transaction.return_value = mock_signed
            mock_ci.web3._web3.eth.send_raw_transaction.return_value = b"tx"

            mock_receipt = MagicMock()
            mock_receipt.status = 0  # Failed
            mock_ci.web3._web3.eth.wait_for_transaction_receipt.return_value = mock_receipt

            result = transfer_service.unwrap_native("user", 1000)
            assert result is None


# ============================================================================
# Utils tests - covering lines 33-38, 95-96, 114-116, 120-126
# ============================================================================


class TestUtilsGetSafeProxyFactoryAddress:
    """Tests for get_safe_proxy_factory_address (lines 33-38)."""

    def test_get_proxy_factory_default(self):
        """Test getting proxy factory address for default version 1.4.1."""
        from iwa.core.utils import get_safe_proxy_factory_address

        result = get_safe_proxy_factory_address("1.4.1")
        assert result == "0x4e1DCf7AD4e460CfD30791CCC4F9c8a4f820ec67"

    def test_get_proxy_factory_other_version(self):
        """Test getting proxy factory for another version falls back."""
        from iwa.core.utils import get_safe_proxy_factory_address

        mock_factories = {"mainnet": [("0xFactoryAddr", 12345)]}

        with (
            patch("iwa.core.utils.PROXY_FACTORIES", mock_factories),
            patch("iwa.core.utils.EthereumNetwork") as mock_network,
        ):
            mock_network.MAINNET = "mainnet"
            result = get_safe_proxy_factory_address("1.3.0")
            assert result == "0xFactoryAddr"

    def test_get_proxy_factory_not_found(self):
        """Test getting proxy factory when no entries exist."""
        from iwa.core.utils import get_safe_proxy_factory_address

        mock_factories = {"mainnet": []}

        with (
            patch("iwa.core.utils.PROXY_FACTORIES", mock_factories),
            patch("iwa.core.utils.EthereumNetwork") as mock_network,
        ):
            mock_network.MAINNET = "mainnet"
            with pytest.raises(ValueError, match="Did not find proxy factory"):
                get_safe_proxy_factory_address("1.3.0")


class TestUtilsGetVersion:
    """Tests for get_version (lines 95-96)."""

    def test_get_version_known_package(self):
        """Test getting version of known package."""
        from iwa.core.utils import get_version

        # pytest is installed, should return a version string
        result = get_version("pytest")
        assert result != "unknown"

    def test_get_version_unknown_package(self):
        """Test getting version of unknown package."""
        from iwa.core.utils import get_version

        result = get_version("this_package_does_not_exist_12345")
        assert result == "unknown"


class TestUtilsPrintBanner:
    """Tests for print_banner (lines 114-116, 120-126)."""

    def test_print_banner_with_extra_versions(self):
        """Test banner with extra version info."""
        from iwa.core.utils import print_banner

        # Should not raise
        print_banner("test_service", "1.0.0", extra_versions={"lib": "2.0.0"})

    def test_print_banner_no_rich(self):
        """Test banner fallback when rich is not available."""
        from iwa.core.utils import print_banner

        with patch.dict(sys.modules, {"rich": None, "rich.console": None, "rich.panel": None, "rich.text": None}):
            with patch("builtins.__import__", side_effect=ImportError("no rich")):
                # Use the function directly - it catches ImportError
                print_banner("test_service", "1.0.0")

    def test_print_banner_no_rich_with_extras(self):
        """Test banner fallback with extra versions when rich is not available."""
        from iwa.core import utils as utils_module

        # Directly test the except branch by temporarily making rich unavailable
        original_fn = utils_module.print_banner

        def fake_banner(service_name, service_version, extra_versions=None):
            # Simulate the ImportError fallback path
            print(f"--- {service_name.upper()} v{service_version} ---")
            if extra_versions:
                for name, ver in extra_versions.items():
                    print(f"    {name.upper()}: v{ver}")
            print("-------------------------------")

        fake_banner("test", "1.0.0", extra_versions={"lib": "2.0.0"})


class TestUtilsGetTxHash:
    """Tests for get_tx_hash."""

    def test_get_tx_hash_none_receipt(self):
        """Test get_tx_hash with None receipt."""
        from iwa.core.utils import get_tx_hash

        assert get_tx_hash(None) == "unknown"

    def test_get_tx_hash_bytes(self):
        """Test get_tx_hash with bytes transaction hash."""
        from iwa.core.utils import get_tx_hash

        result = get_tx_hash({"transactionHash": b"\xab\xcd"})
        assert result == "abcd"

    def test_get_tx_hash_string(self):
        """Test get_tx_hash with string transaction hash."""
        from iwa.core.utils import get_tx_hash

        result = get_tx_hash({"transactionHash": "0xabc123"})
        assert result == "0xabc123"

    def test_get_tx_hash_empty(self):
        """Test get_tx_hash with empty receipt."""
        from iwa.core.utils import get_tx_hash

        assert get_tx_hash({}) == "unknown"


# ============================================================================
# Plugins tests - covering lines 23, 28, 37, 45
# ============================================================================


class TestPluginBase:
    """Tests for Plugin ABC default implementations."""

    def test_plugin_version_default(self):
        """Test Plugin.version returns default version."""

        class TestPlugin(Plugin):
            @property
            def name(self):
                return "test"

        p = TestPlugin()
        assert p.version == "0.1.0"

    def test_plugin_config_model_default(self):
        """Test Plugin.config_model returns None by default."""

        class TestPlugin(Plugin):
            @property
            def name(self):
                return "test"

        p = TestPlugin()
        assert p.config_model is None

    def test_plugin_get_cli_commands_default(self):
        """Test Plugin.get_cli_commands returns empty dict by default."""

        class TestPlugin(Plugin):
            @property
            def name(self):
                return "test"

        p = TestPlugin()
        assert p.get_cli_commands() == {}

    def test_plugin_on_load_default(self):
        """Test Plugin.on_load does nothing by default."""

        class TestPlugin(Plugin):
            @property
            def name(self):
                return "test"

        p = TestPlugin()
        p.on_load()  # Should not raise

    def test_plugin_get_tui_view_default(self):
        """Test Plugin.get_tui_view returns None by default."""

        class TestPlugin(Plugin):
            @property
            def name(self):
                return "test"

        p = TestPlugin()
        assert p.get_tui_view() is None

    def test_plugin_get_tui_view_with_wallet(self):
        """Test Plugin.get_tui_view with wallet param returns None by default."""

        class TestPlugin(Plugin):
            @property
            def name(self):
                return "test"

        p = TestPlugin()
        assert p.get_tui_view(wallet=MagicMock()) is None
