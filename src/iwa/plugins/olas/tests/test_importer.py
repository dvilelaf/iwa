"""Tests for Olas Service Importer."""

import json
from unittest.mock import patch

import pytest
from eth_account import Account

from iwa.plugins.olas.importer import DiscoveredKey, DiscoveredService, OlasServiceImporter


@pytest.fixture
def temp_dirs(tmp_path):
    """Create temporary directories for testing formats."""
    # .trader_runner format
    tr_path = tmp_path / "tr_service" / ".trader_runner"
    tr_path.mkdir(parents=True)
    (tr_path / "service_id.txt").write_text("123")
    (tr_path / "service_safe_address.txt").write_text("0xSafeAddress")

    # Mock encrypted keystore
    keystore = {
        "address": "78731d3ca6b7e34ac0f824c42a7cc18a495cabab",
        "crypto": {"cipher": "aes-128-ctr"},
        "id": "1",
        "version": 3,
    }
    (tr_path / "agent_pkey.txt").write_text(json.dumps(keystore))

    # .operate format
    op_path = tmp_path / "op_service" / ".operate"
    op_path.mkdir(parents=True)
    services_path = op_path / "services" / "uuid"
    services_path.mkdir(parents=True)

    op_config = {
        "keys": [{"address": "0xAgent", "private_key": "0x123"}],
        "chain_configs": {"gnosis": {"chain_data": {"token": 456, "multisig": "0xOpSafe"}}},
    }
    (services_path / "config.json").write_text(json.dumps(op_config))

    return tmp_path


@pytest.fixture
def importer():
    """Create OlasServiceImporter with mocked KeyStorage."""
    with patch("iwa.plugins.olas.importer.KeyStorage") as mock_ks_cls:
        ks = mock_ks_cls.return_value
        ks.accounts = {}
        ks._password = "test_password"
        # MockConfig is also needed since importer init creates one
        with patch("iwa.plugins.olas.importer.Config") as mock_cfg_cls:
            cfg = mock_cfg_cls.return_value
            cfg.plugins = {}
            return OlasServiceImporter(ks)


def test_scan_directory(importer, temp_dirs):
    """Test scanning directory for services."""
    services = importer.scan_directory(temp_dirs)
    assert len(services) == 2

    # Verify trader_runner service
    tr_svc = next(s for s in services if s.format == "trader_runner")
    assert tr_svc.service_id == 123
    assert tr_svc.safe_address == "0xSafeAddress"
    assert len(tr_svc.keys) == 1
    assert tr_svc.keys[0].role == "agent"

    # Verify operate service
    op_svc = next(s for s in services if s.format == "operate")
    assert op_svc.service_id == 456
    assert op_svc.safe_address == "0xOpSafe"
    assert op_svc.keys[0].address == "0xAgent"


def test_decrypt_key(importer):
    """Test key decryption."""
    # Create mock encrypted key
    keystore = Account.encrypt("0x" + "1" * 64, "password")
    key = DiscoveredKey(address="0xAddr", encrypted_keystore=keystore, is_encrypted=True)

    success = importer.decrypt_key(key, "password")
    assert success
    assert key.private_key == "1" * 64
    assert not key.is_encrypted


def test_import_service_success(importer):
    """Test importing a discovered service."""
    service = DiscoveredService(
        service_id=789,
        service_name="TestImport",
        chain_name="gnosis",
        safe_address="0xSafe",
        keys=[
            DiscoveredKey(address="0xAgent", private_key="1" * 64, role="agent", is_encrypted=False)
        ],
    )

    with (
        patch.object(importer, "_import_key", return_value=(True, "ok")),
        patch.object(importer, "_import_safe", return_value=(True, "ok")),
        patch.object(importer, "_import_service_config", return_value=(True, "ok")),
    ):
        result = importer.import_service(service)
        assert result.success
        assert len(result.imported_keys) == 1
        assert "gnosis:789" in result.imported_services


def test_parse_plaintext_key_file(importer, tmp_path):
    """Test parsing plaintext key file."""
    # Test hex format
    key_file = tmp_path / "key.txt"
    key_hex = "1" * 64
    key_file.write_text(key_hex)

    key = importer._parse_plaintext_key_file(key_file, role="owner")
    assert key is not None
    assert key.private_key == key_hex

    # Test JSON format
    json_key = {"address": "0xAddr", "private_key": "0x2" * 32}
    key_file.write_text(json.dumps(json_key))
    key = importer._parse_plaintext_key_file(key_file, role="agent")
    assert key.address == "0xAddr"
