"""Service Registry subgraph queries."""

import time
from typing import Dict, List, Optional

from loguru import logger

from iwa.plugins.olas.subgraph import queries
from iwa.plugins.olas.subgraph.client import GraphQLClient
from iwa.plugins.olas.subgraph.endpoints import SubgraphType, get_available_chains, get_endpoint
from iwa.plugins.olas.subgraph.models import (
    SubgraphDailyActivity,
    SubgraphGlobalStats,
    SubgraphMultisig,
    SubgraphService,
)


class ServiceRegistrySubgraph:
    """Query methods for the Service Registry subgraph."""

    def __init__(self, api_key: Optional[str] = None, cache_ttl: int = 300):
        """Initialize with optional API key and cache TTL."""
        self._api_key = api_key
        self._cache_ttl = cache_ttl
        self._clients: Dict[str, GraphQLClient] = {}

    def _client(self, chain: str) -> GraphQLClient:
        """Get or create a GraphQL client for a chain."""
        if chain not in self._clients:
            endpoint = get_endpoint(chain, SubgraphType.SERVICE_REGISTRY, self._api_key)
            if not endpoint:
                raise ValueError(
                    f"No Service Registry endpoint for chain '{chain}'. "
                    f"Available: {get_available_chains(SubgraphType.SERVICE_REGISTRY, self._api_key)}"
                )
            self._clients[chain] = GraphQLClient(endpoint, cache_ttl=self._cache_ttl)
        return self._clients[chain]

    def get_services(
        self,
        chain: str,
        agent_id: Optional[int] = None,
    ) -> List[SubgraphService]:
        """Get all services on a chain, optionally filtered by agent ID.

        Args:
            chain: Chain name (e.g. "gnosis").
            agent_id: Optional agent type ID to filter by.

        Returns:
            List of services.

        """
        client = self._client(chain)

        if agent_id is not None:
            raw = client.query_all(
                queries.SERVICES_BY_AGENT_ID,
                "services",
                variables={"agentId": agent_id},
            )
        else:
            raw = client.query_all(queries.SERVICES_PAGINATED, "services")

        return [SubgraphService.from_subgraph(s, chain=chain) for s in raw]

    def get_service(self, chain: str, service_id: int) -> Optional[SubgraphService]:
        """Get a single service by ID.

        Args:
            chain: Chain name.
            service_id: Service ID.

        Returns:
            Service if found, None otherwise.

        """
        client = self._client(chain)
        data = client.query(queries.SERVICE_BY_ID, variables={"serviceId": str(service_id)})
        svc = data.get("service")
        if not svc:
            return None
        return SubgraphService.from_subgraph(svc, chain=chain)

    def get_services_by_creator(
        self,
        chain: str,
        creator_address: str,
    ) -> List[SubgraphService]:
        """Get all services created by an address.

        Args:
            chain: Chain name.
            creator_address: Creator/owner address.

        Returns:
            List of services.

        """
        client = self._client(chain)
        data = client.query(
            queries.SERVICES_BY_CREATOR,
            variables={"creator": creator_address.lower()},
        )
        creators = data.get("creators", [])
        if not creators:
            return []
        services = creators[0].get("services", [])
        return [
            SubgraphService.from_subgraph(
                {**s, "creator": {"id": creator_address.lower()}},
                chain=chain,
            )
            for s in services
        ]

    def get_service_by_multisig(
        self,
        chain: str,
        multisig_address: str,
    ) -> Optional[SubgraphMultisig]:
        """Find the service that owns a given multisig address.

        Args:
            chain: Chain name.
            multisig_address: Safe multisig address.

        Returns:
            Multisig info with service ID, or None.

        """
        client = self._client(chain)
        data = client.query(
            queries.MULTISIG_LOOKUP,
            variables={"multisig": multisig_address.lower()},
        )
        multisigs = data.get("multisigs", [])
        if not multisigs:
            return None
        return SubgraphMultisig.from_subgraph(multisigs[0])

    def get_daily_activity(
        self,
        chain: str,
        agent_id: int,
        days: int = 30,
    ) -> List[SubgraphDailyActivity]:
        """Get daily agent performance metrics.

        Args:
            chain: Chain name.
            agent_id: Agent type ID.
            days: Number of days to look back.

        Returns:
            List of daily activity snapshots, newest first.

        """
        client = self._client(chain)
        since = int(time.time()) - (days * 86400)
        data = client.query(
            queries.DAILY_AGENT_PERFORMANCE,
            variables={"agentId": agent_id, "since": str(since)},
        )
        return [
            SubgraphDailyActivity.from_subgraph(d)
            for d in data.get("dailyAgentPerformances", [])
        ]

    def get_global_stats(self, chain: str) -> Optional[SubgraphGlobalStats]:
        """Get global protocol stats for a chain.

        Args:
            chain: Chain name.

        Returns:
            Global stats, or None if unavailable.

        """
        client = self._client(chain)
        data = client.query(queries.GLOBAL_STATS)
        globals_list = data.get("globals", [])
        if not globals_list:
            return None
        g = globals_list[0]
        return SubgraphGlobalStats(
            tx_count=int(g.get("txCount", 0)),
            total_operators=int(g.get("totalOperators", 0)),
            last_updated=g.get("lastUpdated"),
        )

    def get_services_all_chains(
        self,
        agent_id: Optional[int] = None,
    ) -> Dict[str, List[SubgraphService]]:
        """Query all available chains for services.

        Args:
            agent_id: Optional agent type ID to filter by.

        Returns:
            Dict mapping chain name to list of services.

        """
        chains = get_available_chains(SubgraphType.SERVICE_REGISTRY, self._api_key)
        result: Dict[str, List[SubgraphService]] = {}
        for chain in chains:
            try:
                result[chain] = self.get_services(chain, agent_id=agent_id)
            except Exception as exc:
                logger.warning(f"Failed to query services on {chain}: {exc}")
                result[chain] = []
        return result

    def close(self) -> None:
        """Close all HTTP sessions."""
        for client in self._clients.values():
            client.close()
        self._clients.clear()
