"""Chain-related error classes and utilities."""

import re

from iwa.core.utils import configure_logger

logger = configure_logger()


class TenderlyQuotaExceededError(Exception):
    """Raised when Tenderly virtual network quota is exceeded (403 Forbidden).

    This is a fatal error that should halt execution and prompt the user to
    reset the Tenderly network.
    """

    pass


def sanitize_rpc_url(url: str) -> str:
    """Remove API keys and sensitive data from RPC URLs for safe logging.

    Sanitizes:
    - Query parameters (may contain API keys)
    - Path segments that look like API keys (32+ hex chars)
    - Known API key patterns in subdomains

    Args:
        url: The RPC URL to sanitize.

    Returns:
        Sanitized URL safe for logging.

    """
    if not url:
        return url
    # Remove query params that might contain keys
    sanitized = re.sub(r"\?.*$", "?***", url)
    # Remove path segments that look like API keys (32+ hex chars)
    sanitized = re.sub(r"/[a-fA-F0-9]{32,}", "/***", sanitized)
    # Remove common API key patterns in path (e.g., /v3/YOUR_KEY)
    sanitized = re.sub(r"/v[0-9]+/[a-zA-Z0-9_-]{20,}", "/v*/***", sanitized)
    return sanitized


# Backward compatibility alias
_sanitize_rpc_url = sanitize_rpc_url
