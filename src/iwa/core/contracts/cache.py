"""Contract instance cache to reduce RPC calls during instantiation."""

import os
import time
from threading import Lock
from typing import Any, Dict, Optional, Type, TypeVar

from loguru import logger

T = TypeVar("T")


class ContractCache:
    """Singleton cache for contract instances.

    Stores contract instances keyed by (class, address, chain) to prevent
    redundant instantiation and the associated RPC calls.
    """

    _instance = None
    _lock = Lock()

    def __new__(cls) -> "ContractCache":
        """Ensure singleton instance."""
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(ContractCache, cls).__new__(cls)
                cls._instance._contracts: Dict[str, Any] = {}
                cls._instance._creation_times: Dict[str, float] = {}

                # Default TTL: 1 hour, configurable via env var
                env_ttl = os.environ.get("IWA_CONTRACT_CACHE_TTL")
                try:
                    cls._instance.ttl = int(env_ttl) if env_ttl else 3600
                except ValueError:
                    cls._instance.ttl = 3600
                    logger.warning(f"Invalid IWA_CONTRACT_CACHE_TTL value: {env_ttl}. Using 3600.")

        return cls._instance

    def get_contract(
        self,
        contract_cls: Type[T],
        address: str,
        chain_name: str,
        ttl: Optional[int] = None,
    ) -> T:
        """Get a cached contract instance or create a new one.

        Args:
            contract_cls: The contract class to instantiate.
            address: The contract address.
            chain_name: The chain name.
            ttl: Optional TTL override in seconds.

        Returns:
            The contract instance (cached or new).

        """
        if not address:
            raise ValueError("Address is required for contract caching")

        key = self._make_key(contract_cls, address, chain_name)
        now = time.time()
        expiry = ttl if ttl is not None else self.ttl

        with self._lock:
            # Check if cached and valid
            if key in self._contracts:
                created_at = self._creation_times.get(key, 0)
                if now - created_at < expiry:
                    return self._contracts[key]
                else:
                    logger.debug(f"Contract cache expired for {key}")
                    del self._contracts[key]
                    del self._creation_times[key]

            # Create new instance
            logger.debug(f"Creating new cached contract instance for {key}")
            instance = contract_cls(address, chain_name=chain_name)
            self._contracts[key] = instance
            self._creation_times[key] = now
            return instance

    def get_if_cached(
        self,
        contract_cls: Type[T],
        address: str,
        chain_name: str,
    ) -> Optional[T]:
        """Get a cached contract instance if it exists and is valid.

        Does NOT create a new instance if not found.
        """
        if not address:
            return None

        key = self._make_key(contract_cls, address, chain_name)
        now = time.time()

        with self._lock:
            if key in self._contracts:
                # Check TTL
                created_at = self._creation_times.get(key, 0)
                if now - created_at < self.ttl:
                    return self._contracts[key]
                else:
                    # Expired, clean up
                    del self._contracts[key]
                    del self._creation_times[key]
        return None

    def _make_key(self, contract_cls: Type, address: str, chain_name: str) -> str:
        """Create a unique cache key."""
        return f"{contract_cls.__name__}:{chain_name.lower()}:{address.lower()}"

    def clear(self) -> None:
        """Clear all cached contracts."""
        with self._lock:
            self._contracts.clear()
            self._creation_times.clear()
            logger.debug("Contract cache cleared")

    def invalidate(self, contract_cls: Type, address: str, chain_name: str) -> None:
        """Invalidate a specific contract in the cache."""
        key = self._make_key(contract_cls, address, chain_name)
        with self._lock:
            if key in self._contracts:
                del self._contracts[key]
                del self._creation_times[key]
                logger.debug(f"Invalidated cache for {key}")
