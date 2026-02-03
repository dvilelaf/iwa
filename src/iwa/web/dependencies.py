"""Shared dependencies for Web API routers."""

import secrets
from typing import Optional

from fastapi import Header, HTTPException, Security
from fastapi.security import APIKeyHeader
from loguru import logger

from iwa.core.wallet import Wallet

# Singleton wallet instance (lazy-initialized or injected)
_wallet: Optional[Wallet] = None


def get_wallet() -> Wallet:
    """Get the wallet instance (lazy initialization or injected).

    Returns the injected wallet if set_wallet() was called,
    otherwise creates a new Wallet on first access.
    """
    global _wallet
    if _wallet is None:
        _wallet = Wallet()
    return _wallet


def set_wallet(wallet: Wallet) -> None:
    """Inject an external wallet instance.

    Call this BEFORE importing routers to share a wallet
    with an external application (e.g., Triton).
    """
    global _wallet
    _wallet = wallet


# Backwards compatibility: module-level wallet property
# Deprecated: use get_wallet() instead
class _WalletProxy:
    """Proxy that redirects to get_wallet() for backwards compatibility."""

    def __getattr__(self, name: str):
        return getattr(get_wallet(), name)


wallet = _WalletProxy()

# Authentication
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def _get_webui_password() -> Optional[str]:
    """Get WEBUI_PASSWORD from secrets (lazy load to ensure secrets.env is loaded)."""
    from iwa.core.secrets import secrets

    if hasattr(secrets, "webui_password") and secrets.webui_password:
        return secrets.webui_password.get_secret_value()
    return None


async def verify_auth(
    x_api_key: Optional[str] = Security(api_key_header), authorization: Optional[str] = Header(None)
) -> bool:
    """Verify authentication via API key or Password.

    Uses timing-safe comparison to prevent timing attacks.
    """
    password = _get_webui_password()

    # If no password configured, allow everything
    if not password:
        return True

    # Check X-API-Key header (timing-safe comparison)
    if x_api_key and secrets.compare_digest(x_api_key, password):
        return True

    # Check Authorization header (Bearer token)
    if authorization:
        scheme, _, param = authorization.partition(" ")
        if scheme.lower() == "bearer" and param and secrets.compare_digest(param, password):
            return True

    raise HTTPException(
        status_code=401,
        detail="Invalid authentication credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_config():
    """Dependency to provide the Config object."""
    import yaml

    from iwa.core.constants import CONFIG_PATH
    from iwa.core.models import Config

    if not CONFIG_PATH.exists():
        return Config()

    try:
        with open(CONFIG_PATH, "r") as f:
            data = yaml.safe_load(f) or {}
        return Config(**data)
    except Exception as e:
        logger.error(f"Error loading config: {e}")
        return Config()
