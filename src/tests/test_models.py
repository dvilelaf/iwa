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


def test_storable_model_save_yaml():
    model = MockStorableModel(name="test", value=123)
    with patch("pathlib.Path.open", mock_open()) as mock_file:
        model.save_yaml(Path("test.yaml"))
        mock_file.assert_called_once()


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


def test_storable_model_save_auto_yaml():
    model = MockStorableModel(name="test", value=123)
    with patch("pathlib.Path.open", mock_open()) as mock_file:
        model.save("test.yaml")
        mock_file.assert_called_once()


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


def test_storable_model_save_fallback_format():
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
    with patch("pathlib.Path.open", mock_open()) as mock_file:
        model.save("test.txt")
        mock_file.assert_called_once()  # Should call save_yaml


def test_storable_model_load_unsupported_extension():
    with pytest.raises(ValueError, match="Unsupported file extension"):
        MockStorableModel.load(Path("test.txt"))


from iwa.core.models import Config


def test_config_singleton():
    c1 = Config()
    c2 = Config()
    assert c1 is c2


def test_storable_model_save_with_stored_path():
    model = MockStorableModel(name="test", value=123)
    model._path = Path("stored.json")
    with patch("pathlib.Path.open", mock_open()) as mock_file:
        model.save_json()
        mock_file.assert_called_once()

    model._path = Path("stored.toml")
    with patch("pathlib.Path.open", mock_open()) as mock_file:
        model.save_toml()
        mock_file.assert_called_once()

    model._path = Path("stored.yaml")
    with patch("pathlib.Path.open", mock_open()) as mock_file:
        model.save_yaml()
        mock_file.assert_called_once()


def test_storable_model_load_auto_toml_yaml():
    toml_content = b'name = "test"\nvalue = 123'
    with patch("pathlib.Path.open", mock_open(read_data=toml_content)):
        model = MockStorableModel.load(Path("test.toml"))
        assert model.name == "test"

    yaml_content = "name: test\nvalue: 123"
    with patch("pathlib.Path.open", mock_open(read_data=yaml_content)):
        model = MockStorableModel.load(Path("test.yaml"))
        assert model.name == "test"
