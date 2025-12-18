"""Configuration settings module."""

from typing import Optional

from dotenv import load_dotenv
from pydantic import ConfigDict, SecretStr
from pydantic_settings import BaseSettings

from iwa.core.constants import SECRETS_PATH
from iwa.core.utils import singleton


@singleton
class Settings(BaseSettings):
    """Application Settings loaded from environment and secrets file."""

    gnosis_rpc: Optional[SecretStr] = None
    base_rpc: Optional[SecretStr] = None
    ethereum_rpc: Optional[SecretStr] = None
    gnosisscan_api_key: Optional[SecretStr] = None
    telegram_bot_token: Optional[SecretStr] = None
    telegram_chat_id: Optional[int] = None
    coingecko_api_key: Optional[SecretStr] = None
    wallet_password: Optional[SecretStr] = None
    security_word: Optional[SecretStr] = None
    tenderly_account_slug: Optional[SecretStr] = None
    tenderly_project_slug: Optional[SecretStr] = None
    tenderly_access_key: Optional[SecretStr] = None

    model_config = ConfigDict(
        env_file=str(SECRETS_PATH),
        env_file_encoding="utf-8",
        extra="ignore"
    )

    def __init__(self, **values):
        """Initialize Settings and load environment variables."""
        # Force load dotenv to ensure os.maven variables are set if pydantic doesn't pick them up automatically
        # or if we need them in os.environ for other libraries.
        load_dotenv(SECRETS_PATH, override=True)
        super().__init__(**values)


# Global settings instance
settings = Settings()
