"""Tests for atomic config save and register_plugin_config safety."""

from unittest.mock import patch

import pytest
from pydantic import BaseModel, Field
from ruamel.yaml import YAML

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
# Access the original Config class (unwrap singleton).
import iwa.core.models as _models
from iwa.core.models import StorableModel

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
        # Rotating backups now go to <config_dir>/backups/ with a timestamp suffix.
        backup_dir = tmp_path / "backups"

        ryaml = YAML()
        with config_path.open("w") as f:
            ryaml.dump(
                {"core": {"whitelist": {}}, "plugins": {"olas": {"services": {"gnosis:1": {}}}}},
                f,
            )

        config = _fresh_config(config_path)
        with patch("iwa.core.constants.CONFIG_PATH", config_path):
            config.save_config()

        # A timestamped backup must exist in the backups/ subdirectory.
        assert backup_dir.exists(), "backups/ directory was not created"
        backups = list(backup_dir.iterdir())
        assert backups, "No backup file found in backups/"
        backup_path = backups[0]
        with backup_path.open() as f:
            backup_data = ryaml.load(f)
        assert "plugins" in backup_data

    def test_save_config_backup_dir_created_on_save(self, tmp_path):
        """Each save_config() call creates a rotating backup in backups/."""
        config_path = tmp_path / "config.yaml"
        backup_dir = tmp_path / "backups"

        # _fresh_config creates a default config.yaml; save_config then backs it up.
        config = _fresh_config(config_path)
        with patch("iwa.core.constants.CONFIG_PATH", config_path):
            config.save_config()

        assert config_path.exists()
        # backups/ should exist and contain exactly one timestamped backup
        assert backup_dir.exists()
        backups = list(backup_dir.iterdir())
        assert len(backups) == 1
        assert backups[0].name.startswith("config.yaml.")

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


# ---------------------------------------------------------------------------
# Test: _rotate_backup behaviour (review fixes)
# ---------------------------------------------------------------------------


class TestRotateBackup:
    """_rotate_backup must create backups in backups/ (plural) with timestamp names."""

    def test_backup_created_in_backups_dir(self, tmp_path):
        """Backup goes to <parent>/backups/<name>.<ts>.bak."""
        from iwa.core.models import _rotate_backup

        target = tmp_path / "config.yaml"
        target.write_text("key: value\n")

        _rotate_backup(target, keep=5)

        backup_dir = tmp_path / "backups"
        assert backup_dir.exists()
        backups = list(backup_dir.iterdir())
        assert len(backups) == 1
        assert backups[0].name.startswith("config.yaml.")
        assert backups[0].name.endswith(".bak")

    def test_no_backup_if_file_absent(self, tmp_path):
        """If the target file doesn't exist, nothing is written."""
        from iwa.core.models import _rotate_backup

        _rotate_backup(tmp_path / "nonexistent.yaml", keep=5)
        assert not (tmp_path / "backups").exists()

    def test_pruning_keeps_at_most_n_backups(self, tmp_path):
        """After keep+2 calls, only `keep` backups remain.

        Timestamp resolution is 1 second, so we mock datetime.now to produce
        distinct timestamps for each call — otherwise same-second backups
        overwrite each other and the pruning assertion would be wrong.
        """
        from datetime import datetime, timezone
        from unittest.mock import patch as _patch
        from iwa.core.models import _rotate_backup

        target = tmp_path / "config.yaml"
        keep = 3
        call_count = 0

        def fake_now(tz=None):
            nonlocal call_count
            # Each call gets a distinct second so filenames are unique
            dt = datetime(2025, 1, 1, 0, 0, call_count, tzinfo=timezone.utc)
            call_count += 1
            return dt

        with _patch("iwa.core.models.datetime") as mock_dt:
            mock_dt.now.side_effect = fake_now
            for i in range(keep + 2):
                target.write_text(f"version: {i}\n")
                _rotate_backup(target, keep=keep)

        backups = sorted((tmp_path / "backups").iterdir())
        assert len(backups) == keep

    def test_lock_file_parent_created_if_missing(self, tmp_path):
        """save_config must not fail if CONFIG_PATH.parent does not exist yet."""
        fresh_dir = tmp_path / "newdir"
        # Do NOT create fresh_dir — it must be created by save_config itself
        config_path = fresh_dir / "config.yaml"

        config = _fresh_config(config_path)
        with patch("iwa.core.constants.CONFIG_PATH", config_path):
            # Should not raise FileNotFoundError on the lock open
            config.save_config()

        assert config_path.exists()

    def test_audit_log_rotated_when_over_1mb(self, tmp_path):
        """audit.log must be renamed to audit.log.1 when it exceeds 1 MB."""
        from iwa.core.models import _rotate_backup

        target = tmp_path / "config.yaml"
        target.write_text("key: value\n")

        # Create a large audit.log (>1 MB)
        audit_path = tmp_path / "audit.log"
        audit_path.write_bytes(b"x" * (1_048_576 + 1))

        _rotate_backup(target, keep=5)

        # The oversized log must have been rotated
        assert (tmp_path / "audit.log.1").exists(), "audit.log.1 must exist after rotation"
        # New audit.log is smaller (just one entry)
        assert audit_path.stat().st_size < 1_048_576

    def test_audit_log_not_rotated_when_under_1mb(self, tmp_path):
        """audit.log must NOT be rotated when it is below 1 MB."""
        from iwa.core.models import _rotate_backup

        target = tmp_path / "config.yaml"
        target.write_text("key: value\n")

        audit_path = tmp_path / "audit.log"
        audit_path.write_text("small entry\n")
        original_inode = audit_path.stat().st_ino

        _rotate_backup(target, keep=5)

        # Same inode = not rotated (just appended to)
        assert audit_path.stat().st_ino == original_inode
        assert not (tmp_path / "audit.log.1").exists()

    def test_audit_log_created_with_0o600(self, tmp_path):
        """audit.log must be created with 0o600 permissions (not world-readable)."""
        from iwa.core.models import _rotate_backup

        target = tmp_path / "config.yaml"
        target.write_text("key: value\n")

        _rotate_backup(target, keep=5)

        audit_path = tmp_path / "audit.log"
        assert audit_path.exists()
        mode = audit_path.stat().st_mode & 0o777
        assert mode == 0o600, f"Expected 0o600, got {oct(mode)}"

    def test_backups_dir_created_with_0o700(self, tmp_path):
        """backups/ directory must be set to 0o700 so it is not world-traversable."""
        from iwa.core.models import _rotate_backup

        target = tmp_path / "config.yaml"
        target.write_text("key: value\n")

        _rotate_backup(target, keep=5)

        backup_dir = tmp_path / "backups"
        assert backup_dir.exists()
        mode = backup_dir.stat().st_mode & 0o777
        assert mode == 0o700, f"Expected 0o700, got {oct(mode)}"


# ---------------------------------------------------------------------------
# Test: KeyStorage.save uses backups/ (plural) and flock
# ---------------------------------------------------------------------------


class TestKeyStorageSave:
    """KeyStorage.save() must use backups/ directory and acquire flock."""

    def test_wallet_backup_goes_to_backups_plural(self, tmp_path):
        """Backup directory must be named 'backups' (plural), not 'backup'."""
        from unittest.mock import patch as _patch
        from iwa.core.keys import KeyStorage

        wallet_path = tmp_path / "wallet.json"
        # Create a valid empty wallet so KeyStorage can load it
        ks = KeyStorage(wallet_path, password="test_password")
        # Save once to create the initial file, then save again to trigger backup
        ks.save()
        ks.save()

        assert (tmp_path / "backups").exists(), "Should use 'backups' (plural)"
        assert not (tmp_path / "backup").exists(), "Should NOT use 'backup' (singular)"

    def test_wallet_flock_acquired(self, tmp_path):
        """fcntl.flock must be called with LOCK_EX during save."""
        from unittest.mock import patch as _patch
        import fcntl as _fcntl
        from iwa.core.keys import KeyStorage

        wallet_path = tmp_path / "wallet.json"
        ks = KeyStorage(wallet_path, password="test_password")

        flock_calls = []

        def track_flock(fd, op):
            flock_calls.append(op)

        with _patch("iwa.core.keys.fcntl.flock", side_effect=track_flock):
            ks.save()

        assert _fcntl.LOCK_EX in flock_calls, "LOCK_EX must be acquired"
        assert _fcntl.LOCK_UN in flock_calls, "LOCK_UN must be released"
