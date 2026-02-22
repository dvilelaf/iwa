"""OLAS Subgraph client — query services, staking, and protocol data.

Usage::

    from iwa.plugins.olas.subgraph import SubgraphClient

    client = SubgraphClient()

    # Service Registry
    services = client.registry.get_services("gnosis", agent_id=25)
    service = client.registry.get_service("gnosis", 2679)

    # Staking
    contracts = client.staking.get_all_contracts("gnosis")
    rewards = client.staking.get_service_rewards_history("gnosis", 2679)

    # Protocol Registry (Ethereum)
    info = client.protocol.get_service_by_id(10)

"""

from typing import Optional

from iwa.core.secrets import secrets
from iwa.plugins.olas.subgraph.client import SubgraphError, clear_cache
from iwa.plugins.olas.subgraph.protocol_registry import ProtocolRegistrySubgraph
from iwa.plugins.olas.subgraph.service_registry import ServiceRegistrySubgraph
from iwa.plugins.olas.subgraph.staking import StakingSubgraph

__all__ = [
    "SubgraphClient",
    "SubgraphError",
    "clear_cache",
]


class SubgraphClient:
    """Unified client for all OLAS subgraphs.

    Reads the TheGraph API key from secrets automatically.
    Falls back to free proxy endpoints when no key is available.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        cache_ttl: int = 300,
    ):
        """Initialize SubgraphClient.

        Args:
            api_key: TheGraph API key. If None, reads from secrets.
            cache_ttl: Cache TTL in seconds (default 5 minutes).

        """
        if api_key is None:
            secret = getattr(secrets, "subgraph_api_key", None)
            if secret:
                api_key = secret.get_secret_value()

        self._api_key = api_key
        self._cache_ttl = cache_ttl

        self._registry: Optional[ServiceRegistrySubgraph] = None
        self._staking: Optional[StakingSubgraph] = None
        self._protocol: Optional[ProtocolRegistrySubgraph] = None

    @property
    def registry(self) -> ServiceRegistrySubgraph:
        """Service Registry subgraph queries."""
        if self._registry is None:
            self._registry = ServiceRegistrySubgraph(self._api_key, self._cache_ttl)
        return self._registry

    @property
    def staking(self) -> StakingSubgraph:
        """Staking subgraph queries."""
        if self._staking is None:
            self._staking = StakingSubgraph(self._api_key, self._cache_ttl)
        return self._staking

    @property
    def protocol(self) -> ProtocolRegistrySubgraph:
        """Protocol Registry subgraph queries (Ethereum only)."""
        if self._protocol is None:
            self._protocol = ProtocolRegistrySubgraph(self._api_key, self._cache_ttl)
        return self._protocol

    def close(self) -> None:
        """Close all HTTP sessions."""
        if self._registry:
            self._registry.close()
        if self._staking:
            self._staking.close()
        if self._protocol:
            self._protocol.close()
