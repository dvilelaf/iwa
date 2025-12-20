"""Staking contract interaction.

=============================================================================
OLAS STAKING TOKEN MECHANICS
=============================================================================

When staking a service, the TOTAL OLAS required is split 50/50:

1. minStakingDeposit: Collateral for the staking contract
   - Checked by stakingContract.minStakingDeposit()
   - Goes to the staking contract when stake() is called

2. agentBond: Operator bond for the agent instance
   - Must be deposited BEFORE staking during service creation
   - Stored in Token Utility: getAgentBond(serviceId, agentId)

Both deposits are stored in the Token Utility contract:
- mapServiceIdTokenDeposit(serviceId) -> (token, deposit)
- getAgentBond(serviceId, agentId) -> bond

Example for Hobbyist 1 (100 OLAS total):
- minStakingDeposit: 50 OLAS
- agentBond: 50 OLAS (set during service creation)
- Total: 100 OLAS

The staking contract checks that:
1. Service is in DEPLOYED state
2. Service was created with the correct token (OLAS)
3. minStakingDeposit is met
4. Agent bond was deposited during service registration
"""

import math
import time
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional

from iwa.core.contracts.contract import ContractInstance
from iwa.plugins.olas.contracts.activity_checker import ActivityCheckerContract
from iwa.plugins.olas.contracts.base import OLAS_ABI_PATH


class StakingState(Enum):
    """Enum representing the staking state of a service."""

    NOT_STAKED = 0
    STAKED = 1
    EVICTED = 2


class StakingContract(ContractInstance):
    """Class to interact with the staking contract.

    Manages staking operations for OLAS services and tracks activity/liveness
    requirements through the associated activity checker.
    """

    name = "staking"
    abi_path = OLAS_ABI_PATH / "staking.json"

    def __init__(self, address: str, chain_name: str = "gnosis"):
        """Initialize StakingContract.

        Args:
            address: The staking contract address.
            chain_name: The chain name (default: gnosis).

        Note:
            minStakingDeposit is 50% of the total OLAS required.
            The other 50% is the agentBond, deposited during service creation.
            Example: Hobbyist 1 (100 OLAS) = 50 deposit + 50 bond

        """
        super().__init__(address, chain_name=chain_name)
        self.chain_name = chain_name

        # Get activity checker from the staking contract
        activity_checker_address = self.call("activityChecker")
        self.activity_checker = ActivityCheckerContract(
            activity_checker_address, chain_name=chain_name
        )
        self.activity_checker_address = activity_checker_address

        # Cache contract parameters
        self.available_rewards = self.call("availableRewards")
        self.balance = self.call("balance")
        self.liveness_period = self.call("livenessPeriod")
        self.rewards_per_second = self.call("rewardsPerSecond")
        self.max_num_services = self.call("maxNumServices")
        self.min_staking_deposit = self.call("minStakingDeposit")
        self.min_staking_duration_hours = self.call("minStakingDuration") / 3600
        self.staking_token_address = self.call("stakingToken")

    def calculate_accrued_staking_reward(self, service_id: int) -> int:
        """Calculate the accrued staking reward for a given service ID."""
        return self.call("calculateStakingLastReward", service_id)

    def calculate_staking_reward(self, service_id: int) -> int:
        """Calculate the current staking reward for a given service ID."""
        return self.call("calculateStakingReward", service_id)

    def get_epoch_counter(self) -> int:
        """Get the current epoch counter from the staking contract."""
        return self.call("epochCounter")

    def get_next_epoch_start(self) -> datetime:
        """Calculate the start time of the next epoch."""
        return datetime.fromtimestamp(
            self.call("getNextRewardCheckpointTimestamp"),
            tz=timezone.utc,
        )

    def get_service_ids(self) -> List[int]:
        """Get the current staked services."""
        return self.call("getServiceIds")

    def get_service_info(self, service_id: int) -> Dict:
        """Get comprehensive staking information for a service.

        Args:
            service_id: The service ID to query.

        Returns:
            Dict with staking info including nonces, rewards, and liveness status.

        Note:
            Activity nonces from the checker are: (safe_nonce, mech_requests_count).
            For liveness tracking, we use mech_requests_count (index 1).

        """
        (
            multisig_address,
            owner_address,
            nonces_on_last_checkpoint,
            ts_start,
            accrued_reward,
            inactivity,
        ) = self.call("getServiceInfo", service_id)

        # Get current nonces from activity checker: (safe_nonce, mech_requests)
        current_nonces = self.activity_checker.get_multisig_nonces(multisig_address)
        current_safe_nonce, current_mech_requests = current_nonces

        # Last checkpoint nonces are also (safe_nonce, mech_requests)
        last_safe_nonce = nonces_on_last_checkpoint[0]
        last_mech_requests = nonces_on_last_checkpoint[1]

        # Mech requests this epoch (what matters for liveness)
        mech_requests_this_epoch = current_mech_requests - last_mech_requests

        required_requests = self.get_required_requests()
        epoch_end = self.get_next_epoch_start()
        remaining_seconds = (epoch_end - datetime.now(timezone.utc)).total_seconds()

        # Check liveness ratio using activity checker
        liveness_passed = self.is_liveness_ratio_passed(
            current_nonces=current_nonces,
            last_nonces=(last_safe_nonce, last_mech_requests),
            ts_start=ts_start,
        )

        return {
            "multisig_address": multisig_address,
            "owner_address": owner_address,
            "current_safe_nonce": current_safe_nonce,
            "current_mech_requests": current_mech_requests,
            "last_checkpoint_safe_nonce": last_safe_nonce,
            "last_checkpoint_mech_requests": last_mech_requests,
            "mech_requests_this_epoch": mech_requests_this_epoch,
            "required_mech_requests": required_requests,
            "remaining_mech_requests": max(0, required_requests - mech_requests_this_epoch),
            "has_enough_requests": mech_requests_this_epoch >= required_requests,
            "accrued_reward_wei": accrued_reward,
            "epoch_end_utc": epoch_end,
            "remaining_epoch_seconds": remaining_seconds,
            "liveness_ratio_passed": liveness_passed,
            "ts_start": ts_start,
            "inactivity_count": inactivity,
        }

    def get_staking_state(self, service_id: int) -> StakingState:
        """Get the staking state for a given service ID."""
        return StakingState(self.call("getStakingState", service_id))

    def ts_checkpoint(self) -> int:
        """Get the timestamp of the last checkpoint."""
        return self.call("tsCheckpoint")

    def get_required_requests(self) -> int:
        """Calculate the required requests for the current epoch.

        Includes a safety margin of 1 extra request.
        """
        requests_safety_margin = 1
        now_ts = time.time()
        return math.ceil(
            (
                max(self.liveness_period, now_ts - self.ts_checkpoint())
                * self.activity_checker.liveness_ratio
            )
            / 1e18
            + requests_safety_margin
        )

    def is_liveness_ratio_passed(
        self,
        current_nonces: tuple,
        last_nonces: tuple,
        ts_start: int,
    ) -> bool:
        """Check if the liveness ratio requirement is passed.

        Uses the activity checker's isRatioPass function to determine
        if the service meets liveness requirements for staking rewards.

        Args:
            current_nonces: Current (safe_nonce, mech_requests_count).
            last_nonces: Nonces at the last checkpoint (safe_nonce, mech_requests_count).
            ts_start: Timestamp when staking started or last checkpoint.

        Returns:
            True if liveness requirements are met.

        """
        # Calculate time difference since last checkpoint
        ts_diff = int(time.time()) - ts_start
        if ts_diff <= 0:
            return False

        return self.activity_checker.is_ratio_pass(
            current_nonces=current_nonces,
            last_nonces=last_nonces,
            ts_diff=ts_diff,
        )

    def prepare_stake_tx(
        self,
        from_address: str,
        service_id: int,
    ) -> Optional[Dict]:
        """Prepare a stake transaction."""
        tx = self.prepare_transaction(
            method_name="stake",
            method_kwargs={
                "serviceId": service_id,
            },
            tx_params={"from": from_address},
        )
        return tx

    def prepare_unstake_tx(
        self,
        from_address: str,
        service_id: int,
    ) -> Optional[Dict]:
        """Prepare an unstake transaction."""
        tx = self.prepare_transaction(
            method_name="unstake",
            method_kwargs={
                "serviceId": service_id,
            },
            tx_params={"from": from_address},
        )
        return tx
