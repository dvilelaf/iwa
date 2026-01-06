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

    def get_staking_status(self) -> Optional[StakingStatus]:  # noqa: C901
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

            # Look up contract name from constants
            staking_name = None
            from iwa.plugins.olas.constants import OLAS_TRADER_STAKING_CONTRACTS

            for chain_cts in OLAS_TRADER_STAKING_CONTRACTS.values():
                for name, addr in chain_cts.items():
                    if str(addr).lower() == str(staking_address).lower():
                        staking_name = name
                        break
                if staking_name:
                    break
        except Exception as e:
            logger.error(f"Failed to get service info for service {service_id}: {str(e)}")
            import traceback

            logger.error(traceback.format_exc())
            return StakingStatus(
                is_staked=True,
                staking_state=staking_state.name,
                staking_contract_address=str(staking_address),
            )

        # Helper to safely get min_staking_duration
        try:
            min_duration = staking.min_staking_duration
            logger.info(f"[DEBUG-STAKE] min_staking_duration: {min_duration}")
        except Exception as e:
            logger.error(f"[DEBUG-STAKE] Failed to get min_staking_duration: {e}")
            min_duration = 0

        unstake_at = None
        ts_start = info.get("ts_start", 0)
        logger.info(f"[DEBUG-STAKE] ts_start: {ts_start}")

        if ts_start > 0:
            try:
                unstake_ts = ts_start + min_duration
                unstake_at = datetime.fromtimestamp(
                    unstake_ts,
                    tz=timezone.utc,
                ).isoformat()
                logger.info(f"[DEBUG-STAKE] unstake_available_at: {unstake_at} (ts={unstake_ts})")
            except Exception as e:
                logger.error(f"[DEBUG-STAKE] calc error: {e}")
                pass
        else:
            logger.warning("[DEBUG-STAKE] ts_start is 0, cannot calculate unstake time")

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

    def stake(self, staking_contract) -> bool:  # noqa: C901
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
        from iwa.plugins.olas.contracts.service import ServiceState

        # Check centralized staking requirements
        reqs = staking_contract.get_requirements()
        min_deposit = reqs["min_staking_deposit"]
        required_bond = reqs["required_agent_bond"]
        staking_token = Web3.to_checksum_address(reqs["staking_token"])
        staking_token_lower = staking_token.lower()  # For comparison only

        erc20_contract = ERC20Contract(staking_token)
        print(f"[STAKE-SM] Checking requirements for service {self.service.service_id}", flush=True)
        logger.info(f"Checking stake requirements for service {self.service.service_id}")

        # Check that she service is deployed
        service_info = self.registry.get_service(self.service.service_id)
        service_state = service_info["state"]
        print(f"[STAKE-SM] Service state: {service_state.name}", flush=True)
        print(f"[STAKE-SM] Service multisig: {self.service.multisig_address}", flush=True)
        print(
            f"[STAKE-SM] Service registry info: multisig={service_info.get('multisig')}, threshold={service_info.get('threshold')}",
            flush=True,
        )
        logger.info(f"Service state: {service_state.name}")
        if service_state != ServiceState.DEPLOYED:
            print("[STAKE-SM] FAIL: Service not deployed", flush=True)
            logger.error("Service is not deployed, cannot stake")
            return False

        logger.info("Service is deployed")

        # Check token compatibility - service must be created with same token as staking contract expects
        service_token = (self.service.token_address or "").lower()
        print(
            f"[STAKE-SM] Token check: service={service_token}, staking={staking_token_lower}",
            flush=True,
        )
        if service_token != staking_token_lower:
            print(
                "[STAKE-SM] FAIL: Token mismatch! Service token != staking contract token",
                flush=True,
            )
            logger.error(
                f"Token mismatch: service was created with {service_token or 'native'}, "
                f"but staking contract requires {staking_token_lower}"
            )
            return False

        logger.info("Token compatibility check passed")

        # Check that the service has enough agent bond
        # We check for the first agent ID as Olas services usually have one type for traders
        try:
            # Get the first agent ID for this service
            agent_ids = service_info["agent_ids"]
            if not agent_ids:
                logger.error("No agent IDs found for service")
                return False

            agent_id = agent_ids[0]
            agent_params = self.registry.get_agent_params(self.service.service_id, agent_id)
            current_bond = agent_params["bond"]

            print(
                f"[STAKE-SM] Bond check: current={current_bond}, required={required_bond}",
                flush=True,
            )
            logger.info(f"Agent bond check: current={current_bond}, required={required_bond}")

            if current_bond < required_bond:
                error_msg = (
                    f"Service agent bond is too low ({current_bond} < {required_bond}). "
                    "Service must be created with the correct bond amount to be stakeable."
                )
                print(f"[STAKE-SM] FAIL: {error_msg}", flush=True)
                logger.error(error_msg)
                return False
        except Exception as e:
            logger.warning(f"Could not verify agent bond: {e}")

        # Check that there are free slots
        staked_count = len(staking_contract.get_service_ids())
        max_services = staking_contract.max_num_services
        print(f"[STAKE-SM] Slots: {staked_count}/{max_services}", flush=True)
        logger.info(f"Staking contract slots: {staked_count}/{max_services}")
        if staked_count >= max_services:
            print("[STAKE-SM] FAIL: No free slots", flush=True)
            logger.error("Staking contract is full, no free slots available")
            return False

        # Check that there are enough OLAS for the deposit
        master_balance = erc20_contract.balance_of_wei(self.wallet.master_account.address)
        print(
            f"[STAKE-SM] OLAS balance: {master_balance} wei, min_deposit: {min_deposit} wei",
            flush=True,
        )
        logger.info(f"OLAS balance check: master={master_balance}, min_deposit={min_deposit}")
        if master_balance < min_deposit:
            print("[STAKE-SM] FAIL: Not enough OLAS", flush=True)
            logger.error(
                f"Not enough tokens to stake service (have {master_balance}, need {min_deposit})"
            )
            return False

        print("[STAKE-SM] All checks passed, proceeding with stake...", flush=True)

        # Approve the staking contract to move the service token (NFT)
        print("[STAKE-SM] Preparing service NFT approval transaction...", flush=True)
        approve_tx = self.registry.prepare_approve_tx(
            from_address=self.wallet.master_account.address,
            spender=staking_contract.address,
            id_=self.service.service_id,
        )

        print("[STAKE-SM] Sending service NFT approval transaction...", flush=True)
        success, receipt = self.wallet.sign_and_send_transaction(
            transaction=approve_tx,
            signer_address_or_tag=self.wallet.master_account.address,
            chain_name=self.service.chain_name,
            tags=["olas_approve_service_nft"],
        )
        logger.info("Approving service token for staking contract")
        print(f"[STAKE-SM] Service NFT approval result: success={success}", flush=True)

        if not success:
            print("[STAKE-SM] FAIL: Service NFT approval transaction failed", flush=True)
            logger.error("Failed to approve staking contract [Service Registry]")
            return False

        logger.info("Service token approved for staking contract")

        # Approve the staking contract to transfer OLAS tokens
        print("[STAKE-SM] Preparing OLAS token approval transaction...", flush=True)
        olas_approve_tx = erc20_contract.prepare_approve_tx(
            from_address=self.wallet.master_account.address,
            spender=staking_contract.address,
            amount_wei=min_deposit,
        )

        print("[STAKE-SM] Sending OLAS token approval transaction...", flush=True)
        success, receipt = self.wallet.sign_and_send_transaction(
            transaction=olas_approve_tx,
            signer_address_or_tag=self.wallet.master_account.address,
            chain_name=self.service.chain_name,
            tags=["olas_approve_olas_token"],
        )
        print(f"[STAKE-SM] OLAS token approval result: success={success}", flush=True)

        if not success:
            print("[STAKE-SM] FAIL: OLAS token approval transaction failed", flush=True)
            logger.error("Failed to approve OLAS tokens for staking contract")
            return False

        logger.info("OLAS tokens approved for staking contract")

        # Stake the service
        print("[STAKE-SM] Preparing stake transaction...", flush=True)
        stake_tx = staking_contract.prepare_stake_tx(
            from_address=self.wallet.master_account.address,
            service_id=self.service.service_id,
        )

        print("[STAKE-SM] Sending stake transaction...", flush=True)
        success, receipt = self.wallet.sign_and_send_transaction(
            transaction=stake_tx,
            signer_address_or_tag=self.wallet.master_account.address,
            chain_name=self.service.chain_name,
            tags=["olas_stake_service"],
        )
        print(f"[STAKE-SM] Stake tx result: success={success}", flush=True)

        if not success:
            print("[STAKE-SM] FAIL: Stake transaction failed", flush=True)
            if receipt and "status" in receipt and receipt["status"] == 0:
                logger.error(f"Stake transaction reverted. Receipt: {receipt}")
                # Try to decode error if possible (though for status 0 receipt it's too late for simple decoding without re-tracing)
            logger.error("Failed to stake service")
            return False

        logger.info("Service stake transaction sent successfully")

        print("[STAKE-SM] Extracting events from receipt...", flush=True)
        events = staking_contract.extract_events(receipt)
        event_names = [event["name"] for event in events]
        print(f"[STAKE-SM] Events found: {event_names}", flush=True)

        if "ServiceStaked" not in event_names:
            print("[STAKE-SM] FAIL: ServiceStaked event not found", flush=True)
            logger.error("Stake service event not found")
            return False

        staking_state = staking_contract.get_staking_state(self.service.service_id)
        print(f"[STAKE-SM] Final staking state: {staking_state}", flush=True)
        if staking_state != StakingState.STAKED:
            print("[STAKE-SM] FAIL: Service not in STAKED state", flush=True)
            logger.error("Service is not staked after transaction")
            return False

        self.service.staking_contract_address = EthereumAddress(staking_contract.address)
        self._update_and_save_service_state()
        print("[STAKE-SM] SUCCESS: Service staked and config saved", flush=True)
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
            logger.info(f"[SM-UNSTAKE] Unstake TX To: {unstake_tx.get('to')}")
            logger.info(f"[SM-UNSTAKE] Staking Contract Address: {staking_contract.address}")
        except Exception as e:
            logger.exception(f"Failed to prepare unstake tx: {e}")
            return False

        success, receipt = self.wallet.sign_and_send_transaction(
            transaction=unstake_tx,
            signer_address_or_tag=self.wallet.master_account.address,
            chain_name=self.service.chain_name,
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
