"""ServiceManager package."""
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
