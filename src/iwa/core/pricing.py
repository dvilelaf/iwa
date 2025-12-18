"""Pricing service module."""

import time
from datetime import datetime, timedelta
from typing import Dict, Optional

import requests
from loguru import logger

from iwa.core.settings import settings


class PriceService:
    """Service to fetch token prices from CoinGecko."""

    BASE_URL = "https://api.coingecko.com/api/v3"

    def __init__(self, cache_ttl_minutes: int = 5):
        """Initialize PriceService."""
        self.settings = settings
        self.cache: Dict[str, Dict] = {}  # {id_currency: {"price": float, "timestamp": datetime}}
        self.cache_ttl = timedelta(minutes=cache_ttl_minutes)
        self.api_key = (
            self.settings.coingecko_api_key.get_secret_value()
            if self.settings.coingecko_api_key
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

        # Check cache
        if cache_key in self.cache:
            entry = self.cache[cache_key]
            if datetime.now() - entry["timestamp"] < self.cache_ttl:
                return entry["price"]

        # Fetch from API with 2 retries
        max_retries = 2
        for attempt in range(max_retries + 1):
            try:
                url = f"{self.BASE_URL}/simple/price"
                params = {"ids": token_id, "vs_currencies": vs_currency}
                headers = {}
                if self.api_key:
                    headers["x-cg-demo-api-key"] = self.api_key

                response = requests.get(url, params=params, headers=headers, timeout=10)

                if response.status_code == 429:
                    logger.warning(
                        f"CoinGecko rate limit reached (429) for {token_id}. Attempt {attempt + 1}/{max_retries + 1}"
                    )
                    if attempt < max_retries:
                        time.sleep(2 * (attempt + 1))
                        continue
                    return None

                response.raise_for_status()

                data = response.json()
                if token_id in data and vs_currency in data[token_id]:
                    price = float(data[token_id][vs_currency])

                    # Update cache
                    self.cache[cache_key] = {"price": price, "timestamp": datetime.now()}
                    return price
                else:
                    logger.warning(
                        f"Price for {token_id} in {vs_currency} not found in response: {data}"
                    )
                    # Don't cache None, might be a temporary hiccup
                    return None

            except Exception as e:
                logger.error(f"Failed to fetch price for {token_id} (Attempt {attempt + 1}): {e}")
                if attempt < max_retries:
                    time.sleep(1)
                    continue
                return None
        return None
