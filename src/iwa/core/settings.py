"""Configuration settings module."""

import os
from typing import Optional

from dotenv import load_dotenv
from pydantic import ConfigDict, SecretStr, model_validator
from pydantic_settings import BaseSettings

from iwa.core.constants import SECRETS_PATH
from iwa.core.utils import singleton


@singleton
class Settings(BaseSettings):
    """Application Settings loaded from environment and secrets file."""

    # Testing mode - when True, uses Tenderly test RPCs; when False, uses production RPCs
    testing: bool = True

    # RPC endpoints (loaded from gnosis_rpc/ethereum_rpc/base_rpc in secrets.env)
    # When testing=True, these get overwritten with *_test_rpc values
    gnosis_rpc: Optional[SecretStr] = None
    base_rpc: Optional[SecretStr] = None
    ethereum_rpc: Optional[SecretStr] = None

    # Test RPCs
    gnosis_test_rpc: Optional[SecretStr] = None
    ethereum_test_rpc: Optional[SecretStr] = None
    base_test_rpc: Optional[SecretStr] = None

    gnosisscan_api_key: Optional[SecretStr] = None
    coingecko_api_key: Optional[SecretStr] = None
    wallet_password: Optional[SecretStr] = None
    security_word: Optional[SecretStr] = None

    # Tenderly profile (1 or 2) - determines which credentials to load
    tenderly_profile: int = 1

    # Tenderly credentials - loaded dynamically based on profile
    tenderly_account_slug: Optional[SecretStr] = None
    tenderly_project_slug: Optional[SecretStr] = None
    tenderly_access_key: Optional[SecretStr] = None

    # Tenderly funding configuration
    tenderly_native_funds: float = 1000.0
    tenderly_olas_funds: float = 100000.0

    web_enabled: bool = False
    web_port: int = 8080
    webui_password: Optional[SecretStr] = None

    model_config = ConfigDict(env_file=str(SECRETS_PATH), env_file_encoding="utf-8", extra="ignore")

    def __init__(self, **values):
        """Initialize Settings and load environment variables."""
        # Force load dotenv to ensure os.environ variables are set
        load_dotenv(SECRETS_PATH, override=True)
        super().__init__(**values)

    @model_validator(mode="after")
    def load_tenderly_profile_credentials(self) -> "Settings":
        """Load Tenderly credentials based on the selected profile."""
        profile = self.tenderly_profile

        # Load profile-specific credentials from environment
        account = os.getenv(f"tenderly_account_slug_{profile}")
        project = os.getenv(f"tenderly_project_slug_{profile}")
        access_key = os.getenv(f"tenderly_access_key_{profile}")

        if account:
            self.tenderly_account_slug = SecretStr(account)
        if project:
            self.tenderly_project_slug = SecretStr(project)
        if access_key:
            self.tenderly_access_key = SecretStr(access_key)

        # When in testing mode, override RPCs with test RPCs (Tenderly)
        if self.testing:
            if self.gnosis_test_rpc:
                self.gnosis_rpc = self.gnosis_test_rpc
            if self.ethereum_test_rpc:
                self.ethereum_rpc = self.ethereum_test_rpc
            if self.base_test_rpc:
                self.base_rpc = self.base_test_rpc

        # Convert empty webui_password to None (no auth required)
        if self.webui_password and not self.webui_password.get_secret_value():
            self.webui_password = None

        return self


# Global settings instance
settings = Settings()
