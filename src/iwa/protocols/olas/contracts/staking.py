from iwa.protocols.olas.contracts.base import ContractInstance
from iwa.protocols.olas.contracts.activity_checker import ActivityCheckerContract
from datetime import datetime, timezone
import math
import time
from typing import List, Dict
from enum import Enum


class StakingState(Enum):
    """Enum representing the staking state of a service."""

    NOT_STAKED = 0
    STAKED = 1
    EVICTED = 2


class StakingContract(ContractInstance):
    """Class to interact with the staking contract."""

    name = "staking"

    def __init__(self, address: str):
        super().__init__(address)

        activity_checker_address = self.call("activityChecker")
        self.activity_checker = ActivityCheckerContract(activity_checker_address)
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

    def get_service_info(self, service_id: int):
        """Get information about services in the staking contract."""
        (
            multisig_address,
            owner_address,
            nonces_on_last_checkpoint,
            ts_start,
            accrued_reward,
            inactivity,
        ) = self.call("getServiceInfo", service_id)
        total_nonces = self.activity_checker.get_multisig_nonces(multisig_address)
        nonces_since_last_checkpoint = total_nonces[0] - nonces_on_last_checkpoint[0]
        required_nonces = self.get_required_requests()
        return {
            "owner_address": owner_address,
            "activity_nonces": nonces_since_last_checkpoint,
            "multisig_address": multisig_address,
            "accrued_reward": accrued_reward,
            "required_nonces": required_nonces,
            "has_enough_nonces": nonces_since_last_checkpoint >= required_nonces,
            "remaining_epoch_seconds": (
                self.get_next_epoch_start() - datetime.now(timezone.utc)
            ).total_seconds(),
        }

    def get_staking_state(self, service_id: int):
        """Get the staking state for a given service ID."""
        return StakingState(self.call("getStakingState", service_id))

    def ts_checkpoint(self) -> int:
        """Get the timestamp of the last checkpoint."""
        return self.call("tsCheckpoint")

    def get_required_requests(self) -> int:
        """Calculate the required requests for the next epoch."""
        REQUESTS_SAFETY_MARGIN = 1
        now_ts = time.time()
        return math.ceil(
            (
                max(self.liveness_period, now_ts - self.ts_checkpoint())
                * self.activity_checker.liveness_ratio
            )
            / 1e18
            + REQUESTS_SAFETY_MARGIN
        )

    def prepare_stake_tx(
        self,
        from_address: str,
        service_id: int,
    ) -> Dict:
        """Stake a service."""
        tx = self.prepare_transaction(
            "stake",
            from_address=from_address,
            serviceId=service_id,
        )
        return tx

    def prepare_unstake_tx(
        self,
        from_address: str,
        service_id: int,
    ) -> Dict:
        """Unstake a service."""
        tx = self.prepare_transaction(
            "unstake",
            from_address=from_address,
            serviceId=service_id,
        )
        return tx
