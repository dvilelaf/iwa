"""Core models"""

from pydantic_core import core_schema
from pydantic import BaseModel, SecretStr, PrivateAttr
from pydantic_settings import BaseSettings
from pathlib import Path
from .constants import SECRETS_PATH, CONFIG_PATH
from typing import Optional
from iwa.core.utils import singleton
import re
import tomli
import tomli_w
from web3 import Web3


ETHEREUM_ADDRESS_REGEX = r"0x[0-9a-fA-F]{40}"


class EthereumAddress(str):
    """EthereumAddress"""

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


class CoreConfig(BaseModel):
    """CoreConfig"""
    manual_claim_enabled: bool = False
    request_activity_alert_enabled: bool = True


@singleton
class Config(BaseModel):
    """Config"""

    core: Optional[CoreConfig] = None
    _path: Path = PrivateAttr()  # not stored nor validated

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "Config":
        """Load"""
        config_path = path or Path(CONFIG_PATH)
        if not config_path.exists():
            raise ValueError(f"Configuration file does not exist at {config_path}")

        with open(config_path, "rb") as f:
            data = tomli.load(f)

        obj = cls(**data)
        obj._path = config_path
        return obj

    def save(self) -> None:
        """Save configuration to a TOML file"""
        with open(self._path, "wb") as f:
            tomli_w.dump(self.model_dump(exclude_none=True), f)


@singleton
class Secrets(BaseSettings):
    """Secrets"""
    gnosis_rpc: Optional[SecretStr] = None
    base_rpc: Optional[SecretStr] = None
    ethereum_rpc: Optional[SecretStr] = None
    gnosisscan_api_key: SecretStr
    telegram_bot_token: SecretStr
    telegram_chat_id: int
    coingecko_api_key: SecretStr
    wallet_password: SecretStr
    security_word: SecretStr

    class Config:
        """Config"""
        env_file = SECRETS_PATH
        env_file_encoding = "utf-8"
