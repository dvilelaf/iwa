"""Pricing service module."""

from datetime import datetime, timedelta
from typing import Dict, Optional

import requests
from loguru import logger

from iwa.core.models import Secrets


class PriceService:
    """Service to fetch token prices from CoinGecko."""

    BASE_URL = "https://api.coingecko.com/api/v3"

    def __init__(self, cache_ttl_minutes: int = 5):
        """Initialize PriceService."""
        self.secrets = Secrets()
        self.cache: Dict[str, Dict] = {}  # {id_currency: {"price": float, "timestamp": datetime}}
        self.cache_ttl = timedelta(minutes=cache_ttl_minutes)
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

        # Check cache
        if cache_key in self.cache:
            entry = self.cache[cache_key]
            if datetime.now() - entry["timestamp"] < self.cache_ttl:
                return entry["price"]

        # Fetch from API
        try:
            url = f"{self.BASE_URL}/simple/price"
            params = {"ids": token_id, "vs_currencies": vs_currency}
            headers = {}
            if self.api_key:
                headers["x-cg-demo-api-key"] = self.api_key

            response = requests.get(url, params=params, headers=headers, timeout=10)
            response.raise_for_status()

            data = response.json()
            if token_id in data and vs_currency in data[token_id]:
                price = data[token_id][vs_currency]

                # Update cache
                self.cache[cache_key] = {"price": price, "timestamp": datetime.now()}
                return price
            else:
                logger.warning(
                    f"Price for {token_id} in {vs_currency} not found in response: {data}"
                )
                return None

        except Exception as e:
            logger.error(f"Failed to fetch price for {token_id}: {e}")
            return None
