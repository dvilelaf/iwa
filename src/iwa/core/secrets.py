"""Secrets module - loads sensitive values from environment variables.

Secrets are injected via docker-compose env_file, NOT from mounted volume.
This is more secure as secrets don't persist in the container's filesystem.
"""

from typing import Optional

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Secrets(BaseSettings):
    """Application Secrets loaded from environment variables.

    In production, these are injected via docker-compose:
        env_file:
          - ./secrets.env

    For local development, set environment variables or use a .env file
    at the project root (not in data/).
    """

    # Testing mode - when True, uses Tenderly test RPCs; when False, uses production RPCs
    testing: bool = False

    # RPC endpoints
    # When testing=True, these get overwritten with *_test_rpc values
    gnosis_rpc: Optional[SecretStr] = None
    base_rpc: Optional[SecretStr] = None
    ethereum_rpc: Optional[SecretStr] = None

    # Test RPCs (Tenderly)
    gnosis_test_rpc: Optional[SecretStr] = None
    ethereum_test_rpc: Optional[SecretStr] = None
    base_test_rpc: Optional[SecretStr] = None

    coingecko_api_key: Optional[SecretStr] = None
    wallet_password: Optional[SecretStr] = None

    webui_password: Optional[SecretStr] = None

    # Load from environment only (no file)
    model_config = SettingsConfigDict(extra="ignore")

    @model_validator(mode="after")
    def load_tenderly_profile_credentials(self) -> "Secrets":
        """Load Tenderly credentials based on the selected profile."""
        # Note: Logic moved to dynamic loading in tools/reset_tenderly.py
        # using Config().core.tenderly_profile

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


# Global secrets instance
secrets = Secrets()
