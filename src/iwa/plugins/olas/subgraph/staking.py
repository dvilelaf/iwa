"""Staking subgraph queries."""

from datetime import datetime, timezone
from typing import Dict, List, Optional

from loguru import logger

from iwa.plugins.olas.subgraph import queries
from iwa.plugins.olas.subgraph.client import GraphQLClient
from iwa.plugins.olas.subgraph.endpoints import SubgraphType, get_available_chains, get_endpoint
from iwa.plugins.olas.subgraph.models import (
    SubgraphCheckpoint,
    SubgraphDailyStakingTrend,
    SubgraphDeposit,
    SubgraphRewardClaim,
    SubgraphServiceEvents,
    SubgraphStakedService,
    SubgraphStakingContract,
    SubgraphStakingEvent,
    SubgraphStakingGlobal,
    SubgraphWithdraw,
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

    def get_service_reward_claims(
        self,
        chain: str,
        service_id: int,
    ) -> List[SubgraphRewardClaim]:
        """Get reward claims for a specific service.

        Args:
            chain: Chain name.
            service_id: Service ID.

        Returns:
            List of reward claims, newest first.

        """
        client = self._client(chain)
        data = client.query(
            queries.STAKING_REWARD_CLAIMS_BY_SERVICE,
            variables={"serviceId": str(service_id)},
        )
        return [
            SubgraphRewardClaim.from_subgraph(r)
            for r in data.get("rewardClaimeds", [])
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

        Uses the latest checkpoint for the given contract address.

        Args:
            chain: Chain name.
            contract_address: Staking contract address.

        Returns:
            List of active service IDs.

        """
        client = self._client(chain)
        data = client.query(
            queries.ACTIVE_SERVICE_CHECKPOINT,
            variables={"contractAddress": contract_address.lower()},
        )
        checkpoints = data.get("checkpoints", [])
        if not checkpoints:
            return []
        return [int(sid) for sid in (checkpoints[0].get("serviceIds") or [])]

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

    def get_checkpoints(
        self, chain: str, limit: int = 100
    ) -> List[SubgraphCheckpoint]:
        """Get recent checkpoints."""
        client = self._client(chain)
        data = client.query(queries.STAKING_CHECKPOINTS, variables={"limit": limit})
        return [SubgraphCheckpoint.from_subgraph(c) for c in data.get("checkpoints", [])]

    def get_deposits(self, chain: str, limit: int = 100) -> List[SubgraphDeposit]:
        """Get recent deposits."""
        client = self._client(chain)
        data = client.query(queries.STAKING_DEPOSITS, variables={"limit": limit})
        return [SubgraphDeposit.from_subgraph(d) for d in data.get("deposits", [])]

    def get_withdrawals(self, chain: str, limit: int = 100) -> List[SubgraphWithdraw]:
        """Get recent withdrawals."""
        client = self._client(chain)
        data = client.query(queries.STAKING_WITHDRAWS, variables={"limit": limit})
        return [SubgraphWithdraw.from_subgraph(w) for w in data.get("withdraws", [])]

    def get_reward_claims(
        self, chain: str, limit: int = 100
    ) -> List[SubgraphRewardClaim]:
        """Get recent reward claims."""
        client = self._client(chain)
        data = client.query(queries.STAKING_REWARD_CLAIMS, variables={"limit": limit})
        return [SubgraphRewardClaim.from_subgraph(r) for r in data.get("rewardClaimeds", [])]

    def get_daily_trends(
        self, chain: str, limit: int = 90
    ) -> List[SubgraphDailyStakingTrend]:
        """Get daily staking trends."""
        client = self._client(chain)
        data = client.query(queries.STAKING_DAILY_TRENDS, variables={"limit": limit})
        return [
            SubgraphDailyStakingTrend.from_subgraph(d)
            for d in data.get("cumulativeDailyStakingGlobals", [])
        ]

    def get_recent_events(
        self, chain: str, limit: int = 100
    ) -> List[SubgraphStakingEvent]:
        """Get all staking lifecycle events merged and sorted by timestamp."""
        client = self._client(chain)
        events: List[SubgraphStakingEvent] = []

        staked = client.query(
            queries.STAKING_SERVICE_STAKED_RECENT, variables={"limit": limit}
        ).get("serviceStakeds", [])
        for e in staked:
            events.append(SubgraphStakingEvent(
                event_type="staked", epoch=int(e.get("epoch", 0)),
                service_id=int(e.get("serviceId", 0)),
                owner=e.get("owner", ""), multisig=e.get("multisig", ""),
                block_timestamp=e.get("blockTimestamp"),
                transaction_hash=e.get("transactionHash", ""),
            ))

        unstaked = client.query(
            queries.STAKING_SERVICE_UNSTAKED_RECENT, variables={"limit": limit}
        ).get("serviceUnstakeds", [])
        for e in unstaked:
            events.append(SubgraphStakingEvent(
                event_type="unstaked", epoch=int(e.get("epoch", 0)),
                service_id=int(e.get("serviceId", 0)),
                owner=e.get("owner", ""), multisig=e.get("multisig", ""),
                amount=int(e.get("reward", 0)),
                block_timestamp=e.get("blockTimestamp"),
                transaction_hash=e.get("transactionHash", ""),
            ))

        inactivity = client.query(
            queries.STAKING_SERVICE_INACTIVITY_RECENT, variables={"limit": limit}
        ).get("serviceInactivityWarnings", [])
        for e in inactivity:
            events.append(SubgraphStakingEvent(
                event_type="inactivity", epoch=int(e.get("epoch", 0)),
                service_id=int(e.get("serviceId", 0)),
                amount=int(e.get("serviceInactivity", 0)),
                block_timestamp=e.get("blockTimestamp"),
                transaction_hash=e.get("transactionHash", ""),
            ))

        evictions = client.query(
            queries.STAKING_EVICTIONS_RECENT, variables={"limit": limit}
        ).get("servicesEvicteds", [])
        for e in evictions:
            events.append(SubgraphStakingEvent(
                event_type="evicted", epoch=int(e.get("epoch", 0)),
                service_ids=[int(s) for s in (e.get("serviceIds") or [])],
                block_timestamp=e.get("blockTimestamp"),
                transaction_hash=e.get("transactionHash", ""),
            ))

        # Sort by timestamp descending
        events.sort(
            key=lambda ev: ev.block_timestamp or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )
        return events[:limit]

    def close(self) -> None:
        """Close all HTTP sessions."""
        for client in self._clients.values():
            client.close()
        self._clients.clear()
