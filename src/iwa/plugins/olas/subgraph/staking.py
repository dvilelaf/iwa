"""Staking subgraph queries."""

from typing import Dict, List, Optional

from loguru import logger

from iwa.plugins.olas.subgraph import queries
from iwa.plugins.olas.subgraph.client import GraphQLClient
from iwa.plugins.olas.subgraph.endpoints import SubgraphType, get_available_chains, get_endpoint
from iwa.plugins.olas.subgraph.models import (
    SubgraphRewardEpoch,
    SubgraphServiceEvents,
    SubgraphStakedService,
    SubgraphStakingContract,
    SubgraphStakingGlobal,
)


class StakingSubgraph:
    """Query methods for the Staking subgraph."""

    def __init__(self, api_key: Optional[str] = None, cache_ttl: int = 300):
        """Initialize with optional API key and cache TTL."""
        self._api_key = api_key
        self._cache_ttl = cache_ttl
        self._clients: Dict[str, GraphQLClient] = {}

    def _client(self, chain: str) -> GraphQLClient:
        """Get or create a GraphQL client for a chain."""
        if chain not in self._clients:
            endpoint = get_endpoint(chain, SubgraphType.STAKING, self._api_key)
            if not endpoint:
                raise ValueError(
                    f"No Staking endpoint for chain '{chain}'. "
                    f"Available: {get_available_chains(SubgraphType.STAKING, self._api_key)}"
                )
            self._clients[chain] = GraphQLClient(endpoint, cache_ttl=self._cache_ttl)
        return self._clients[chain]

    def get_all_contracts(
        self,
        chain: str,
        agent_id: Optional[int] = None,
    ) -> List[SubgraphStakingContract]:
        """Get all staking contracts, optionally filtered by agent ID.

        Args:
            chain: Chain name.
            agent_id: Optional agent type ID to filter by.

        Returns:
            List of staking contracts.

        """
        client = self._client(chain)

        if agent_id is not None:
            raw = client.query_all(
                queries.STAKING_CONTRACTS_BY_AGENT_ID,
                "stakingContracts",
                variables={"agentId": str(agent_id)},
            )
        else:
            raw = client.query_all(queries.STAKING_CONTRACTS_PAGINATED, "stakingContracts")

        return [SubgraphStakingContract.from_subgraph(c, chain=chain) for c in raw]

    def get_contracts_with_free_slots(
        self,
        chain: str,
        agent_id: Optional[int] = None,
    ) -> List[SubgraphStakingContract]:
        """Get staking contracts that have available capacity.

        Note: The subgraph stores contracts as immutable entities, so we
        cannot directly query the current number of staked services.
        This method fetches all contracts and the caller should cross-reference
        with ``get_active_services()`` or on-chain data for slot availability.

        Args:
            chain: Chain name.
            agent_id: Optional agent type ID to filter by.

        Returns:
            List of staking contracts (all — caller filters by capacity).

        """
        return self.get_all_contracts(chain, agent_id=agent_id)

    def get_service_staking_info(
        self,
        chain: str,
        service_id: int,
    ) -> Optional[SubgraphStakedService]:
        """Get staking info for a specific service.

        Args:
            chain: Chain name.
            service_id: Service ID.

        Returns:
            Staked service info, or None.

        """
        client = self._client(chain)
        data = client.query(
            queries.STAKING_SERVICE_INFO,
            variables={"serviceId": str(service_id)},
        )
        svc = data.get("service")
        if not svc:
            return None
        return SubgraphStakedService.from_subgraph(svc)

    def get_service_rewards_history(
        self,
        chain: str,
        service_id: int,
    ) -> List[SubgraphRewardEpoch]:
        """Get per-epoch rewards history for a service.

        Args:
            chain: Chain name.
            service_id: Service ID.

        Returns:
            List of reward epochs, newest first.

        """
        client = self._client(chain)
        data = client.query(
            queries.STAKING_REWARDS_HISTORY,
            variables={"serviceId": str(service_id)},
        )
        return [
            SubgraphRewardEpoch.from_subgraph(r)
            for r in data.get("serviceRewardsHistories", [])
        ]

    def get_service_events(
        self,
        chain: str,
        service_id: int,
    ) -> SubgraphServiceEvents:
        """Get staking lifecycle events for a service.

        Fetches staked, unstaked, inactivity warnings, and eviction events.

        Args:
            chain: Chain name.
            service_id: Service ID.

        Returns:
            Aggregated service events.

        """
        client = self._client(chain)
        sid = str(service_id)

        staked = client.query(
            queries.SERVICE_STAKED_EVENTS,
            variables={"serviceId": sid},
            cache_ttl=0,
        ).get("serviceStakeds", [])

        unstaked = client.query(
            queries.SERVICE_UNSTAKED_EVENTS,
            variables={"serviceId": sid},
            cache_ttl=0,
        ).get("serviceUnstakeds", [])

        warnings = client.query(
            queries.SERVICE_INACTIVITY_WARNINGS,
            variables={"serviceId": sid},
            cache_ttl=0,
        ).get("serviceInactivityWarnings", [])

        evictions = client.query(
            queries.SERVICES_EVICTED,
            variables={"serviceId": sid},
            cache_ttl=0,
        ).get("servicesEvicteds", [])

        return SubgraphServiceEvents(
            service_id=service_id,
            staked=staked,
            unstaked=unstaked,
            inactivity_warnings=warnings,
            evictions=evictions,
        )

    def get_active_services(
        self,
        chain: str,
        contract_address: str,
    ) -> List[int]:
        """Get service IDs currently active in a staking contract.

        Args:
            chain: Chain name.
            contract_address: Staking contract address.

        Returns:
            List of active service IDs.

        """
        client = self._client(chain)
        data = client.query(
            queries.ACTIVE_SERVICE_EPOCH,
            variables={"contractAddress": contract_address.lower()},
        )
        epochs = data.get("activeServiceEpoches", [])
        if not epochs:
            return []
        return [int(sid) for sid in (epochs[0].get("activeServiceIds") or [])]

    def get_global_stats(self, chain: str) -> Optional[SubgraphStakingGlobal]:
        """Get global staking stats for a chain.

        Args:
            chain: Chain name.

        Returns:
            Global staking stats, or None.

        """
        client = self._client(chain)
        data = client.query(queries.STAKING_GLOBAL)
        globals_list = data.get("globals", [])
        if not globals_list:
            return None
        g = globals_list[0]
        return SubgraphStakingGlobal(
            cumulative_olas_staked=int(g.get("cumulativeOlasStaked", 0)),
            cumulative_olas_unstaked=int(g.get("cumulativeOlasUnstaked", 0)),
            current_olas_staked=int(g.get("currentOlasStaked", 0)),
            total_rewards=int(g.get("totalRewards", 0)),
        )

    def get_all_contracts_all_chains(
        self,
        agent_id: Optional[int] = None,
    ) -> Dict[str, List[SubgraphStakingContract]]:
        """Query all available chains for staking contracts.

        Args:
            agent_id: Optional agent type ID to filter by.

        Returns:
            Dict mapping chain name to list of staking contracts.

        """
        chains = get_available_chains(SubgraphType.STAKING, self._api_key)
        result: Dict[str, List[SubgraphStakingContract]] = {}
        for chain in chains:
            try:
                result[chain] = self.get_all_contracts(chain, agent_id=agent_id)
            except Exception as exc:
                logger.warning(f"Failed to query staking contracts on {chain}: {exc}")
                result[chain] = []
        return result

    def close(self) -> None:
        """Close all HTTP sessions."""
        for client in self._clients.values():
            client.close()
        self._clients.clear()
