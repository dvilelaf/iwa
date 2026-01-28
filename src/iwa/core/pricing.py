"""Pricing service module."""

import time
from datetime import datetime, timedelta
from typing import Dict, Optional

from loguru import logger

from iwa.core.http import create_retry_session
from iwa.core.secrets import secrets

# Global cache shared across all PriceService instances
_PRICE_CACHE: Dict[str, Dict] = {}
_CACHE_TTL = timedelta(minutes=30)
_NEGATIVE_CACHE_TTL = timedelta(minutes=5)


class PriceService:
    """Service to fetch token prices from CoinGecko."""

    BASE_URL = "https://api.coingecko.com/api/v3"

    def __init__(self):
        """Initialize PriceService."""
        self.secrets = secrets
        self.api_key = (
            self.secrets.coingecko_api_key.get_secret_value()
            if self.secrets.coingecko_api_key
            else None
        )
        self.session = create_retry_session()

    def close(self):
        """Close the session."""
        self.session.close()

    def get_token_price(self, token_id: str, vs_currency: str = "eur") -> Optional[float]:
        """Get token price in specified currency.

        Args:
            token_id: CoinGecko token ID (e.g. 'ethereum', 'gnosis', 'olas')
            vs_currency: Target currency (default 'eur')

        Returns:
            Price as float, or None if fetch failed.

        """
        cache_key = f"{token_id}_{vs_currency}"

        # Check global cache (including negative cache)
        if cache_key in _PRICE_CACHE:
            entry = _PRICE_CACHE[cache_key]
            ttl = _CACHE_TTL if entry["price"] is not None else _NEGATIVE_CACHE_TTL
            if datetime.now() - entry["timestamp"] < ttl:
                return entry["price"]

        price = self._fetch_price_from_api(token_id, vs_currency)
        # We always cache, even if price is None (negative caching)
        _PRICE_CACHE[cache_key] = {"price": price, "timestamp": datetime.now()}
        return price

    def _fetch_price_from_api(self, token_id: str, vs_currency: str) -> Optional[float]:
        """Fetch price from API with retries and key fallback."""
        max_retries = 2
        for attempt in range(max_retries + 1):
            try:
                base_url = self.BASE_URL
                url = f"{base_url}/simple/price"
                params = {"ids": token_id, "vs_currencies": vs_currency}
                headers = {}
                if self.api_key:
                    headers["x-cg-demo-api-key"] = self.api_key

                # Use session instead of direct requests
                response = self.session.get(url, params=params, headers=headers, timeout=10)

                if response.status_code == 401 and self.api_key:
                    logger.warning("CoinGecko API key invalid (401). Retrying without key...")
                    self.api_key = None
                    headers.pop("x-cg-demo-api-key", None)
                    # Re-run with base URL
                    url = f"{self.BASE_URL}/simple/price"
                    response = self.session.get(url, params=params, headers=headers, timeout=10)

                if response.status_code == 429:
                    logger.warning(
                        f"CoinGecko rate limit reached (429) for {token_id}. "
                        f"Attempt {attempt + 1}/{max_retries + 1}"
                    )
                    if attempt < max_retries:
                        time.sleep(2 * (attempt + 1))
                        continue
                    return None

                response.raise_for_status()
                data = response.json()

                if token_id in data and vs_currency in data[token_id]:
                    return float(data[token_id][vs_currency])

                # If we got response but price not found, it's likely a wrong ID
                logger.debug(f"Price for {token_id} in {vs_currency} not found in response: {data}")
                return None

            except Exception as e:
                # Only log error on last attempt to avoid spamming
                if attempt == max_retries:
                    logger.error(f"Failed to fetch price for {token_id}: {e}")
                if attempt < max_retries:
                    time.sleep(1)
                    continue
        return None
