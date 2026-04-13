"""Core models"""

import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Type, TypeVar

import tomli
import tomli_w
from pydantic import BaseModel, Field, PrivateAttr, model_validator
from pydantic_core import core_schema
from ruamel.yaml import YAML

from iwa.core.types import EthereumAddress  # noqa: F401 - re-exported for backwards compatibility
from iwa.core.utils import singleton


def _update_yaml_recursive(target: Dict, source: Dict) -> None:
    """Recursively update a ruamel.yaml CommentedMap with data from a dict.

    This preserves comments and structure in the target map.
    Skips None values in source when target already has a non-None value,
    preventing fields (e.g. addresses) from being overwritten with None.
    """
    for key, value in source.items():
        if isinstance(value, dict) and key in target and isinstance(target[key], dict):
            _update_yaml_recursive(target[key], value)
        elif value is None and key in target and target[key] is not None:
            continue  # don't overwrite non-None with None
        else:
            target[key] = value


_AUDIT_MAX_BYTES = 1_048_576  # 1 MB


def _write_audit_log(data_dir: Path, ts: str, entry: dict) -> None:
    """Append a JSONL audit entry to data/audit.log with size-based rotation.

    Failures are logged at WARNING but never propagate — audit is non-fatal.
    """
    try:
        audit_path = data_dir / "audit.log"
        if audit_path.exists() and audit_path.stat().st_size > _AUDIT_MAX_BYTES:
            rotated = data_dir / "audit.log.1"
            try:
                rotated.unlink(missing_ok=True)
                audit_path.rename(rotated)
            except OSError:
                pass  # rotation failure is non-fatal
        # Open with mode 0o600 so audit.log is never world-readable.
        # The mode argument only applies on creation; fchmod ensures 0o600 even
        # on existing files that may have been created with a looser umask.
        fd = os.open(str(audit_path), os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
        try:
            os.fchmod(fd, 0o600)
        except OSError:
            pass
        with os.fdopen(fd, "a", encoding="utf-8") as af:
            af.write(json.dumps(entry) + "\n")
        # Also emit to docker logs — audit.log lives in data/ (wipeable volume);
        # docker logs survive outside the volume so this gives forensic evidence
        # even when data/ is lost.
        from loguru import logger as _logger
        _logger.info(f"[audit] {json.dumps(entry)}")
    except OSError as _e:
        from loguru import logger as _logger
        _logger.warning(f"audit.log write failed (tamper or disk issue?): {_e}")


def _rotate_backup(path: Path, keep: int = 30) -> None:
    """Snapshot path to a timestamped backup file before overwriting. Prunes oldest.

    Also appends a JSONL audit entry to data/audit.log so every config/wallet
    write can be reconstructed post-incident without diffing backup files.
    """
    if not path.exists():
        return
    backup_dir = path.parent / "backups"
    # mode=0o700 on creation closes the TOCTOU window between mkdir and chmod.
    # The explicit chmod below still runs to fix dirs created by older versions.
    backup_dir.mkdir(mode=0o700, exist_ok=True)
    # Ensure the backups/ directory is not world-traversable (both code paths
    # — config saves and wallet saves — must agree on 0o700 so whichever path
    # creates the dir first doesn't leave it world-readable).
    try:
        os.chmod(backup_dir, 0o700)
    except OSError:
        pass
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = backup_dir / f"{path.name}.{ts}.bak"
    # Wrap backup copy in try/except so copy failures (ENOSPC, EACCES on backups/)
    # do NOT abort the main save — losing the backup is bad, but losing the write is
    # worse. This is symmetric with the prune section below.
    try:
        shutil.copy2(path, backup_path)
    except OSError as _e:
        from loguru import logger as _logger
        _logger.warning(f"_rotate_backup: could not write backup {backup_path}: {_e} — skipping backup, proceeding with save")
        return
    # Ensure backup has at least 0o600 (owner rw). Use | not & — bitwise AND
    # would strip bits and could produce 0o400 or 0o000 if source lacks owner-write.
    try:
        os.chmod(backup_path, 0o600)
    except OSError:
        pass

    # Prune beyond `keep` — sort by filename (not mtime) because mtime is unreliable
    # on overlayfs/NFS (overlayfs inherits lower-layer mtime on copy-up; NFS has 1s
    # granularity). The timestamp embedded in the filename is monotonic and
    # filesystem-independent.
    # Wrap in try/except so a prune failure (ENOSPC, permission) does NOT abort
    # the main save — the backup was already taken; losing old backups is preferable
    # to losing the current write.
    try:
        prefix = f"{path.name}."
        backups = sorted(
            (
                p
                for p in backup_dir.iterdir()
                if p.name.startswith(prefix) and p.name.endswith(".bak")
            ),
            key=lambda p: p.name,
            reverse=True,
        )
        for old in backups[keep:]:
            old.unlink(missing_ok=True)
    except OSError as _prune_e:
        from loguru import logger as _logger
        _logger.warning(f"_rotate_backup: prune failed for {path.name}: {_prune_e} — old backups may accumulate")

    try:
        from iwa.core.utils import get_version as _get_version
        _iwa_ver = _get_version("iwa")
    except Exception:
        _iwa_ver = "unknown"
    audit_entry = {
        "ts": ts,
        "action": "save",
        "file": path.name,
        "backup": str(backup_path),
        "pid": os.getpid(),
        "iwa_version": _iwa_ver,
    }
    _write_audit_log(path.parent, ts, audit_entry)


def _atomic_yaml_write(path: Path, data: dict, ryaml: YAML) -> None:
    """Write YAML data to path atomically using temp file + rename.

    Ensures no data loss if the process is killed mid-write:
    - Writes to a temp file in the same directory (same filesystem)
    - Sets restrictive permissions (0o600) on the temp file
    - Calls fsync to flush data to disk before renaming
    - Uses os.replace for atomic rename
    - Cleans up temp file on any failure
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        dir=path.parent, prefix=".save_", suffix=".yaml.tmp"
    )
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            ryaml.dump(data, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        import contextlib
        with contextlib.suppress(OSError):
            os.unlink(tmp_path)
        raise


class EncryptedData(BaseModel):
    """Encrypted data structure with explicit KDF parameters."""

    kdf: str = "scrypt"
    kdf_salt: str
    kdf_n: int = 16384  # 2**14
    kdf_r: int = 8
    kdf_p: int = 1
    kdf_len: int = 32
    cipher: str = "aesgcm"
    nonce: str
    ciphertext: str


class StoredAccount(BaseModel):
    """StoredAccount representing an EOA or contract account."""

    address: EthereumAddress = Field(description="Ethereum address (checksummed)")
    tag: str = Field(description="Human-readable alias for the account")


class StoredSafeAccount(StoredAccount):
    """StoredSafeAccount representing a Gnosis Safe."""

    signers: List[EthereumAddress] = Field(description="List of owner addresses")
    threshold: int = Field(description="Required signatures threshold")
    chains: List[str] = Field(description="List of supported chains")


class CoreConfig(BaseModel):
    """Core configuration settings."""

    whitelist: Dict[str, EthereumAddress] = Field(
        default_factory=dict, description="Address whitelist for security"
    )
    custom_tokens: Dict[str, Dict[str, EthereumAddress]] = Field(
        default_factory=dict, description="Custom token definitions per chain"
    )

    # Web UI Configuration
    web_enabled: bool = Field(default=False, description="Enable Web UI")
    web_port: int = Field(default=8080, description="Web UI port")

    # IPFS Configuration
    ipfs_api_url: str = Field(default="https://registry.autonolas.tech", description="IPFS API URL")

    # Tenderly Configuration
    tenderly_profile: int = Field(default=0, description="Tenderly profile ID (1, 2, 3). 0 = disabled.")
    tenderly_native_funds: float = Field(
        default=1000.0, description="Native ETH amount for vNet funding"
    )
    tenderly_olas_funds: float = Field(default=100000.0, description="OLAS amount for vNet funding")

    # ChainList enrichment - when False, skip adding public RPCs from ChainList.
    # Useful for Anvil/local fork testing where only the configured RPC should be used.
    # Override via env var: CHAINLIST_ENRICHMENT=false
    chainlist_enrichment: bool = Field(default=True, description="Enrich RPCs from ChainList")

    @model_validator(mode="after")
    def _override_from_env(self) -> "CoreConfig":
        """Allow env var override for chainlist_enrichment (case-insensitive)."""
        import os
        val = (
            os.environ.get("CHAINLIST_ENRICHMENT")
            or os.environ.get("chainlist_enrichment")
            or ""
        ).lower()
        if val in ("false", "0", "no"):
            self.chainlist_enrichment = False
        return self

    # Safe Transaction Retry System
    safe_tx_max_retries: int = Field(default=6, description="Maximum retries for Safe transactions")
    safe_tx_gas_buffer: float = Field(
        default=1.5, description="Gas buffer multiplier for Safe transactions"
    )


T = TypeVar("T", bound="StorableModel")


class StorableModel(BaseModel):
    """StorableModel with load and save methods for JSON, TOML, and YAML formats."""

    _storage_format: Optional[str] = PrivateAttr(default=None)
    _path: Optional[Path] = PrivateAttr()

    def save_json(self, path: Optional[Path] = None, **kwargs) -> None:
        """Save to JSON file"""
        if path is None:
            if getattr(self, "_path", None) is None:
                raise ValueError("Save path not specified and no previous path stored.")
            path = self._path

        path = path.with_suffix(".json")

        with path.open("w", encoding="utf-8") as f:
            json.dump(self.model_dump(), f, indent=2, ensure_ascii=False, **kwargs)
        self._storage_format = "json"
        self._path = path

    def save_toml(self, path: Optional[Path] = None) -> None:
        """Save to TOML file"""
        if path is None:
            if getattr(self, "_path", None) is None:
                raise ValueError("Save path not specified and no previous path stored.")
            path = self._path

        path = path.with_suffix(".toml")

        with path.open("wb") as f:
            tomli_w.dump(self.model_dump(exclude_none=True), f)
        self._storage_format = "toml"
        self._path = path

    def save_yaml(self, path: Optional[Path] = None) -> None:
        """Save to YAML file preserving comments if file exists.

        Uses atomic write (temp file + rename) to prevent data loss.
        """
        if path is None:
            if getattr(self, "_path", None) is None:
                raise ValueError("Save path not specified and no previous path stored.")
            path = self._path

        path = path.with_suffix(".yaml")
        ryaml = YAML()
        ryaml.preserve_quotes = True
        ryaml.indent(mapping=2, sequence=4, offset=2)

        data = self.model_dump(mode="json")

        if path.exists():
            with path.open("r", encoding="utf-8") as f:
                try:
                    target = ryaml.load(f) or {}
                    _update_yaml_recursive(target, data)
                    data = target
                except Exception as e:
                    from loguru import logger

                    logger.warning(f"Failed to parse existing YAML at {path}, overwriting: {e}")

        _atomic_yaml_write(path, data, ryaml)
        self._storage_format = "yaml"
        self._path = path

    def save(self, path: str | Path | None = None, **kwargs) -> None:
        """Save to file with specified format"""
        if path is None:
            if getattr(self, "_path", None) is None:
                raise ValueError("Save path not specified and no previous path stored.")
            path = self._path

        path = Path(path)
        ext = path.suffix.lower()
        if ext == ".json":
            self.save_json(path, **kwargs)
        elif ext in {".toml", ".tml"}:
            self.save_toml(path)
        elif ext in {".yaml", ".yml"}:
            self.save_yaml(path)
        else:
            sf = (self._storage_format or "").lower()
            if sf == "json":
                self.save_json(path, **kwargs)
            elif sf in {"toml", "tml"}:
                self.save_toml(path)
            elif sf in {"yaml", "yml"}:
                self.save_yaml(path)
            else:
                raise ValueError(f"Extension not supported: {ext}")

    @classmethod
    def load_json(cls: Type[T], path: str | Path) -> T:
        """Load from JSON file"""
        path = Path(path)
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        obj = cls(**data)
        obj._storage_format = "json"
        obj._path = path
        return obj

    @classmethod
    def load_toml(cls: Type[T], path: str | Path) -> T:
        """Load from TOML file"""
        path = Path(path)
        with path.open("rb") as f:
            data = tomli.load(f)
        obj = cls(**data)
        obj._storage_format = "toml"
        obj._path = path
        return obj

    @classmethod
    def load_yaml(cls: Type[T], path: str | Path) -> T:
        """Load from YAML file"""
        path = Path(path)
        ryaml = YAML()
        with path.open("r", encoding="utf-8") as f:
            data = ryaml.load(f)
        obj = cls(**data)
        obj._storage_format = "yaml"
        obj._path = path
        return obj

    @classmethod
    def load(cls: Type[T], path: Path) -> T:
        """Load from file with specified format"""
        extension = path.suffix.lower()
        if extension == ".json":
            return cls.load_json(path)
        elif extension in {".toml", ".tml"}:
            return cls.load_toml(path)
        elif extension in {".yaml", ".yml"}:
            return cls.load_yaml(path)
        else:
            raise ValueError(f"Unsupported file extension: {extension}")


@singleton
class Config(StorableModel):
    """Config with auto-loading and plugin support."""

    core: Optional[CoreConfig] = None
    plugins: Dict[str, BaseModel] = Field(default_factory=dict)

    _initialized: bool = PrivateAttr(default=False)
    _plugin_models: Dict[str, type] = PrivateAttr(default_factory=dict)

    def model_post_init(self, __context) -> None:
        """Load config from file after initialization."""
        if not self._initialized:
            self._try_load()
            self._initialized = True

    def _try_load(self) -> None:
        """Try to load from config.yaml if exists, otherwise create default."""
        from loguru import logger

        from iwa.core.constants import CONFIG_PATH

        if not CONFIG_PATH.exists():
            # Initialize default core config and save
            self.core = CoreConfig()
            CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
            self.save_yaml(CONFIG_PATH)
            logger.info(f"Created default config file: {CONFIG_PATH}")
            return

        try:
            ryaml = YAML()
            with CONFIG_PATH.open("r", encoding="utf-8") as f:
                data = ryaml.load(f) or {}

            # Load core config
            if "core" in data:
                self.core = CoreConfig(**data["core"])

            # Load plugin configs - will be hydrated when plugins register
            if "plugins" in data:
                for plugin_name, plugin_data in data["plugins"].items():
                    # Store raw data until plugin model is registered
                    if plugin_name in self._plugin_models:
                        self.plugins[plugin_name] = self._plugin_models[plugin_name](**plugin_data)
                    else:
                        # Store as dict temporarily, will hydrate on register
                        self.plugins[plugin_name] = plugin_data

            self._path = CONFIG_PATH
            self._storage_format = "yaml"
        except Exception as e:
            logger.warning(f"Failed to load config from {CONFIG_PATH}: {e}")

        # Ensure core config always exists
        if self.core is None:
            self.core = CoreConfig()

    def register_plugin_config(self, plugin_name: str, model_class: type) -> None:
        """Register a plugin's config model class.

        If raw data was loaded for this plugin, it will be hydrated into the model.
        If no data exists, creates default config and persists to file.

        IMPORTANT: Never overwrites existing non-None values with defaults.
        When hydrating from raw YAML data, the YAML values take priority.
        When creating defaults for a new plugin, existing YAML data on disk
        is preserved via _update_yaml_recursive (None never overwrites non-None).

        Only persists to disk when the hydrated model introduces new default
        fields not present in the original data, avoiding unnecessary writes
        that could corrupt the config during crash-restart cycles.
        """
        self._plugin_models[plugin_name] = model_class

        # Hydrate any raw data that was loaded from YAML
        if plugin_name in self.plugins:
            current = self.plugins[plugin_name]
            if isinstance(current, dict):
                hydrated = model_class(**current)
                self.plugins[plugin_name] = hydrated
                # Only persist if the model added new default fields
                hydrated_keys = set(hydrated.model_dump(mode="json").keys())
                if hydrated_keys - set(current.keys()):
                    self.save_config()
        else:
            # No existing data — check if YAML on disk has data for this plugin
            # (could happen if _try_load ran before plugin was registered and
            # the YAML section was added by another process/deploy)
            from iwa.core.constants import CONFIG_PATH

            disk_data = None
            if CONFIG_PATH.exists():
                try:
                    ryaml = YAML()
                    with CONFIG_PATH.open("r", encoding="utf-8") as f:
                        raw = ryaml.load(f) or {}
                    disk_data = (raw.get("plugins") or {}).get(plugin_name)
                except Exception:
                    pass

            if disk_data and isinstance(disk_data, dict):
                # YAML has data for this plugin — hydrate from disk, not defaults
                self.plugins[plugin_name] = model_class(**disk_data)
            else:
                # Truly new plugin — create default config and persist
                self.plugins[plugin_name] = model_class()
                self.save_config()

    def save_config(self) -> None:
        """Persist current config to config.yaml using atomic write.

        Uses write-to-temp-file + os.replace() to prevent data loss if the
        process is killed mid-write. Takes a rotating timestamped backup before
        overwriting. Holds an exclusive fcntl.flock for the duration of the
        backup+write to prevent concurrent writers from racing.
        """
        import fcntl

        from loguru import logger

        from iwa.core.constants import CONFIG_PATH

        data = {}

        if self.core:
            data["core"] = self.core.model_dump(mode="json")

        data["plugins"] = {}
        for plugin_name, plugin_config in self.plugins.items():
            if isinstance(plugin_config, BaseModel):
                data["plugins"][plugin_name] = plugin_config.model_dump(mode="json")
            elif isinstance(plugin_config, dict):
                data["plugins"][plugin_name] = plugin_config

        ryaml = YAML()
        ryaml.preserve_quotes = True
        ryaml.indent(mapping=2, sequence=4, offset=2)

        if CONFIG_PATH.exists():
            with CONFIG_PATH.open("r", encoding="utf-8") as f:
                try:
                    target = ryaml.load(f) or {}
                    _update_yaml_recursive(target, data)
                    data = target
                except Exception as e:
                    logger.warning(
                        f"Failed to parse existing config at {CONFIG_PATH}, overwriting: {e}"
                    )

        # Exclusive lock to prevent concurrent writers from racing on backup+write.
        # mkdir parents=True: on fresh install CONFIG_PATH.parent may not exist yet;
        # _atomic_yaml_write also does this but the lock open runs FIRST.
        lock_path = CONFIG_PATH.parent / ".config.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with open(lock_path, "w") as _lock_file:
            try:
                os.chmod(lock_path, 0o600)
            except OSError:
                pass
            fcntl.flock(_lock_file, fcntl.LOCK_EX)
            try:
                # Rotating timestamped backup before overwriting (30 snapshots kept)
                _rotate_backup(CONFIG_PATH, keep=30)
                _atomic_yaml_write(CONFIG_PATH, data, ryaml)
            finally:
                fcntl.flock(_lock_file, fcntl.LOCK_UN)

        self._path = CONFIG_PATH
        self._storage_format = "yaml"

    def get_plugin_config(self, plugin_name: str) -> Optional[BaseModel]:
        """Get a plugin's configuration."""
        return self.plugins.get(plugin_name)


class Token(BaseModel):
    """Token model for defined tokens."""

    symbol: str
    address: EthereumAddress
    decimals: int = 18
    name: Optional[str] = None


class TokenAmount(BaseModel):
    """TokenAmount - amount in human-readable ETH units."""

    address: EthereumAddress
    symbol: str
    amount_eth: float


class FundRequirements(BaseModel):
    """FundRequirements - amounts in human-readable ETH units."""

    native_eth: float
    tokens: List[TokenAmount] = Field(default_factory=list)


class VirtualNet(BaseModel):
    """Virtual Network configuration for Tenderly."""

    vnet_id: Optional[str] = Field(default=None, description="Tenderly Virtual TestNet ID")
    chain_id: int = Field(description="Chain ID of the forked network")
    vnet_slug: Optional[str] = Field(default=None, description="Slug for the Virtual TestNet")
    vnet_display_name: Optional[str] = Field(default=None, description="Display name for UI")
    funds_requirements: Dict[str, FundRequirements] = Field(
        description="Required funds for test accounts"
    )
    admin_rpc: Optional[str] = Field(default=None, description="Admin RPC URL for the vNet")
    public_rpc: Optional[str] = Field(default=None, description="Public RPC URL for the vNet")
    initial_block: int = Field(default=0, description="Block number at vNet creation")

    @classmethod
    def __get_pydantic_core_schema__(cls, _source, _handler):
        """Get the Pydantic core schema for VirtualNet."""
        return core_schema.with_info_after_validator_function(
            cls.validate,
            _handler(_source),
        )

    @classmethod
    def validate(cls, value: "VirtualNet", _info) -> "VirtualNet":
        """Validate RPC URLs."""
        if value.admin_rpc and not (
            value.admin_rpc.startswith("http://") or value.admin_rpc.startswith("https://")
        ):
            raise ValueError(f"Invalid admin_rpc URL: {value.admin_rpc}")
        if value.public_rpc and not (
            value.public_rpc.startswith("http://") or value.public_rpc.startswith("https://")
        ):
            raise ValueError(f"Invalid public_rpc URL: {value.public_rpc}")
        return value


class TenderlyConfig(StorableModel):
    """Configuration for Tenderly integration."""

    vnets: Dict[str, VirtualNet] = Field(
        description="Map of chain names to VirtualNet configurations"
    )
