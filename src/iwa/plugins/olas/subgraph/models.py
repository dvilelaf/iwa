"""Pydantic models for OLAS subgraph responses."""

from datetime import datetime, timezone
from typing import Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


def _ts_to_datetime(v: int | str | None) -> Optional[datetime]:
    """Convert a Unix timestamp (str or int) to UTC datetime."""
    if v is None:
        return None
    return datetime.fromtimestamp(int(v), tz=timezone.utc)


# ---------------------------------------------------------------------------
# Service Registry
# ---------------------------------------------------------------------------


class SubgraphService(BaseModel):
    """Service from the Service Registry subgraph."""

    service_id: int
    multisig: Optional[str] = None
    agent_ids: List[int] = Field(default_factory=list)
    creation_timestamp: Optional[datetime] = None
    config_hash: Optional[str] = None
    creator: Optional[str] = None
    chain: str = ""

    @field_validator("creation_timestamp", mode="before")
    @classmethod
    def parse_timestamp(cls, v: int | str | None) -> Optional[datetime]:
        """Parse Unix timestamp to datetime."""
        return _ts_to_datetime(v)

    @classmethod
    def from_subgraph(cls, data: Dict, chain: str = "") -> "SubgraphService":
        """Parse a service entity from raw subgraph JSON."""
        creator = data.get("creator")
        if isinstance(creator, dict):
            creator = creator.get("id")
        return cls(
            service_id=int(data["id"]),
            multisig=data.get("multisig"),
            agent_ids=[int(a) for a in (data.get("agentIds") or [])],
            creation_timestamp=data.get("creationTimestamp"),
            config_hash=data.get("configHash"),
            creator=creator,
            chain=chain,
        )


class SubgraphMultisig(BaseModel):
    """Multisig entity from the Service Registry subgraph."""

    address: str
    service_id: int
    creator: Optional[str] = None
    agent_ids: List[int] = Field(default_factory=list)
    creation_timestamp: Optional[datetime] = None

    @field_validator("creation_timestamp", mode="before")
    @classmethod
    def parse_timestamp(cls, v: int | str | None) -> Optional[datetime]:
        """Parse Unix timestamp to datetime."""
        return _ts_to_datetime(v)

    @classmethod
    def from_subgraph(cls, data: Dict) -> "SubgraphMultisig":
        """Parse a multisig entity from raw subgraph JSON."""
        return cls(
            address=data["id"],
            service_id=int(data["serviceId"]),
            creator=data.get("creator"),
            agent_ids=[int(a) for a in (data.get("agentIds") or [])],
            creation_timestamp=data.get("creationTimestamp"),
        )


class SubgraphDailyActivity(BaseModel):
    """Daily agent performance from the Service Registry subgraph."""

    day_timestamp: Optional[datetime] = None
    agent_id: int
    tx_count: int = 0
    active_multisig_count: int = 0

    @field_validator("day_timestamp", mode="before")
    @classmethod
    def parse_timestamp(cls, v: int | str | None) -> Optional[datetime]:
        """Parse Unix timestamp to datetime."""
        return _ts_to_datetime(v)

    @classmethod
    def from_subgraph(cls, data: Dict) -> "SubgraphDailyActivity":
        """Parse a daily activity entity from raw subgraph JSON."""
        return cls(
            day_timestamp=data.get("dayTimestamp"),
            agent_id=int(data.get("agentId", 0)),
            tx_count=int(data.get("txCount", 0)),
            active_multisig_count=int(data.get("activeMultisigCount", 0)),
        )


class SubgraphGlobalStats(BaseModel):
    """Global stats from the Service Registry subgraph."""

    tx_count: int = 0
    total_operators: int = 0
    last_updated: Optional[datetime] = None

    @field_validator("last_updated", mode="before")
    @classmethod
    def parse_timestamp(cls, v: int | str | None) -> Optional[datetime]:
        """Parse Unix timestamp to datetime."""
        return _ts_to_datetime(v)


# ---------------------------------------------------------------------------
# Staking
# ---------------------------------------------------------------------------


class SubgraphStakingContract(BaseModel):
    """Staking contract from the Staking subgraph."""

    address: str
    implementation: Optional[str] = None
    max_num_services: int = 0
    rewards_per_second: int = 0
    min_staking_deposit: int = 0
    min_staking_duration: int = 0
    max_num_inactivity_periods: int = 0
    liveness_period: int = 0
    time_for_emissions: int = 0
    num_agent_instances: int = 0
    agent_ids: List[int] = Field(default_factory=list)
    threshold: int = 0
    config_hash: Optional[str] = None
    activity_checker: Optional[str] = None
    service_registry: Optional[str] = None
    metadata_hash: Optional[str] = None
    chain: str = ""

    @classmethod
    def from_subgraph(cls, data: Dict, chain: str = "") -> "SubgraphStakingContract":
        """Parse a staking contract entity from raw subgraph JSON."""
        return cls(
            address=data.get("instance") or data["id"],
            implementation=data.get("implementation"),
            max_num_services=int(data.get("maxNumServices", 0)),
            rewards_per_second=int(data.get("rewardsPerSecond", 0)),
            min_staking_deposit=int(data.get("minStakingDeposit", 0)),
            min_staking_duration=int(data.get("minStakingDuration", 0)),
            max_num_inactivity_periods=int(data.get("maxNumInactivityPeriods", 0)),
            liveness_period=int(data.get("livenessPeriod", 0)),
            time_for_emissions=int(data.get("timeForEmissions", 0)),
            num_agent_instances=int(data.get("numAgentInstances", 0)),
            agent_ids=[int(a) for a in (data.get("agentIds") or [])],
            threshold=int(data.get("threshold", 0)),
            config_hash=data.get("configHash"),
            activity_checker=data.get("activityChecker"),
            service_registry=data.get("serviceRegistry"),
            metadata_hash=data.get("metadataHash"),
            chain=chain,
        )


class SubgraphStakedService(BaseModel):
    """Service staking info from the Staking subgraph."""

    service_id: int
    current_olas_staked: int = 0
    olas_rewards_earned: int = 0
    olas_rewards_claimed: int = 0
    latest_staking_contract: Optional[str] = None
    total_epochs_participated: int = 0

    @classmethod
    def from_subgraph(cls, data: Dict) -> "SubgraphStakedService":
        """Parse a staked service entity from raw subgraph JSON."""
        return cls(
            service_id=int(data["id"]),
            current_olas_staked=int(data.get("currentOlasStaked", 0)),
            olas_rewards_earned=int(data.get("olasRewardsEarned", 0)),
            olas_rewards_claimed=int(data.get("olasRewardsClaimed", 0)),
            latest_staking_contract=data.get("latestStakingContract"),
            total_epochs_participated=int(data.get("totalEpochsParticipated", 0)),
        )


class SubgraphRewardEpoch(BaseModel):
    """Per-epoch reward record from the Staking subgraph."""

    epoch: int
    reward_amount: int = 0
    staking_contract: Optional[str] = None
    checkpointed_at: Optional[datetime] = None
    block_timestamp: Optional[datetime] = None

    @field_validator("checkpointed_at", "block_timestamp", mode="before")
    @classmethod
    def parse_timestamp(cls, v: int | str | None) -> Optional[datetime]:
        """Parse Unix timestamp to datetime."""
        return _ts_to_datetime(v)

    @classmethod
    def from_subgraph(cls, data: Dict) -> "SubgraphRewardEpoch":
        """Parse a reward epoch entity from raw subgraph JSON."""
        return cls(
            epoch=int(data.get("epoch", 0)),
            reward_amount=int(data.get("rewardAmount", 0)),
            staking_contract=data.get("contractAddress"),
            checkpointed_at=data.get("checkpointedAt"),
            block_timestamp=data.get("blockTimestamp"),
        )


class SubgraphServiceEvents(BaseModel):
    """Aggregated staking lifecycle events for a service."""

    service_id: int
    staked: List[Dict] = Field(default_factory=list)
    unstaked: List[Dict] = Field(default_factory=list)
    inactivity_warnings: List[Dict] = Field(default_factory=list)
    evictions: List[Dict] = Field(default_factory=list)


class SubgraphStakingGlobal(BaseModel):
    """Global staking stats."""

    cumulative_olas_staked: int = 0
    cumulative_olas_unstaked: int = 0
    current_olas_staked: int = 0
    total_rewards: int = 0


# ---------------------------------------------------------------------------
# Protocol Registry (Ethereum)
# ---------------------------------------------------------------------------


class SubgraphProtocolService(BaseModel):
    """Service from the Autonolas Protocol Registry (Ethereum)."""

    service_id: int
    public_id: str = ""
    state: int = 0
    agent_ids: List[int] = Field(default_factory=list)
    threshold: int = 0
    multisig: Optional[str] = None
    instances: List[str] = Field(default_factory=list)
    owner: Optional[str] = None
    description: Optional[str] = None

    @classmethod
    def from_subgraph(cls, data: Dict) -> "SubgraphProtocolService":
        """Parse a protocol service entity from raw subgraph JSON."""
        return cls(
            service_id=int(data.get("serviceId", 0)),
            public_id=data.get("publicId", ""),
            state=int(data.get("state", 0)),
            agent_ids=[int(a) for a in (data.get("agentIds") or [])],
            threshold=int(data.get("threshold", 0)),
            multisig=data.get("multisig"),
            instances=data.get("instances") or [],
            owner=data.get("owner"),
            description=data.get("description"),
        )


class SubgraphProtocolGlobal(BaseModel):
    """Global stats from the Autonolas Protocol Registry."""

    total_builders: int = 0
    total_agents: int = 0
    total_components: int = 0
    total_services: int = 0
