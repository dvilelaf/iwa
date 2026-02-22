"""Tokenomics subgraph queries."""

from typing import Dict, List, Optional

from loguru import logger

from iwa.plugins.olas.subgraph import queries
from iwa.plugins.olas.subgraph.client import GraphQLClient
from iwa.plugins.olas.subgraph.endpoints import SubgraphType, get_available_chains, get_endpoint
from iwa.plugins.olas.subgraph.models import (
    SubgraphTokenHolder,
    SubgraphTokenInfo,
    SubgraphTransfer,
)


class TokenomicsSubgraph:
    """Query methods for the Tokenomics subgraph."""

    def __init__(self, api_key: Optional[str] = None, cache_ttl: int = 300):
        """Initialize with optional API key and cache TTL."""
        self._api_key = api_key
        self._cache_ttl = cache_ttl
        self._clients: Dict[str, GraphQLClient] = {}

    def _client(self, chain: str) -> GraphQLClient:
        """Get or create a GraphQL client for a chain."""
        if chain not in self._clients:
            endpoint = get_endpoint(chain, SubgraphType.TOKENOMICS, self._api_key)
            if not endpoint:
                raise ValueError(
                    f"No Tokenomics endpoint for chain '{chain}'. "
                    f"Available: {get_available_chains(SubgraphType.TOKENOMICS, self._api_key)}"
                )
            self._clients[chain] = GraphQLClient(endpoint, cache_ttl=self._cache_ttl)
        return self._clients[chain]

    def get_token_info(self, chain: str) -> Optional[SubgraphTokenInfo]:
        """Get OLAS token info (balance and holder count).

        Args:
            chain: Chain name.

        Returns:
            Token info, or None if not available.

        """
        client = self._client(chain)
        data = client.query(queries.TOKENOMICS_TOKEN)
        tokens = data.get("tokens", [])
        if not tokens:
            return None
        return SubgraphTokenInfo.from_subgraph(tokens[0])

    def get_top_holders(
        self, chain: str, limit: int = 100
    ) -> List[SubgraphTokenHolder]:
        """Get top token holders by balance.

        Args:
            chain: Chain name.
            limit: Maximum number of holders to return.

        Returns:
            List of token holders sorted by balance descending.

        """
        client = self._client(chain)
        data = client.query(
            queries.TOKENOMICS_TOP_HOLDERS, variables={"limit": limit}
        )
        return [
            SubgraphTokenHolder.from_subgraph(h)
            for h in data.get("tokenHolders", [])
        ]

    def get_recent_transfers(
        self, chain: str, limit: int = 100
    ) -> List[SubgraphTransfer]:
        """Get most recent token transfers.

        Args:
            chain: Chain name.
            limit: Maximum number of transfers to return.

        Returns:
            List of transfers sorted by timestamp descending.

        """
        client = self._client(chain)
        data = client.query(
            queries.TOKENOMICS_RECENT_TRANSFERS, variables={"limit": limit}
        )
        return [
            SubgraphTransfer.from_subgraph(t) for t in data.get("transfers", [])
        ]

    def get_all_data(
        self, chain: str, holders_limit: int = 100, transfers_limit: int = 100
    ) -> Dict:
        """Get all tokenomics data for a chain in one call.

        Args:
            chain: Chain name.
            holders_limit: Max holders to return.
            transfers_limit: Max transfers to return.

        Returns:
            Dict with token_info, top_holders, and recent_transfers.

        """
        token_info = None
        top_holders: List[SubgraphTokenHolder] = []
        recent_transfers: List[SubgraphTransfer] = []

        try:
            token_info = self.get_token_info(chain)
        except Exception as exc:
            logger.warning(f"Tokenomics token info error for {chain}: {exc}")

        try:
            top_holders = self.get_top_holders(chain, limit=holders_limit)
        except Exception as exc:
            logger.warning(f"Tokenomics holders error for {chain}: {exc}")

        try:
            recent_transfers = self.get_recent_transfers(chain, limit=transfers_limit)
        except Exception as exc:
            logger.warning(f"Tokenomics transfers error for {chain}: {exc}")

        return {
            "token_info": token_info,
            "top_holders": top_holders,
            "recent_transfers": recent_transfers,
        }

    def close(self) -> None:
        """Close all HTTP sessions."""
        for client in self._clients.values():
            client.close()
        self._clients.clear()
