"""Pricing service module."""

import time
from datetime import datetime, timedelta
from typing import Dict, Optional

import requests
from loguru import logger

from iwa.core.secrets import secrets

# Global cache shared across all PriceService instances
_PRICE_CACHE: Dict[str, Dict] = {}
_CACHE_TTL = timedelta(minutes=30)


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

    def get_token_price(self, token_id: str, vs_currency: str = "eur") -> Optional[float]:
        """Get token price in specified currency.

        Args:
            token_id: CoinGecko token ID (e.g. 'ethereum', 'gnosis', 'olas')
            vs_currency: Target currency (default 'eur')

        Returns:
            Price as float, or None if fetch failed.

        """
        cache_key = f"{token_id}_{vs_currency}"

        # Check global cache
        if cache_key in _PRICE_CACHE:
            entry = _PRICE_CACHE[cache_key]
            if datetime.now() - entry["timestamp"] < _CACHE_TTL:
                return entry["price"]

        price = self._fetch_price_from_api(token_id, vs_currency)
        if price is not None:
            _PRICE_CACHE[cache_key] = {"price": price, "timestamp": datetime.now()}
        return price

    def _fetch_price_from_api(self, token_id: str, vs_currency: str) -> Optional[float]:
        """Fetch price from API with retries and key fallback."""
        max_retries = 2
        for attempt in range(max_retries + 1):
            try:
                url = f"{self.BASE_URL}/simple/price"
                params = {"ids": token_id, "vs_currencies": vs_currency}
                headers = {}
                if self.api_key:
                    headers["x-cg-demo-api-key"] = self.api_key

                response = requests.get(url, params=params, headers=headers, timeout=10)

                if response.status_code == 401 and self.api_key:
                    logger.warning("CoinGecko API key invalid (401). Retrying without key...")
                    self.api_key = None
                    headers.pop("x-cg-demo-api-key", None)
                    response = requests.get(url, params=params, headers=headers, timeout=10)

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

                logger.warning(
                    f"Price for {token_id} in {vs_currency} not found in response: {data}"
                )
                return None

            except Exception as e:
                logger.error(f"Failed to fetch price for {token_id} (Attempt {attempt + 1}): {e}")
                if attempt < max_retries:
                    time.sleep(1)
                    continue
        return None
