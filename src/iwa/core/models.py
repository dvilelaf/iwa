"""Core models"""

import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Type, TypeVar

import tomli
import tomli_w
import yaml
from pydantic import BaseModel, Field, PrivateAttr
from pydantic_core import core_schema
from web3 import Web3

from iwa.core.utils import singleton

ETHEREUM_ADDRESS_REGEX = r"0x[0-9a-fA-F]{40}"


class EthereumAddress(str):
    """EthereumAddress"""

    def __new__(cls, value: str):
        """Create a new EthereumAddress instance."""
        if not re.fullmatch(ETHEREUM_ADDRESS_REGEX, value):
            raise ValueError(f"Invalid Ethereum address: {value}")
        return str.__new__(cls, Web3.to_checksum_address(value))

    @classmethod
    def __get_pydantic_core_schema__(cls, _source, _handler):
        """Get the Pydantic core schema for EthereumAddress."""
        return core_schema.with_info_after_validator_function(
            cls.validate,
            core_schema.str_schema(),
        )

    @classmethod
    def validate(cls, value: str, _info) -> str:
        """Validate that the value is a valid Ethereum address."""
        if not re.fullmatch(ETHEREUM_ADDRESS_REGEX, value):
            raise ValueError(f"Invalid Ethereum address: {value}")
        return Web3.to_checksum_address(value)


class StoredAccount(BaseModel):
    """StoredAccount"""

    address: EthereumAddress
    tag: str


class StoredSafeAccount(StoredAccount):
    """StoredSafeAccount"""

    signers: List[EthereumAddress]
    threshold: int
    chains: List[str]


class CoreConfig(BaseModel):
    """CoreConfig"""

    manual_claim_enabled: bool = False
    request_activity_alert_enabled: bool = True
    whitelist: Dict[str, EthereumAddress] = Field(default_factory=dict)
    custom_tokens: Dict[str, Dict[str, EthereumAddress]] = Field(default_factory=dict)


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

        with path.open("w", encoding="utf-8") as f:
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
    """Config"""

    core: Optional[CoreConfig] = None
    plugins: Optional[Dict[str, BaseModel]] = None


class Token(BaseModel):
    """Token model for defined tokens."""

    symbol: str
    address: EthereumAddress
    decimals: int = 18
    name: Optional[str] = None


class TokenAmount(BaseModel):
    """TokenAmount"""

    address: EthereumAddress
    symbol: str
    amount: float


class FundRequirements(BaseModel):
    """FundRequirements"""

    native: float
    tokens: List[TokenAmount] = Field(default_factory=list)


class VirtualNet(BaseModel):
    """VirtualNet"""

    vnet_id: Optional[str] = None
    chain_id: int
    vnet_slug: Optional[str] = None
    vnet_display_name: Optional[str] = None
    funds_requirements: Dict[str, FundRequirements]
    admin_rpc: Optional[str] = None
    public_rpc: Optional[str] = None

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
    """TenderlyConfig"""

    vnets: Dict[str, VirtualNet]
