"""Secrets module - loads sensitive values from environment variables.

Secrets are loaded from:
1. Environment variables (injected by docker-compose env_file in production)
2. secrets.env file at project root (for local development)
"""

from pathlib import Path
from typing import Optional

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# secrets.env is at project root (not in data/)
SECRETS_FILE = Path("secrets.env")


class Secrets(BaseSettings):
    """Application Secrets loaded from environment variables.

    In production, these are injected via docker-compose:
        env_file:
          - ./secrets.env

    For local development, secrets are loaded from secrets.env at project root.
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

    # Load from environment AND secrets.env file (for local dev)
    model_config = SettingsConfigDict(
        env_file=str(SECRETS_FILE) if SECRETS_FILE.exists() else None,
        env_file_encoding="utf-8",
        extra="ignore",
    )

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

    @model_validator(mode="after")
    def strip_quotes_from_secrets(self) -> "Secrets":
        """Strip leading/trailing quotes from SecretStr fields.

        Docker env_file often preserves quotes (e.g. KEY="val" -> "val"),
        which causes API authentication failures.
        """
        for field_name, field_value in self:
            if isinstance(field_value, SecretStr):
                raw_value = field_value.get_secret_value()
                # Check for matching quotes at start and end
                if len(raw_value) >= 2 and (
                    (raw_value.startswith('"') and raw_value.endswith('"'))
                    or (raw_value.startswith("'") and raw_value.endswith("'"))
                ):
                    clean_value = raw_value[1:-1]
                    setattr(self, field_name, SecretStr(clean_value))
            elif isinstance(field_value, str):
                # Also strip quotes from plain string fields (like health_url)
                if len(field_value) >= 2 and (
                    (field_value.startswith('"') and field_value.endswith('"'))
                    or (field_value.startswith("'") and field_value.endswith("'"))
                ):
                    clean_value = field_value[1:-1]
                    setattr(self, field_name, clean_value)
        return self


# Global secrets instance
secrets = Secrets()
