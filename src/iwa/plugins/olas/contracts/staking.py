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
from typing import Dict, List, Optional, Union

from loguru import logger

from iwa.core.contracts.contract import ContractInstance
from iwa.core.types import EthereumAddress
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

    def __init__(self, address: EthereumAddress, chain_name: str = "gnosis"):
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
        self._contract_params_cache: Dict[str, int] = {}

        self._activity_checker: Optional[ActivityCheckerContract] = None
        self._activity_checker_address: Optional[EthereumAddress] = None

    def get_requirements(self) -> Dict[str, Union[str, int]]:
        """Get the contract requirements for token and deposits.

        Returns:
            Dict containing:
                - staking_token: address of the token required
                - min_staking_deposit: amount required to be paid during stake()
                - required_agent_bond: amount required to be set during service creation

        """
        # For Olas Trader contracts (Hobbyist, Alpha, Beta, etc.),
        # the total OLAS is split 50/50:
        # 50% as agent bond (in registry) and 50% as staking deposit (passed to stake()).
        return {
            "staking_token": self.staking_token_address,
            "min_staking_deposit": self.min_staking_deposit,
            "required_agent_bond": self.min_staking_deposit,
        }

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
        result = self.call("getServiceInfo", service_id)
        # Handle potential nested tuple if web3 returns [(struct)]
        if (
            isinstance(result, (list, tuple))
            and len(result) == 1
            and isinstance(result[0], (list, tuple))
        ):
            result = result[0]

        try:
            (
                multisig_address,
                owner_address,
                nonces_on_last_checkpoint,
                ts_start,
                accrued_reward,
                inactivity,
            ) = result
        except ValueError as e:
            # Try to log useful info if unpacking fails
            logger.error(
                f"[Staking] Unpacking failed. Result type: {type(result)}, Result: {result}"
            )
            raise e

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
        # logic: use the latest of (service_start_time, global_checkpoint_time)
        # If service started AFTER global checkpoint, use service_start_time.
        # If service was already running, use global_checkpoint_time.
        global_ts_checkpoint = self.ts_checkpoint()
        effective_ts_start = max(ts_start, global_ts_checkpoint)

        liveness_passed = self.is_liveness_ratio_passed(
            current_nonces=current_nonces,
            last_nonces=(last_safe_nonce, last_mech_requests),
            ts_start=effective_ts_start,
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
        """Get the timestamp of the last checkpoint.

        Cached until the estimated end of the current epoch (ts_checkpoint + liveness_period).
        """
        now = time.time()
        cache_key = "ts_checkpoint"

        # Check if we have a valid cached value
        if cache_key in self._contract_params_cache:
            ts = self._contract_params_cache[cache_key]
            # Use liveness period to determine if we should re-check
            if now < ts + self.liveness_period:
                return ts

            # If past expected epoch end, check at most once per minute
            last_checked = self._contract_params_cache.get(f"{cache_key}_last_checked", 0)
            if now - last_checked < 60:
                return ts

        # Fetch new value
        ts = self.call("tsCheckpoint")
        self._contract_params_cache[cache_key] = ts
        self._contract_params_cache[f"{cache_key}_last_checked"] = now
        return ts

    def clear_epoch_cache(self) -> None:
        """Clear cache for epoch-dependent properties."""
        self._contract_params_cache.pop("ts_checkpoint", None)
        self._contract_params_cache.pop("ts_checkpoint_last_checked", None)
        logger.debug(f"Cleared epoch cache for StakingContract {self.address}")

    def get_required_requests(self, use_liveness_period: bool = True) -> int:
        """Calculate the required requests for the current epoch.

        Includes a safety margin of 1 extra request.
        """
        requests_safety_margin = 1
        now_ts = time.time()

        # If use_liveness_period is True, we show the requirement for a standard epoch
        # instead of the potentially very long period since the last global checkpoint.
        time_diff = (
            self.liveness_period
            if use_liveness_period
            else max(self.liveness_period, now_ts - self.ts_checkpoint())
        )

        return math.ceil(
            (time_diff * self.activity_checker.liveness_ratio) / 1e18 + requests_safety_margin
        )

    @property
    def activity_checker_address_value(self) -> EthereumAddress:
        """Get the activity checker address."""
        if self._activity_checker_address is None:
            self._activity_checker_address = self.call("activityChecker")
        return self._activity_checker_address

    @property
    def activity_checker_address(self) -> EthereumAddress:
        """Backwards compatibility for activity_checker_address."""
        return self.activity_checker_address_value

    @property
    def activity_checker(self) -> ActivityCheckerContract:
        """Get the activity checker contract."""
        if self._activity_checker is None:
            self._activity_checker = ActivityCheckerContract(
                self.activity_checker_address_value, chain_name=self.chain_name
            )
        return self._activity_checker

    @property
    def available_rewards(self) -> int:
        """Get available rewards."""
        if "availableRewards" not in self._contract_params_cache:
            self._contract_params_cache["availableRewards"] = self.call("availableRewards")
        return self._contract_params_cache["availableRewards"]

    @property
    def balance(self) -> int:
        """Get contract balance."""
        if "balance" not in self._contract_params_cache:
            self._contract_params_cache["balance"] = self.call("balance")
        return self._contract_params_cache["balance"]

    @property
    def liveness_period(self) -> int:
        """Get liveness period."""
        if "livenessPeriod" not in self._contract_params_cache:
            self._contract_params_cache["livenessPeriod"] = self.call("livenessPeriod")
        return self._contract_params_cache["livenessPeriod"]

    @property
    def rewards_per_second(self) -> int:
        """Get rewards per second."""
        if "rewardsPerSecond" not in self._contract_params_cache:
            self._contract_params_cache["rewardsPerSecond"] = self.call("rewardsPerSecond")
        return self._contract_params_cache["rewardsPerSecond"]

    @property
    def max_num_services(self) -> int:
        """Get max number of services."""
        if "maxNumServices" not in self._contract_params_cache:
            self._contract_params_cache["maxNumServices"] = self.call("maxNumServices")
        return self._contract_params_cache["maxNumServices"]

    @property
    def min_staking_deposit(self) -> int:
        """Get min staking deposit."""
        if "minStakingDeposit" not in self._contract_params_cache:
            self._contract_params_cache["minStakingDeposit"] = self.call("minStakingDeposit")
        return self._contract_params_cache["minStakingDeposit"]

    @property
    def min_staking_duration_hours(self) -> float:
        """Get min staking duration in hours."""
        return self.min_staking_duration / 3600

    @property
    def staking_token_address(self) -> EthereumAddress:
        """Get staking token address."""
        if "stakingToken" not in self._contract_params_cache:
            self._contract_params_cache["stakingToken"] = self.call("stakingToken")
        return self._contract_params_cache["stakingToken"]

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

    @property
    def min_staking_duration(self) -> int:
        """Get the minimum duration a service must be staked before it can be unstaked."""
        if "minStakingDuration" not in self._contract_params_cache:
            self._contract_params_cache["minStakingDuration"] = self.call("minStakingDuration")
        return self._contract_params_cache["minStakingDuration"]

    def prepare_stake_tx(
        self,
        from_address: EthereumAddress,
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
        from_address: EthereumAddress,
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

    def prepare_claim_tx(
        self,
        from_address: EthereumAddress,
        service_id: int,
    ) -> Optional[Dict]:
        """Prepare a claim transaction to claim staking rewards.

        Args:
            from_address: The address sending the transaction (service owner).
            service_id: The service ID to claim rewards for.

        Returns:
            Transaction dict ready to be signed and sent.

        """
        tx = self.prepare_transaction(
            method_name="claim",
            method_kwargs={
                "serviceId": service_id,
            },
            tx_params={"from": from_address},
        )
        return tx

    def get_accrued_rewards(self, service_id: int) -> int:
        """Get accrued rewards for a service.

        Args:
            service_id: The service ID to query.

        Returns:
            Accrued rewards in wei (from mapServiceInfo[3]).

        """
        service_info = self.call("mapServiceInfo", service_id)
        # mapServiceInfo returns (multisig, owner, nonces, tsStart, reward, inactivity)
        # reward is at index 4 (0-indexed)
        return service_info[4] if len(service_info) > 4 else 0

    def is_checkpoint_needed(self, grace_period_seconds: int = 600) -> bool:
        """Check if the checkpoint needs to be called.

        The checkpoint should be called when:
        1. The current epoch has ended (current time > epoch_end)
        2. A grace period has passed (to allow someone else to call it first)

        Args:
            grace_period_seconds: Seconds to wait after epoch ends before calling.
                                  Defaults to 600 (10 minutes).

        Returns:
            True if checkpoint should be called, False otherwise.

        """
        epoch_end = self.get_next_epoch_start()
        now = datetime.now(timezone.utc)

        # If the epoch has not finished, no need to call
        if now < epoch_end:
            return False

        # If less than grace_period has passed since epoch ended, wait
        if (now - epoch_end).total_seconds() < grace_period_seconds:
            return False

        return True

    def prepare_checkpoint_tx(self, from_address: str) -> Optional[Dict]:
        """Prepare a checkpoint transaction.

        The checkpoint closes the current epoch and starts a new one.
        Anyone can call this once the epoch has ended.

        Args:
            from_address: The address sending the transaction.

        Returns:
            Transaction dict ready to be signed and sent.

        """
        tx = self.prepare_transaction(
            method_name="checkpoint",
            method_kwargs={},
            tx_params={"from": from_address},
        )
        return tx
