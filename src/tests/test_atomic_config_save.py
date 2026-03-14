"""Tests for atomic config save and register_plugin_config safety."""

import os
from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import BaseModel, Field
from ruamel.yaml import YAML

from iwa.core.models import StorableModel


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Access the original Config class (unwrap singleton).
import iwa.core.models as _models

_OriginalConfig = None
for _cell in _models.Config.__closure__ or []:
    _val = _cell.cell_contents
    if isinstance(_val, type) and _val.__name__ == "Config":
        _OriginalConfig = _val
        break

if _OriginalConfig is None:
    for _cell in _models.Config.__closure__ or []:
        _val = _cell.cell_contents
        if isinstance(_val, dict):
            for _k in _val:
                if isinstance(_k, type) and _k.__name__ == "Config":
                    _OriginalConfig = _k
                    break


def _fresh_config(config_path):
    """Create a fresh Config instance bypassing singleton and auto-load."""
    config = object.__new__(_OriginalConfig)
    object.__setattr__(config, "__dict__", {
        "core": None,
        "plugins": {},
    })
    object.__setattr__(config, "__pydantic_fields_set__", set())
    object.__setattr__(config, "__pydantic_extra__", None)
    object.__setattr__(config, "__pydantic_private__", {
        "_initialized": False,
        "_plugin_models": {},
        "_path": None,
        "_storage_format": None,
    })
    with patch("iwa.core.constants.CONFIG_PATH", config_path):
        config._try_load()
    return config


class SimplePluginConfig(BaseModel):
    """Minimal plugin config for testing."""

    services: dict = Field(default_factory=dict)
    enabled: bool = True


class ExtendedPluginConfig(BaseModel):
    """Plugin config with an extra field to test new-default detection."""

    services: dict = Field(default_factory=dict)
    enabled: bool = True
    new_field: str = "default_value"


class MockStorable(StorableModel):
    name: str = "test"
    value: int = 42


# ---------------------------------------------------------------------------
# Test: Atomic write in save_config
# ---------------------------------------------------------------------------


class TestAtomicSaveConfig:
    """Tests that save_config uses atomic write (temp file + rename)."""

    def test_save_config_creates_file(self, tmp_path):
        config_path = tmp_path / "config.yaml"

        ryaml = YAML()
        with config_path.open("w") as f:
            ryaml.dump({"core": {"whitelist": {}}, "plugins": {}}, f)

        config = _fresh_config(config_path)
        with patch("iwa.core.constants.CONFIG_PATH", config_path):
            config.register_plugin_config("test_plugin", SimplePluginConfig)
            config.save_config()

        assert config_path.exists()
        with config_path.open() as f:
            data = ryaml.load(f)
        assert "plugins" in data
        assert "test_plugin" in data["plugins"]

    def test_save_config_creates_backup(self, tmp_path):
        config_path = tmp_path / "config.yaml"
        backup_path = tmp_path / "config.yaml.bak"

        ryaml = YAML()
        with config_path.open("w") as f:
            ryaml.dump(
                {"core": {"whitelist": {}}, "plugins": {"olas": {"services": {"gnosis:1": {}}}}},
                f,
            )

        config = _fresh_config(config_path)
        with patch("iwa.core.constants.CONFIG_PATH", config_path):
            config.save_config()

        assert backup_path.exists()
        with backup_path.open() as f:
            backup_data = ryaml.load(f)
        assert "plugins" in backup_data

    def test_save_config_no_backup_for_empty_file(self, tmp_path):
        config_path = tmp_path / "config.yaml"
        backup_path = tmp_path / "config.yaml.bak"

        # Create an empty config file (0 bytes)
        config_path.touch()

        config = _fresh_config(config_path)
        with patch("iwa.core.constants.CONFIG_PATH", config_path):
            config.save_config()

        assert config_path.exists()
        assert not backup_path.exists()

    def test_save_config_no_temp_file_left_on_success(self, tmp_path):
        config_path = tmp_path / "config.yaml"

        config = _fresh_config(config_path)
        with patch("iwa.core.constants.CONFIG_PATH", config_path):
            config.save_config()

        tmp_files = list(tmp_path.glob("*.tmp"))
        assert tmp_files == []

    def test_save_config_cleans_temp_on_failure(self, tmp_path):
        config_path = tmp_path / "config.yaml"

        config = _fresh_config(config_path)
        with patch("iwa.core.constants.CONFIG_PATH", config_path):
            with patch("ruamel.yaml.YAML.dump", side_effect=RuntimeError("write failed")):
                with pytest.raises(RuntimeError, match="write failed"):
                    config.save_config()

        tmp_files = list(tmp_path.glob("*.tmp"))
        assert tmp_files == []

    def test_save_config_preserves_original_on_failure(self, tmp_path):
        config_path = tmp_path / "config.yaml"

        ryaml = YAML()
        with config_path.open("w") as f:
            ryaml.dump(
                {"core": {"whitelist": {}}, "plugins": {"olas": {"services": {"gnosis:1": {}}}}},
                f,
            )

        original_content = config_path.read_text()

        config = _fresh_config(config_path)
        with patch("iwa.core.constants.CONFIG_PATH", config_path):
            with patch("os.replace", side_effect=OSError("disk full")):
                with pytest.raises(OSError):
                    config.save_config()

        assert config_path.read_text() == original_content


# ---------------------------------------------------------------------------
# Test: register_plugin_config only saves when needed
# ---------------------------------------------------------------------------


class TestRegisterPluginConfigSaveReduction:
    """Tests that register_plugin_config only saves when new fields are added."""

    def test_no_save_when_all_fields_present(self, tmp_path):
        config_path = tmp_path / "config.yaml"

        ryaml = YAML()
        with config_path.open("w") as f:
            ryaml.dump(
                {
                    "core": {"whitelist": {}},
                    "plugins": {"test": {"services": {"a": 1}, "enabled": True}},
                },
                f,
            )

        config = _fresh_config(config_path)
        save_count = 0
        original_save = _OriginalConfig.save_config

        def counting_save(self_inner):
            nonlocal save_count
            save_count += 1

        with patch("iwa.core.constants.CONFIG_PATH", config_path):
            with patch.object(_OriginalConfig, "save_config", counting_save):
                config.register_plugin_config("test", SimplePluginConfig)

        assert save_count == 0

    def test_saves_when_new_default_field_added(self, tmp_path):
        config_path = tmp_path / "config.yaml"

        ryaml = YAML()
        with config_path.open("w") as f:
            ryaml.dump(
                {
                    "core": {"whitelist": {}},
                    "plugins": {"test": {"services": {}, "enabled": True}},
                },
                f,
            )

        config = _fresh_config(config_path)
        save_count = 0

        def counting_save(self_inner):
            nonlocal save_count
            save_count += 1

        with patch("iwa.core.constants.CONFIG_PATH", config_path):
            with patch.object(_OriginalConfig, "save_config", counting_save):
                config.register_plugin_config("test", ExtendedPluginConfig)

        assert save_count == 1

    def test_saves_when_plugin_not_in_config(self, tmp_path):
        config_path = tmp_path / "config.yaml"

        ryaml = YAML()
        with config_path.open("w") as f:
            ryaml.dump({"core": {"whitelist": {}}, "plugins": {}}, f)

        config = _fresh_config(config_path)
        save_count = 0

        def counting_save(self_inner):
            nonlocal save_count
            save_count += 1

        with patch("iwa.core.constants.CONFIG_PATH", config_path):
            with patch.object(_OriginalConfig, "save_config", counting_save):
                config.register_plugin_config("new_plugin", SimplePluginConfig)

        assert save_count == 1

    def test_hydrates_correctly_without_saving(self, tmp_path):
        config_path = tmp_path / "config.yaml"

        ryaml = YAML()
        with config_path.open("w") as f:
            ryaml.dump(
                {
                    "core": {"whitelist": {}},
                    "plugins": {"test": {"services": {"svc1": "data"}, "enabled": False}},
                },
                f,
            )

        config = _fresh_config(config_path)
        with patch("iwa.core.constants.CONFIG_PATH", config_path):
            config.register_plugin_config("test", SimplePluginConfig)

        plugin = config.get_plugin_config("test")
        assert isinstance(plugin, SimplePluginConfig)
        assert plugin.services == {"svc1": "data"}
        assert plugin.enabled is False


# ---------------------------------------------------------------------------
# Test: StorableModel.save_yaml atomic write
# ---------------------------------------------------------------------------


class TestStorableModelAtomicYaml:
    """Tests that StorableModel.save_yaml uses atomic write."""

    def test_save_yaml_writes_correctly(self, tmp_path):
        path = tmp_path / "test.yaml"
        model = MockStorable(name="hello", value=99)
        model.save_yaml(path)

        assert path.exists()
        ryaml = YAML()
        with path.open() as f:
            data = ryaml.load(f)
        assert data["name"] == "hello"
        assert data["value"] == 99

    def test_save_yaml_no_temp_files(self, tmp_path):
        path = tmp_path / "test.yaml"
        model = MockStorable()
        model.save_yaml(path)

        tmp_files = list(tmp_path.glob("*.tmp"))
        assert tmp_files == []

    def test_save_yaml_cleans_temp_on_failure(self, tmp_path):
        path = tmp_path / "test.yaml"
        model = MockStorable()

        with patch("ruamel.yaml.YAML.dump", side_effect=RuntimeError("fail")):
            with pytest.raises(RuntimeError):
                model.save_yaml(path)

        tmp_files = list(tmp_path.glob("*.tmp"))
        assert tmp_files == []
