"""Shared HTTP session utilities."""

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

DEFAULT_RETRY_TOTAL = 3
DEFAULT_BACKOFF_FACTOR = 1
DEFAULT_STATUS_FORCELIST = [429, 500, 502, 503, 504]


def create_retry_session(
    retries: int = DEFAULT_RETRY_TOTAL,
    backoff_factor: int = DEFAULT_BACKOFF_FACTOR,
    status_forcelist: list[int] | None = None,
) -> requests.Session:
    """Create a requests.Session with retry strategy.

    Used by PriceService, IPFS, and other modules that need
    persistent HTTP connections with automatic retry.
    """
    session = requests.Session()
    retry_strategy = Retry(
        total=retries,
        backoff_factor=backoff_factor,
        status_forcelist=status_forcelist or DEFAULT_STATUS_FORCELIST,
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session
