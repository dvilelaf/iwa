"""Protocol Registry subgraph queries (Ethereum only)."""

from typing import List, Optional

from iwa.plugins.olas.subgraph import queries
from iwa.plugins.olas.subgraph.client import GraphQLClient
from iwa.plugins.olas.subgraph.endpoints import SubgraphType, get_endpoint
from iwa.plugins.olas.subgraph.models import SubgraphProtocolGlobal, SubgraphProtocolService


class ProtocolRegistrySubgraph:
    """Query methods for the Autonolas Protocol Registry subgraph (Ethereum)."""

    def __init__(self, api_key: Optional[str] = None, cache_ttl: int = 300):
        """Initialize with optional API key and cache TTL."""
        self._api_key = api_key
        self._cache_ttl = cache_ttl
        self._client: Optional[GraphQLClient] = None

    def _get_client(self) -> GraphQLClient:
        """Get or create the GraphQL client."""
        if self._client is None:
            endpoint = get_endpoint("ethereum", SubgraphType.PROTOCOL_REGISTRY, self._api_key)
            if not endpoint:
                raise ValueError("No Protocol Registry endpoint available for Ethereum")
            self._client = GraphQLClient(endpoint, cache_ttl=self._cache_ttl)
        return self._client

    def get_services(self) -> List[SubgraphProtocolService]:
        """Get all registered services.

        Returns:
            List of protocol services.

        """
        client = self._get_client()
        raw = client.query_all(queries.PROTOCOL_SERVICES_PAGINATED, "services")
        return [SubgraphProtocolService.from_subgraph(s) for s in raw]

    def get_service_by_id(self, service_id: int) -> Optional[SubgraphProtocolService]:
        """Get a service by its numeric ID.

        Args:
            service_id: On-chain service ID.

        Returns:
            Protocol service, or None.

        """
        client = self._get_client()
        data = client.query(
            queries.PROTOCOL_SERVICE_BY_ID,
            variables={"serviceId": str(service_id)},
        )
        services = data.get("services", [])
        if not services:
            return None
        return SubgraphProtocolService.from_subgraph(services[0])

    def search_services(self, term: str) -> List[SubgraphProtocolService]:
        """Search services by public ID substring.

        Note: The subgraph does not support text search natively.
        This fetches all services and filters client-side.

        Args:
            term: Search term to match against publicId.

        Returns:
            Matching services.

        """
        all_services = self.get_services()
        term_lower = term.lower()
        return [s for s in all_services if term_lower in s.public_id.lower()]

    def get_global_stats(self) -> Optional[SubgraphProtocolGlobal]:
        """Get global protocol stats.

        Returns:
            Global stats, or None.

        """
        client = self._get_client()
        data = client.query(queries.PROTOCOL_GLOBAL)
        globals_list = data.get("globals", [])
        if not globals_list:
            return None
        g = globals_list[0]
        return SubgraphProtocolGlobal(
            total_builders=int(g.get("totalBuilders", 0)),
            total_agents=int(g.get("totalAgents", 0)),
            total_components=int(g.get("totalComponents", 0)),
            total_services=int(g.get("totalServices", 0)),
        )

    def close(self) -> None:
        """Close the HTTP session."""
        if self._client:
            self._client.close()
            self._client = None
