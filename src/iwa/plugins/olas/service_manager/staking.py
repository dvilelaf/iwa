"""Staking manager mixin."""

from datetime import datetime, timezone
from typing import Optional

from loguru import logger
from web3 import Web3

from iwa.core.contracts.erc20 import ERC20Contract
from iwa.core.types import EthereumAddress
from iwa.plugins.olas.contracts.staking import StakingContract, StakingState
from iwa.plugins.olas.models import StakingStatus


class StakingManagerMixin:
    """Mixin for staking operations."""

    def get_staking_status(self) -> Optional[StakingStatus]:
        """Get comprehensive staking status for the active service.

        Returns:
            StakingStatus with liveness check info, or None if no service loaded.

        """
        if not self.service:
            logger.error("No active service")
            return None

        service_id = self.service.service_id
        staking_address = self.service.staking_contract_address

        # Check if service is staked
        if not staking_address:
            return StakingStatus(
                is_staked=False,
                staking_state="NOT_STAKED",
            )

        # Load the staking contract
        try:
            staking = StakingContract(str(staking_address), chain_name=self.chain_name)
        except Exception as e:
            logger.error(f"Failed to load staking contract: {e}")
            return StakingStatus(
                is_staked=False,
                staking_state="ERROR",
                staking_contract_address=str(staking_address),
            )

        # Get staking state
        staking_state = staking.get_staking_state(service_id)
        is_staked = staking_state == StakingState.STAKED

        if not is_staked:
            return StakingStatus(
                is_staked=False,
                staking_state=staking_state.name,
                staking_contract_address=str(staking_address),
                activity_checker_address=staking.activity_checker_address,
                liveness_ratio=staking.activity_checker.liveness_ratio,
            )

        # Get detailed service info
        try:
            info = staking.get_service_info(service_id)
            # Get current epoch number
            epoch_number = staking.get_epoch_counter()
            # Identify contract name
            staking_name = self._identify_staking_contract_name(staking_address)
        except Exception as e:
            logger.error(f"Failed to get service info for service {service_id}: {str(e)}")
            import traceback

            logger.error(traceback.format_exc())
            return StakingStatus(
                is_staked=True,
                staking_state=staking_state.name,
                staking_contract_address=str(staking_address),
            )

        # Calculate unstake timing
        unstake_at, ts_start, min_duration = self._calculate_unstake_time(staking, info)

        return StakingStatus(
            is_staked=True,
            staking_state=staking_state.name,
            staking_contract_address=str(staking_address),
            staking_contract_name=staking_name,
            mech_requests_this_epoch=info["mech_requests_this_epoch"],
            required_mech_requests=info["required_mech_requests"],
            remaining_mech_requests=info["remaining_mech_requests"],
            has_enough_requests=info["has_enough_requests"],
            liveness_ratio_passed=info["liveness_ratio_passed"],
            accrued_reward_wei=info["accrued_reward_wei"],
            accrued_reward_olas=float(Web3.from_wei(info["accrued_reward_wei"], "ether")),
            epoch_number=epoch_number,
            epoch_end_utc=info["epoch_end_utc"].isoformat() if info["epoch_end_utc"] else None,
            remaining_epoch_seconds=info["remaining_epoch_seconds"],
            activity_checker_address=staking.activity_checker_address,
            liveness_ratio=staking.activity_checker.liveness_ratio,
            ts_start=ts_start,
            min_staking_duration=min_duration,
            unstake_available_at=unstake_at,
        )

    def _identify_staking_contract_name(self, staking_address: str) -> Optional[str]:
        """Identify the name of the staking contract from constants."""
        from iwa.plugins.olas.constants import OLAS_TRADER_STAKING_CONTRACTS

        for chain_cts in OLAS_TRADER_STAKING_CONTRACTS.values():
            for name, addr in chain_cts.items():
                if str(addr).lower() == str(staking_address).lower():
                    return name
        return None

    def _calculate_unstake_time(
        self, staking: StakingContract, info: dict
    ) -> tuple[Optional[str], int, int]:
        """Calculate unstake availability time.

        Returns:
            Tuple of (unstake_at_iso, ts_start, min_duration)

        """
        # Helper to safely get min_staking_duration
        try:
            min_duration = staking.min_staking_duration
            logger.info(f"min_staking_duration: {min_duration}")
        except Exception as e:
            logger.error(f"Failed to get min_staking_duration: {e}")
            min_duration = 0

        unstake_at = None
        ts_start = info.get("ts_start", 0)
        logger.info(f"ts_start: {ts_start}")

        if ts_start > 0:
            try:
                unstake_ts = ts_start + min_duration
                unstake_at = datetime.fromtimestamp(
                    unstake_ts,
                    tz=timezone.utc,
                ).isoformat()
                logger.info(f"unstake_available_at: {unstake_at} (ts={unstake_ts})")
            except Exception as e:
                logger.error(f"calc error: {e}")
                pass
        else:
            logger.warning("ts_start is 0, cannot calculate unstake time")

        return unstake_at, ts_start, min_duration

    def stake(self, staking_contract) -> bool:
        """Stake the service in a staking contract.

        Token Flow:
            The total OLAS required is split 50/50 between deposit and bond:
            - minStakingDeposit: Transferred to staking contract during this call
            - agentBond: Already in Token Utility from service registration

            Example for Hobbyist 1 (100 OLAS total):
            - minStakingDeposit: 50 OLAS (from master account -> staking contract)
            - agentBond: 50 OLAS (already in Token Utility)

        Requirements:
            - Service must be in DEPLOYED state
            - Service must be created with OLAS token (not native currency)
            - Master account must have >= minStakingDeposit OLAS tokens
            - Staking contract must have available slots

        Args:
            staking_contract: StakingContract instance to stake in.

        Returns:
            True if staking succeeded, False otherwise.

        """
        # 1. Validation
        requirements = self._check_stake_requirements(staking_contract)
        if not requirements:
            return False

        min_deposit = requirements["min_deposit"]

        # 2. Approve Tokens
        if not self._approve_staking_tokens(staking_contract, min_deposit):
            return False

        # 3. Execute Stake Transaction
        return self._execute_stake_transaction(staking_contract)

    def _check_stake_requirements(self, staking_contract) -> Optional[dict]:
        """Validate all conditions required for staking."""
        from iwa.plugins.olas.contracts.service import ServiceState

        # Check centralized staking requirements
        reqs = staking_contract.get_requirements()
        min_deposit = reqs["min_staking_deposit"]
        required_bond = reqs["required_agent_bond"]
        staking_token = Web3.to_checksum_address(reqs["staking_token"])
        staking_token_lower = staking_token.lower()

        logger.info(f"Checking stake requirements for service {self.service.service_id}")

        # Check service state
        service_info = self.registry.get_service(self.service.service_id)
        service_state = service_info["state"]
        logger.info(f"Service state: {service_state.name}")

        if service_state != ServiceState.DEPLOYED:
            logger.error("Service is not deployed, cannot stake")
            return None

        # Check token compatibility
        service_token = (self.service.token_address or "").lower()
        if service_token != staking_token_lower:
            logger.error(
                f"Token mismatch: service was created with {service_token or 'native'}, "
                f"but staking contract requires {staking_token_lower}"
            )
            return None

        # Check agent bond
        try:
            agent_ids = service_info["agent_ids"]
            if not agent_ids:
                logger.error("No agent IDs found for service")
                return None

            agent_id = agent_ids[0]
            agent_params = self.registry.get_agent_params(self.service.service_id, agent_id)
            current_bond = agent_params["bond"]

            if current_bond < required_bond:
                logger.error(
                    f"Service agent bond is too low ({current_bond} < {required_bond}). "
                    "Service must be created with the correct bond amount to be stakeable."
                )
                return None
        except Exception as e:
            logger.warning(f"Could not verify agent bond: {e}")

        # Check free slots
        staked_count = len(staking_contract.get_service_ids())
        max_services = staking_contract.max_num_services
        if staked_count >= max_services:
            logger.error("Staking contract is full, no free slots available")
            return None

        # Check OLAS balance
        erc20_contract = ERC20Contract(staking_token)
        master_balance = erc20_contract.balance_of_wei(self.wallet.master_account.address)
        if master_balance < min_deposit:
            logger.error(
                f"Not enough tokens to stake service (have {master_balance}, need {min_deposit})"
            )
            return None

        return {"min_deposit": min_deposit, "staking_token": staking_token}

    def _approve_staking_tokens(self, staking_contract, min_deposit: int) -> bool:
        """Approve both the service NFT and OLAS tokens for staking."""
        # Approve service NFT
        approve_tx = self.registry.prepare_approve_tx(
            from_address=self.wallet.master_account.address,
            spender=staking_contract.address,
            id_=self.service.service_id,
        )

        success, receipt = self.wallet.sign_and_send_transaction(
            transaction=approve_tx,
            signer_address_or_tag=self.wallet.master_account.address,
            chain_name=self.chain_name,
            tags=["olas_approve_service_nft"],
        )

        if not success:
            logger.error("Failed to approve staking contract [Service Registry]")
            return False

        logger.info("Service token approved for staking contract")

        # Approve OLAS tokens
        # We need to get the token address from the contract requirements again or pass it
        # Retching for simplicity and safety
        reqs = staking_contract.get_requirements()
        staking_token = Web3.to_checksum_address(reqs["staking_token"])
        erc20_contract = ERC20Contract(staking_token)

        olas_approve_tx = erc20_contract.prepare_approve_tx(
            from_address=self.wallet.master_account.address,
            spender=staking_contract.address,
            amount_wei=min_deposit,
        )

        success, receipt = self.wallet.sign_and_send_transaction(
            transaction=olas_approve_tx,
            signer_address_or_tag=self.wallet.master_account.address,
            chain_name=self.chain_name,
            tags=["olas_approve_olas_token"],
        )

        if not success:
            logger.error("Failed to approve OLAS tokens for staking contract")
            return False

        logger.info("OLAS tokens approved for staking contract")
        return True

    def _execute_stake_transaction(self, staking_contract) -> bool:
        """Send the stake transaction and verify the result."""
        stake_tx = staking_contract.prepare_stake_tx(
            from_address=self.wallet.master_account.address,
            service_id=self.service.service_id,
        )

        success, receipt = self.wallet.sign_and_send_transaction(
            transaction=stake_tx,
            signer_address_or_tag=self.wallet.master_account.address,
            chain_name=self.chain_name,
            tags=["olas_stake_service"],
        )

        if not success:
            if receipt and "status" in receipt and receipt["status"] == 0:
                logger.error(f"Stake transaction reverted. Receipt: {receipt}")
            logger.error("Failed to stake service")
            return False

        logger.info("Service stake transaction sent successfully")

        events = staking_contract.extract_events(receipt)
        event_names = [event["name"] for event in events]

        if "ServiceStaked" not in event_names:
            logger.error("Stake service event not found")
            return False

        # Verify state
        staking_state = staking_contract.get_staking_state(self.service.service_id)
        if staking_state != StakingState.STAKED:
            logger.error("Service is not staked after transaction")
            return False

        # Update local state
        self.service.staking_contract_address = EthereumAddress(staking_contract.address)
        self._update_and_save_service_state()

        logger.info("Service staked successfully")
        return True

    def unstake(self, staking_contract) -> bool:
        """Unstake the service from the staking contract."""
        if not self.service:
            logger.error("No active service")
            return False

        logger.info(
            f"Preparing to unstake service {self.service.service_id} from {staking_contract.address}"
        )

        # Check that the service is staked
        try:
            staking_state = staking_contract.get_staking_state(self.service.service_id)
            logger.info(f"Current staking state: {staking_state}")

            if staking_state != StakingState.STAKED:
                logger.error(
                    f"Service {self.service.service_id} is not staked (state={staking_state}), cannot unstake"
                )
                return False
        except Exception as e:
            logger.error(f"Failed to get staking state: {e}")
            return False

        # Check that enough time has passed since staking
        try:
            service_info = staking_contract.get_service_info(self.service.service_id)
            ts_start = service_info.get("ts_start", 0)
            if ts_start > 0:
                min_duration = staking_contract.min_staking_duration
                unlock_ts = ts_start + min_duration
                now_ts = datetime.now(timezone.utc).timestamp()

                if now_ts < unlock_ts:
                    diff = int(unlock_ts - now_ts)
                    logger.error(
                        f"Cannot unstake yet. Minimum staking duration not met. Unlocks in {diff} seconds."
                    )
                    return False
        except Exception as e:
            logger.warning(f"Could not verify staking duration: {e}. Proceeding with caution.")

        # Unstake the service
        try:
            logger.info(f"Preparing unstake transaction for service {self.service.service_id}")
            unstake_tx = staking_contract.prepare_unstake_tx(
                from_address=self.wallet.master_account.address,
                service_id=self.service.service_id,
            )
            logger.info("Unstake transaction prepared successfully")

        except Exception as e:
            logger.exception(f"Failed to prepare unstake tx: {e}")
            return False

        success, receipt = self.wallet.sign_and_send_transaction(
            transaction=unstake_tx,
            signer_address_or_tag=self.wallet.master_account.address,
            chain_name=self.chain_name,
            tags=["olas_unstake_service"],
        )

        if not success:
            logger.error(f"Failed to unstake service {self.service.service_id}: Transaction failed")
            return False

        logger.info(
            f"Unstake transaction sent: {receipt.get('transactionHash', '').hex() if receipt else 'No Receipt'}"
        )

        events = staking_contract.extract_events(receipt)

        if "ServiceUnstaked" not in [event["name"] for event in events]:
            logger.error("Unstake service event not found")
            return False

        self.service.staking_contract_address = None
        self._update_and_save_service_state()

        logger.info("Service unstaked successfully")
        return True

    def call_checkpoint(
        self,
        staking_contract: Optional[StakingContract] = None,
        grace_period_seconds: int = 600,
    ) -> bool:
        """Call the checkpoint on the staking contract to close the current epoch.

        The checkpoint closes the current epoch, calculates rewards for all staked
        services, and starts a new epoch. Anyone can call this once the epoch has ended.

        This method will:
        1. Check if the checkpoint is needed (epoch ended)
        2. Send the checkpoint transaction

        Args:
            staking_contract: Optional pre-loaded StakingContract. If not provided,
                              it will be loaded from the service's staking_contract_address.
            grace_period_seconds: Seconds to wait after epoch ends before calling.
                                  Defaults to 600 (10 minutes) to allow others to call first.

        Returns:
            True if checkpoint was called successfully, False otherwise.

        """
        if not self.service:
            logger.error("No active service")
            return False

        if not self.service.staking_contract_address:
            logger.error("Service is not staked")
            return False

        # Load staking contract if not provided
        if not staking_contract:
            try:
                staking_contract = StakingContract(
                    str(self.service.staking_contract_address),
                    chain_name=self.service.chain_name,
                )
            except Exception as e:
                logger.error(f"Failed to load staking contract: {e}")
                return False

        # Check if checkpoint is needed
        if not staking_contract.is_checkpoint_needed(grace_period_seconds):
            epoch_end = staking_contract.get_next_epoch_start()
            logger.info(f"Checkpoint not needed yet. Epoch ends at {epoch_end.isoformat()}")
            return False

        logger.info("Calling checkpoint to close the current epoch")

        # Prepare and send checkpoint transaction
        checkpoint_tx = staking_contract.prepare_checkpoint_tx(
            from_address=self.wallet.master_account.address,
        )

        if not checkpoint_tx:
            logger.error("Failed to prepare checkpoint transaction")
            return False

        success, receipt = self.wallet.sign_and_send_transaction(
            checkpoint_tx,
            signer_address_or_tag=self.wallet.master_account.address,
            chain_name=self.service.chain_name,
            tags=["olas_call_checkpoint"],
        )
        if not success:
            logger.error("Failed to send checkpoint transaction")
            return False

        # Verify the Checkpoint event was emitted
        events = staking_contract.extract_events(receipt)
        checkpoint_events = [e for e in events if e["name"] == "Checkpoint"]

        if not checkpoint_events:
            logger.error("Checkpoint event not found - transaction may have failed")
            return False

        # Log checkpoint details from the event
        checkpoint_event = checkpoint_events[0]
        args = checkpoint_event.get("args", {})
        new_epoch = args.get("epoch", "unknown")
        available_rewards = args.get("availableRewards", 0)
        rewards_olas = available_rewards / 1e18 if available_rewards else 0

        logger.info(
            f"Checkpoint successful - New epoch: {new_epoch}, "
            f"Available rewards: {rewards_olas:.2f} OLAS"
        )

        # Log any inactivity warnings
        inactivity_warnings = [e for e in events if e["name"] == "ServiceInactivityWarning"]
        if inactivity_warnings:
            service_ids = [e["args"]["serviceId"] for e in inactivity_warnings]
            logger.warning(f"Services with inactivity warnings: {service_ids}")

        return True
