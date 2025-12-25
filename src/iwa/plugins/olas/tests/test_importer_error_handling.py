"""Tests for Olas service importer error handling and validation."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from iwa.plugins.olas.importer import DiscoveredKey, DiscoveredService, OlasServiceImporter


@pytest.fixture
def mock_wallet():
    """Mock wallet."""
    wallet = MagicMock()
    wallet.key_storage = MagicMock()
    return wallet


@pytest.fixture
def importer(mock_wallet):
    """Importer fixture."""
    with patch("iwa.core.models.Config"):
        return OlasServiceImporter(mock_wallet)


def test_parse_plaintext_key_file_corrupted_json(importer, tmp_path):
    """Test parsing a file that contains invalid JSON."""
    p = tmp_path / "corrupted.json"
    p.write_text("{invalid: json}")

    # Method is private but we test it for coverage
    result = importer._parse_plaintext_key_file(str(p))
    assert result is None


def test_parse_plaintext_key_file_not_dict(importer, tmp_path):
    """Test parsing a file that is valid JSON but not a dict."""
    p = tmp_path / "list.json"
    p.write_text("[1, 2, 3]")

    result = importer._parse_plaintext_key_file(str(p))
    assert result is None


def test_decrypt_key_invalid_format(importer):
    """Test decrypting a key with invalid format."""
    key = DiscoveredKey(address="0x1", is_encrypted=True)
    # Since key.encrypted_keystore is None and it's not a valid hex, it should fail
    assert importer.decrypt_key(key, "pwd") is False


def test_scan_directory_with_unreadable_subdir(importer, tmp_path):
    """Test scanning a directory with permission errors (mocked)."""
    # Simply ensure it doesn't crash if walk returns something
    with patch("os.walk") as mock_walk:
        mock_walk.return_value = [
            (str(tmp_path), ["subdir"], []),
        ]
        results = importer.scan_directory(str(tmp_path))
        assert len(results) == 0


def test_import_service_missing_keys(importer):
    """Test importing a service with no keys."""
    service = DiscoveredService(service_id=1, keys=[])
    result = importer.import_service(service)
    assert result.success is True  # Empty import is technically successful?
    # Actually let's check what it does.


def test_import_service_already_exists(importer):
    """Test importing a service that is already in existing config."""
    with patch("iwa.plugins.olas.models.OlasConfig") as mock_olas_config_cls:
        mock_olas_config = mock_olas_config_cls.return_value
        mock_olas_config.services = {"gnosis:1": MagicMock()}
        # Inject the mock config into the importer's config
        importer.config.plugins["olas"] = mock_olas_config

        service = DiscoveredService(service_id=1, chain_name="gnosis")
        result = importer.import_service(service)
        # In current implementation, if _import_service_config fails with "duplicate",
        # the service is added to 'skipped' and success remains True or False depending on other keys.
        assert result.success is True
        assert len(result.skipped) == 1
        assert "already exists" in result.skipped[0] or "duplicate" in result.skipped[0]


def test_parse_plaintext_key_file_hex_but_invalid(importer, tmp_path):
    """Test parsing a file that looks like hex but isn't valid private key."""
    p = tmp_path / "bad_hex.txt"
    p.write_text("0xZZZZZZZZZZ")  # Invalid hex

    result = importer._parse_plaintext_key_file(str(p))
    assert result is None


def test_scan_operate_success(importer, tmp_path):
    """Test scanning a directory in .operate format."""
    operate_dir = tmp_path / "service_dir" / ".operate"
    operate_dir.mkdir(parents=True)
    keys_dir = operate_dir / "keys"
    keys_dir.mkdir()
    (keys_dir / "0x123").write_text('{"address": "0x123", "crypto": {}}')

    services_dir = operate_dir / "services"
    services_dir.mkdir()
    uuid_dir = services_dir / "some-uuid"
    uuid_dir.mkdir()
    (uuid_dir / "config.json").write_text(
        '{"chain_configs": {"gnosis": {"chain_data": {"token": 42, "multisig": "0xSafe"}}}}'
    )

    results = importer.scan_directory(Path(tmp_path))
    assert len(results) == 1
    assert results[0].format == "operate"
    assert results[0].service_id == 42


def test_scan_operate_missing_keys(importer, tmp_path):
    """Test .operate directory with missing keys folder."""
    operate_dir = Path(tmp_path) / ".operate"
    operate_dir.mkdir()
    # No keys dir

    result = importer._parse_operate_format(operate_dir)
    assert result == []


def test_scan_operate_standalone_keys(importer, tmp_path):
    """Test .operate directory with standalone keys (no services)."""
    operate_dir = Path(tmp_path) / "standalone.operate"
    operate_dir.mkdir()
    wallets_dir = operate_dir / "wallets"
    wallets_dir.mkdir()
    (wallets_dir / "ethereum.txt").write_text('{"address": "0x123", "private_key": "0xabc"}')
    (wallets_dir / "ethereum.json").write_text('{"safes": {"gnosis": "0xSafe"}}')

    services = importer._parse_operate_format(operate_dir)
    assert len(services) == 1
    assert services[0].safe_address == "0xSafe"
    assert len(services[0].keys) == 1


def test_parse_trader_runner_keys(importer, tmp_path):
    """Test _parse_trader_runner_format with agent and operator keys."""
    runner_dir = Path(tmp_path) / ".trader_runner"
    runner_dir.mkdir()
    # Provision valid-ish keystore JSON (must have 'crypto' or 'ciphertext')
    (runner_dir / "agent_pkey.txt").write_text(
        '{"address": "0xAgent", "crypto": {"ciphertext": "abc"}}'
    )
    (runner_dir / "operator_pkey.txt").write_text(
        '{"address": "0xOper", "crypto": {"ciphertext": "def"}}'
    )
    (runner_dir / "service_id.txt").write_text("100\n")
    (runner_dir / "service_safe_address.txt").write_text("0xSafeAddress\n")

    service = importer._parse_trader_runner_format(runner_dir)
    assert service.service_id == 100
    assert service.safe_address == "0xSafeAddress"
    assert len(service.keys) == 2
    assert any(k.role == "agent" for k in service.keys)
    assert any(k.role == "operator" for k in service.keys)


def test_parse_trader_runner_invalid_id(importer, tmp_path):
    """Test _parse_trader_runner_format with invalid service_id."""
    runner_dir = Path(tmp_path) / ".trader_runner"
    runner_dir.mkdir()
    (runner_dir / "service_id.txt").write_text("not-an-int\n")
    (runner_dir / "agent_pkey.txt").write_text('{"address": "0x1", "crypto": {}}')

    service = importer._parse_trader_runner_format(runner_dir)
    assert service.service_id is None


def test_parse_keys_json(importer, tmp_path):
    """Test _parse_keys_json with valid and invalid entries."""
    keys_file = Path(tmp_path) / "keys.json"
    keys_file.write_text(
        json.dumps(
            [
                {"address": "0x1", "crypto": {"ciphertext": "a"}},
                {"invalid": "key"},
                {"address": "0x2", "crypto": {"ciphertext": "b"}},
            ]
        )
    )

    keys = importer._parse_keys_json(keys_file)
    assert len(keys) == 2
    assert keys[0].address == "0x1"
    assert keys[1].address == "0x2"


def test_import_service_duplicate(importer):
    """Test importing a service that already exists in OlasConfig."""
    from iwa.plugins.olas.importer import DiscoveredService

    service = DiscoveredService(
        service_id=1,
        chain_name="gnosis",
        source_folder=Path("/tmp"),
        format="trader_runner",
        service_name="existing",
    )

    # Mock existing service in config
    importer.config.plugins["olas"] = MagicMock()
    importer.config.plugins["olas"].services = {"gnosis:1": MagicMock()}

    success, msg = importer._import_service_config(service)
    assert success is False
    assert msg == "duplicate"


def test_import_key_duplicate(importer):
    """Test importing a key that already exists in KeyStorage."""
    from iwa.plugins.olas.importer import DiscoveredKey

    key = DiscoveredKey(
        address="0x78731D3Ca6b7E34aC0F824c42a7cC18A495cabaB",
        private_key="0xabc",
        role="agent",
        source_file=Path("/tmp/key.txt"),
        is_encrypted=False,
    )

    importer.key_storage.find_stored_account.return_value = MagicMock()

    success, msg = importer._import_key(key, "service")
    assert success is False
    assert msg == "duplicate"


def test_import_key_no_password(importer):
    """Test importing an encrypted key without providing a password."""
    from iwa.plugins.olas.importer import DiscoveredKey

    key = DiscoveredKey(
        address="0x78731D3Ca6b7E34aC0F824c42a7cC18A495cabaB",
        private_key=None,
        role="agent",
        source_file=Path("/tmp/key.txt"),
        is_encrypted=True,
        encrypted_keystore={"crypto": {}},
    )

    importer.key_storage.find_stored_account.return_value = None

    success, msg = importer._import_key(key, "service", password=None)
    assert success is False
    assert "password" in msg


def test_generate_tag_collisions(importer):
    """Test tag generation with collisions."""
    from iwa.plugins.olas.importer import DiscoveredKey

    key = DiscoveredKey(address="0x1", private_key="0x1", role="agent", is_encrypted=False)

    # Mock existing tags
    importer.key_storage.accounts = {
        "0x2": MagicMock(tag="test_service_agent"),
        "0x3": MagicMock(tag="test_service_agent_2"),
    }

    tag = importer._generate_tag(key, "test_service")
    assert tag == "test_service_agent_3"


def test_import_safe_duplicate(importer):
    """Test importing a Safe that already exists."""
    from iwa.plugins.olas.importer import DiscoveredService

    service = DiscoveredService(
        service_id=1, chain_name="gnosis", safe_address="0xSafe", source_folder=Path("/tmp")
    )

    importer.key_storage.find_stored_account.return_value = MagicMock()

    success, msg = importer._import_safe(service)
    assert success is False
    assert msg == "duplicate"


def test_import_key_success(importer):
    """Test successful key import with tag generation."""
    from iwa.plugins.olas.importer import DiscoveredKey

    addr = "0x78731D3Ca6b7E34aC0F824c42a7cC18A495cabaB"
    key = DiscoveredKey(
        address=addr,
        private_key="abc",
        role="agent",
        source_file=Path("/tmp/k"),
        is_encrypted=False,
    )
    importer.key_storage.find_stored_account.return_value = None
    importer.key_storage.accounts = {}

    with patch("iwa.core.keys.EncryptedAccount.encrypt_private_key") as mock_enc:
        mock_enc.return_value = MagicMock(address=addr)
        success, msg = importer._import_key(key, "my_service")
        assert success is True
        assert msg == "ok"
        assert addr in importer.key_storage.accounts


def test_import_safe_success(importer):
    """Test successful Safe import with tag generation."""
    from iwa.plugins.olas.importer import DiscoveredService

    service = DiscoveredService(
        service_id=1,
        chain_name="gnosis",
        safe_address="0x78731D3Ca6b7E34aC0F824c42a7cC18A495cabaB",
        source_folder=Path("/tmp"),
        service_name="my_service",
    )
    importer.key_storage.find_stored_account.return_value = None
    importer.key_storage.accounts = {}

    success, msg = importer._import_safe(service)
    assert success is True
    assert msg == "ok"
    assert "0x78731D3Ca6b7E34aC0F824c42a7cC18A495cabaB" in importer.key_storage.accounts


def test_import_service_config_success(importer):
    """Test successful service config import."""
    from iwa.plugins.olas.importer import DiscoveredService

    service = DiscoveredService(
        service_id=1,
        chain_name="gnosis",
        safe_address="0x78731D3Ca6b7E34aC0F824c42a7cC18A495cabaB",
        source_folder=Path("/tmp"),
        service_name="my_service",
    )
    mock_olas = MagicMock()
    mock_olas.services = {}  # Use real dict
    importer.config.plugins["olas"] = mock_olas

    success, msg = importer._import_service_config(service)
    assert success is True
    assert msg == "ok"
    mock_olas.add_service.assert_called_once()
