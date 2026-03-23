from pathlib import Path
from unittest.mock import mock_open, patch

import pytest

from iwa.core.models import EthereumAddress, StorableModel


def test_ethereum_address_valid():
    addr_str = "0x1111111111111111111111111111111111111111"
    addr = EthereumAddress(addr_str)
    assert addr == addr_str


def test_ethereum_address_invalid():
    with pytest.raises(ValueError, match="Invalid Ethereum address"):
        EthereumAddress("0xInvalid")


def test_ethereum_address_checksum():
    # Test that it converts to checksum address
    addr_lower = "0x1111111111111111111111111111111111111111"  # All 1s is same
    # Let's use one that changes
    addr_lower = "0x5aaeb6053f3e94c9b9a09f33669435e7ef1beaed"
    addr_checksum = "0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAed"
    addr = EthereumAddress(addr_lower)
    assert addr == addr_checksum


class MockStorableModel(StorableModel):
    name: str
    value: int


def test_storable_model_save_json():
    model = MockStorableModel(name="test", value=123)
    with patch("pathlib.Path.open", mock_open()) as mock_file:
        model.save_json(Path("test.json"))
        mock_file.assert_called_once()


def test_storable_model_save_toml():
    model = MockStorableModel(name="test", value=123)
    with patch("pathlib.Path.open", mock_open()) as mock_file:
        model.save_toml(Path("test.toml"))
        mock_file.assert_called_once()


def test_storable_model_save_yaml(tmp_path):
    model = MockStorableModel(name="test", value=123)
    path = tmp_path / "test.yaml"
    model.save_yaml(path)
    assert path.exists()


def test_storable_model_save_auto_json():
    model = MockStorableModel(name="test", value=123)
    with patch("pathlib.Path.open", mock_open()) as mock_file:
        model.save("test.json")
        mock_file.assert_called_once()


def test_storable_model_save_auto_toml():
    model = MockStorableModel(name="test", value=123)
    with patch("pathlib.Path.open", mock_open()) as mock_file:
        model.save("test.toml")
        mock_file.assert_called_once()


def test_storable_model_save_auto_yaml(tmp_path):
    model = MockStorableModel(name="test", value=123)
    path = tmp_path / "test.yaml"
    model.save(str(path))
    assert path.exists()


def test_storable_model_save_no_path():
    model = MockStorableModel(name="test", value=123)
    with pytest.raises(ValueError, match="Save path not specified"):
        model.save()


def test_storable_model_save_stored_path():
    model = MockStorableModel(name="test", value=123)
    model._path = Path("stored.json")
    model._storage_format = "json"
    with patch("pathlib.Path.open", mock_open()) as mock_file:
        model.save()
        mock_file.assert_called_once()


def test_storable_model_load_json():
    json_content = '{"name": "test", "value": 123}'
    with patch("pathlib.Path.open", mock_open(read_data=json_content)):
        model = MockStorableModel.load_json("test.json")
        assert model.name == "test"
        assert model.value == 123


def test_storable_model_load_toml():
    toml_content = b'name = "test"\nvalue = 123'
    with patch("pathlib.Path.open", mock_open(read_data=toml_content)):
        model = MockStorableModel.load_toml("test.toml")
        assert model.name == "test"
        assert model.value == 123


def test_storable_model_load_yaml():
    yaml_content = "name: test\nvalue: 123"
    with patch("pathlib.Path.open", mock_open(read_data=yaml_content)):
        model = MockStorableModel.load_yaml("test.yaml")
        assert model.name == "test"
        assert model.value == 123


def test_storable_model_load_auto():
    json_content = '{"name": "test", "value": 123}'
    with patch("pathlib.Path.open", mock_open(read_data=json_content)):
        model = MockStorableModel.load(Path("test.json"))
        assert model.name == "test"


def test_ethereum_address_validate_method():
    # Test the validate class method directly
    with pytest.raises(ValueError, match="Invalid Ethereum address"):
        EthereumAddress.validate("0xInvalid", None)

    addr = EthereumAddress.validate("0x1111111111111111111111111111111111111111", None)
    assert addr == "0x1111111111111111111111111111111111111111"


def test_storable_model_save_methods_no_path_error():
    model = MockStorableModel(name="test", value=123)
    # Ensure no _path is set
    if hasattr(model, "_path"):
        del model._path

    with pytest.raises(ValueError, match="Save path not specified"):
        model.save_json()

    with pytest.raises(ValueError, match="Save path not specified"):
        model.save_toml()

    with pytest.raises(ValueError, match="Save path not specified"):
        model.save_yaml()


def test_storable_model_save_unsupported_extension():
    model = MockStorableModel(name="test", value=123)
    with pytest.raises(ValueError, match="Extension not supported"):
        model.save("test.txt")


def test_storable_model_save_fallback_format(tmp_path):
    model = MockStorableModel(name="test", value=123)
    model._storage_format = "json"
    with patch("pathlib.Path.open", mock_open()) as mock_file:
        model.save("test.txt")  # Unknown extension, fallback to _storage_format
        mock_file.assert_called_once()  # Should call save_json

    model._storage_format = "toml"
    with patch("pathlib.Path.open", mock_open()) as mock_file:
        model.save("test.txt")
        mock_file.assert_called_once()  # Should call save_toml

    model._storage_format = "yaml"
    yaml_path = tmp_path / "test.yaml"
    model.save(str(yaml_path))
    assert yaml_path.exists()


def test_storable_model_load_unsupported_extension():
    with pytest.raises(ValueError, match="Unsupported file extension"):
        MockStorableModel.load(Path("test.txt"))


from iwa.core.models import Config


def test_config_singleton():
    c1 = Config()
    c2 = Config()
    assert c1 is c2


def test_storable_model_save_with_stored_path(tmp_path):
    model = MockStorableModel(name="test", value=123)
    model._path = Path("stored.json")
    with patch("pathlib.Path.open", mock_open()) as mock_file:
        model.save_json()
        mock_file.assert_called_once()

    model._path = Path("stored.toml")
    with patch("pathlib.Path.open", mock_open()) as mock_file:
        model.save_toml()
        mock_file.assert_called_once()

    yaml_path = tmp_path / "stored.yaml"
    model._path = yaml_path
    model.save_yaml()
    assert yaml_path.exists()


def test_storable_model_load_auto_toml_yaml():
    toml_content = b'name = "test"\nvalue = 123'
    with patch("pathlib.Path.open", mock_open(read_data=toml_content)):
        model = MockStorableModel.load(Path("test.toml"))
        assert model.name == "test"

    yaml_content = "name: test\nvalue: 123"
    with patch("pathlib.Path.open", mock_open(read_data=yaml_content)):
        model = MockStorableModel.load(Path("test.yaml"))
        assert model.name == "test"


# --- EthereumAddress enforcement in Pydantic models ---


from iwa.plugins.olas.models import Service, StakingStatus


def test_staking_status_auto_checksums_address():
    """StakingStatus should auto-checksum lowercase addresses."""
    lowercase = "0x5aaeb6053f3e94c9b9a09f33669435e7ef1beaed"
    checksummed = "0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAed"
    status = StakingStatus(
        is_staked=True,
        staking_state="STAKED",
        staking_contract_address=lowercase,
    )
    assert status.staking_contract_address == checksummed


def test_staking_status_rejects_invalid_address():
    """StakingStatus should reject invalid addresses."""
    with pytest.raises(ValueError):
        StakingStatus(
            is_staked=True,
            staking_state="STAKED",
            staking_contract_address="0xNotAnAddress",
        )


def test_service_auto_checksums_all_address_fields():
    """Service should auto-checksum all address fields."""
    addr1 = "0x5aaeb6053f3e94c9b9a09f33669435e7ef1beaed"
    addr2 = "0x1111111111111111111111111111111111111111"
    checksummed1 = "0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAed"
    svc = Service(
        service_name="test",
        chain_name="gnosis",
        service_id=1,
        multisig_address=addr1,
        agent_address=addr2,
        staking_contract_address=addr1,
        service_owner_eoa_address=addr2,
    )
    assert svc.multisig_address == checksummed1
    assert svc.staking_contract_address == checksummed1
    assert svc.agent_address == addr2  # All 1s doesn't change
    assert svc.service_owner_eoa_address == addr2


def test_service_rejects_invalid_address():
    """Service should reject invalid address strings."""
    with pytest.raises(ValueError):
        Service(
            service_name="test",
            chain_name="gnosis",
            service_id=1,
            multisig_address="not_an_address",
        )


# --- _update_yaml_recursive tests ---

from iwa.core.models import _update_yaml_recursive


def test_update_yaml_recursive_none_does_not_overwrite():
    """None in source must NOT overwrite a non-None value in target."""
    target = {"address": "0xABCD", "name": "svc"}
    source = {"address": None, "name": "svc"}
    _update_yaml_recursive(target, source)
    assert target["address"] == "0xABCD"


def test_update_yaml_recursive_non_none_overwrites():
    """A non-None source value MUST overwrite a non-None target value."""
    target = {"address": "0xOLD", "count": 1}
    source = {"address": "0xNEW", "count": 2}
    _update_yaml_recursive(target, source)
    assert target["address"] == "0xNEW"
    assert target["count"] == 2


def test_update_yaml_recursive_empty_string_vs_none():
    """Empty string is a valid value and should overwrite; None should not."""
    target = {"field_a": "keep_me", "field_b": "keep_me_too"}
    source = {"field_a": "", "field_b": None}
    _update_yaml_recursive(target, source)
    # Empty string overwrites
    assert target["field_a"] == ""
    # None does NOT overwrite
    assert target["field_b"] == "keep_me_too"


def test_update_yaml_recursive_none_sets_new_key():
    """None in source for a key absent from target should still be set."""
    target = {"existing": 1}
    source = {"new_key": None}
    _update_yaml_recursive(target, source)
    assert target["new_key"] is None


def test_update_yaml_recursive_nested_none_protection():
    """None protection must work recursively in nested dicts."""
    target = {
        "service": {
            "address": "0xABCD",
            "multisig": "0x1234",
        }
    }
    source = {
        "service": {
            "address": None,
            "multisig": "0xNEW",
        }
    }
    _update_yaml_recursive(target, source)
    assert target["service"]["address"] == "0xABCD"
    assert target["service"]["multisig"] == "0xNEW"
