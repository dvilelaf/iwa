"""Response cache for web API endpoints to reduce RPC calls."""

import os
import time
from threading import Lock
from typing import Any, Callable, Dict, Optional, TypeVar

from loguru import logger

T = TypeVar("T")


class ResponseCache:
    """Singleton TTL cache for API response data.

    Caches expensive query results (service status, balances, etc.)
    to prevent redundant RPC calls when refreshing the web UI.
    """

    _instance: Optional["ResponseCache"] = None
    _lock = Lock()

    def __new__(cls) -> "ResponseCache":
        """Ensure singleton instance."""
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._cache: Dict[str, Any] = {}
                cls._instance._timestamps: Dict[str, float] = {}
                cls._instance._enabled = os.environ.get("IWA_RESPONSE_CACHE", "1") != "0"
                cls._instance._invalidation_callbacks: list = []
        return cls._instance

    def on_invalidate(self, callback: Callable[[Optional[str]], None]) -> None:
        """Register a callback to be notified when cache entries are invalidated.

        Args:
            callback: Function that receives the invalidation pattern (or None for full clear).

        """
        self._invalidation_callbacks.append(callback)

    def get(self, key: str, ttl_seconds: int = 60) -> Optional[Any]:
        """Get a cached value if it exists and hasn't expired.

        Args:
            key: Cache key.
            ttl_seconds: Time-to-live in seconds.

        Returns:
            Cached value or None if not found/expired.

        """
        if not self._enabled:
            return None

        with self._lock:
            if key in self._cache:
                created_at = self._timestamps.get(key, 0)
                if time.time() - created_at < ttl_seconds:
                    logger.debug(f"Cache HIT: {key}")
                    return self._cache[key]
                else:
                    # Expired
                    del self._cache[key]
                    del self._timestamps[key]
        return None

    def set(self, key: str, value: Any) -> None:
        """Store a value in the cache.

        Args:
            key: Cache key.
            value: Value to cache.

        """
        if not self._enabled:
            return

        with self._lock:
            self._cache[key] = value
            self._timestamps[key] = time.time()
            logger.debug(f"Cache SET: {key}")

    def invalidate(self, pattern: Optional[str] = None) -> None:
        """Invalidate cache entries and notify registered callbacks.

        Args:
            pattern: If provided, invalidate keys containing this pattern.
                    If None, clear entire cache.

        """
        with self._lock:
            if pattern is None:
                self._cache.clear()
                self._timestamps.clear()
                logger.debug("Cache cleared")
            else:
                keys_to_remove = [k for k in self._cache if pattern in k]
                for key in keys_to_remove:
                    del self._cache[key]
                    del self._timestamps[key]
                if keys_to_remove:
                    logger.debug(f"Cache invalidated {len(keys_to_remove)} entries matching '{pattern}'")

        for cb in self._invalidation_callbacks:
            try:
                cb(pattern)
            except Exception:
                pass

    def get_or_compute(
        self,
        key: str,
        compute_fn: Callable[[], T],
        ttl_seconds: int = 60,
    ) -> T:
        """Get cached value or compute and cache it.

        Args:
            key: Cache key.
            compute_fn: Function to compute the value if not cached.
            ttl_seconds: Time-to-live in seconds.

        Returns:
            Cached or computed value.

        """
        cached = self.get(key, ttl_seconds)
        if cached is not None:
            return cached

        value = compute_fn()
        self.set(key, value)
        return value


# Singleton accessor
response_cache = ResponseCache()


# TTL constants for different data types (in seconds)
class CacheTTL:
    """Standard TTL values for different data types."""

    # Service state changes infrequently (after user actions)
    SERVICE_STATE = 120  # 2 minutes

    # Staking status (epoch info, rewards) changes slowly
    STAKING_STATUS = 60  # 1 minute

    # Balances can change via external transactions
    BALANCES = 30  # 30 seconds

    # Account list rarely changes
    ACCOUNTS = 300  # 5 minutes

    # Basic service info (config-based) rarely changes
    SERVICE_BASIC = 120  # 2 minutes
