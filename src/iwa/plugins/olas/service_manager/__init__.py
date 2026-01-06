"""Service Manager package for OLAS services."""

from iwa.core.chain import ChainInterfaces
from iwa.core.contracts.erc20 import ERC20Contract
from iwa.core.models import Config
from iwa.plugins.olas.constants import OLAS_CONTRACTS
from iwa.plugins.olas.contracts.mech import MechContract
from iwa.plugins.olas.contracts.mech_marketplace import MechMarketplaceContract
from iwa.plugins.olas.contracts.service import (
    ServiceManagerContract,
    ServiceRegistryContract,
    ServiceState,
)
from iwa.plugins.olas.contracts.staking import StakingContract, StakingState
from iwa.plugins.olas.models import OlasConfig, Service, StakingStatus
from iwa.plugins.olas.service_manager.base import ServiceManagerBase
from iwa.plugins.olas.service_manager.drain import DrainManagerMixin
from iwa.plugins.olas.service_manager.lifecycle import LifecycleManagerMixin
from iwa.plugins.olas.service_manager.mech import MechManagerMixin
from iwa.plugins.olas.service_manager.staking import StakingManagerMixin


class ServiceManager(
    LifecycleManagerMixin,
    DrainManagerMixin,
    MechManagerMixin,
    StakingManagerMixin,
    ServiceManagerBase,
):
    """ServiceManager for OLAS services with multi-service support.

    Combines functionality from:
    - LifecycleManagerMixin: create, deploy, terminate, etc.
    - StakingManagerMixin: stake, unstake, checkpoint
    - DrainManagerMixin: drain, claim_rewards
    - MechManagerMixin: send_mech_request
    - ServiceManagerBase: init, common config
    """

    pass


__all__ = [
    "ServiceManager",
    # Re-export commonly used types for backward compatibility
    "Service",
    "StakingStatus",
    "OlasConfig",
    "ServiceState",
    "StakingState",
    "StakingContract",
    "ServiceRegistryContract",
    "ServiceManagerContract",
    "MechContract",
    "MechMarketplaceContract",
    "ERC20Contract",
    "ChainInterfaces",
    "Config",
    "OLAS_CONTRACTS",
]
