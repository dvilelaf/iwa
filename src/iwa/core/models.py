"""Core models"""

import json
from pathlib import Path
from typing import Dict, List, Optional, Type, TypeVar

import tomli
import tomli_w
import yaml
from pydantic import BaseModel, Field, PrivateAttr
from pydantic_core import core_schema

from iwa.core.types import EthereumAddress  # noqa: F401 - re-exported for backwards compatibility
from iwa.core.utils import singleton


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

    manual_claim_enabled: bool = Field(
        default=False, description="Enable manual claiming of rewards"
    )
    request_activity_alert_enabled: bool = Field(
        default=True, description="Enable alerts for suspicious activity"
    )
    whitelist: Dict[str, EthereumAddress] = Field(
        default_factory=dict, description="Address whitelist for security"
    )
    custom_tokens: Dict[str, Dict[str, EthereumAddress]] = Field(
        default_factory=dict, description="Custom token definitions per chain"
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
        """Save to YAML file"""
        if path is None:
            if getattr(self, "_path", None) is None:
                raise ValueError("Save path not specified and no previous path stored.")
            path = self._path

        path = path.with_suffix(".yaml")

        with path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(self.model_dump(), f, sort_keys=False, allow_unicode=True)
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
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
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
            import yaml

            with CONFIG_PATH.open("r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}

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
        """
        self._plugin_models[plugin_name] = model_class

        # Hydrate any raw data that was loaded
        if plugin_name in self.plugins:
            current = self.plugins[plugin_name]
            if isinstance(current, dict):
                self.plugins[plugin_name] = model_class(**current)
        else:
            # Create default config for plugin and persist
            self.plugins[plugin_name] = model_class()
            self.save_config()

    def save_config(self) -> None:
        """Persist current config to config.yaml."""
        import yaml

        from iwa.core.constants import CONFIG_PATH

        data = {}

        if self.core:
            data["core"] = self.core.model_dump()

        data["plugins"] = {}
        for plugin_name, plugin_config in self.plugins.items():
            if isinstance(plugin_config, BaseModel):
                data["plugins"][plugin_name] = plugin_config.model_dump()
            elif isinstance(plugin_config, dict):
                data["plugins"][plugin_name] = plugin_config

        with CONFIG_PATH.open("w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True, default_flow_style=False)

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
