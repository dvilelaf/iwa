"""Shared dependencies for Web API routers."""

import logging
import os
from typing import Optional

from fastapi import Header, HTTPException, Security
from fastapi.security import APIKeyHeader

from iwa.core.wallet import Wallet

logger = logging.getLogger(__name__)

# Singleton wallet instance for the web app
wallet = Wallet()

# Authentication
WEBUI_PASSWORD = os.getenv("WEBUI_PASSWORD")
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_auth(
    x_api_key: Optional[str] = Security(api_key_header), authorization: Optional[str] = Header(None)
) -> bool:
    """Verify authentication via API key or Password."""
    # If no password configured, allow everything
    if not WEBUI_PASSWORD:
        return True

    # Check X-API-Key header (simple password check)
    if x_api_key == WEBUI_PASSWORD:
        return True

    # Check Authorization header (Bearer token)
    if authorization:
        scheme, _, param = authorization.partition(" ")
        if scheme.lower() == "bearer" and param == WEBUI_PASSWORD:
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
