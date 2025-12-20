"""Olas models"""

from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from iwa.core.models import EthereumAddress


class Service(BaseModel):
    """Service model for OLAS services."""

    service_name: str  # Human-readable name
    chain_name: str
    service_id: int  # Unique per chain
    agent_ids: List[int] = Field(default_factory=list)  # List of agent type IDs
    service_owner_address: Optional[EthereumAddress] = None
    agent_address: Optional[EthereumAddress] = None
    multisig_address: Optional[EthereumAddress] = None
    staking_contract_address: Optional[EthereumAddress] = None
    token_address: Optional[EthereumAddress] = None

    @property
    def key(self) -> str:
        """Unique key for this service (chain_name:service_id)."""
        return f"{self.chain_name}:{self.service_id}"


class StakingStatus(BaseModel):
    """Staking status for a service including liveness check info.

    The activity checker tracks:
    - safe_nonce: Total Safe multisig transactions
    - mech_requests: Total mech requests made

    Liveness is measured by mech_requests made since last checkpoint.
    """

    is_staked: bool
    staking_contract_address: Optional[str] = None
    staking_state: str  # "NOT_STAKED", "STAKED", "EVICTED"

    # Mech request tracking (what determines liveness)
    mech_requests_this_epoch: int = 0
    required_mech_requests: int = 0
    remaining_mech_requests: int = 0
    has_enough_requests: bool = False
    liveness_ratio_passed: bool = False

    # Rewards
    accrued_reward_wei: int = 0

    # Epoch timing
    epoch_end_utc: Optional[str] = None  # ISO format string
    remaining_epoch_seconds: float = 0

    # Activity checker info
    activity_checker_address: Optional[str] = None
    liveness_ratio: int = 0  # Requests per second * 1e18


class OlasConfig(BaseModel):
    """OlasConfig with multi-service support."""

    # Dict keyed by service key (chain_name:service_id)
    services: Dict[str, Service] = Field(default_factory=dict)

    # Currently active service key (for ServiceManager)
    active_service_key: Optional[str] = None

    def get_active_service(self) -> Optional[Service]:
        """Get the currently active service."""
        if self.active_service_key and self.active_service_key in self.services:
            return self.services[self.active_service_key]
        return None

    def add_service(self, service: Service) -> None:
        """Add or update a service."""
        self.services[service.key] = service

    def remove_service(self, key: str) -> bool:
        """Remove a service by key."""
        if key in self.services:
            del self.services[key]
            if self.active_service_key == key:
                self.active_service_key = None
            return True
        return False

    def set_active(self, chain_name: str, service_id: int) -> bool:
        """Set the active service by chain and ID."""
        key = f"{chain_name}:{service_id}"
        if key in self.services:
            self.active_service_key = key
            return True
        return False

    def get_service(self, chain_name: str, service_id: int) -> Optional[Service]:
        """Get a specific service by chain and ID."""
        key = f"{chain_name}:{service_id}"
        return self.services.get(key)
