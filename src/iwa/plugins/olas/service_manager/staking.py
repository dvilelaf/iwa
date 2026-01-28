"""Staking manager mixin for OLAS service staking operations.

OLAS Token Flow Overview
========================

For OLAS token-bonded services (e.g., Expert 7 MM requiring 10,000 OLAS total),
the tokens flow through multiple stages:

1. CREATE SERVICE
   - Service is registered on-chain with bond parameters
   - Service Owner approves Token Utility to spend OLAS (2 × bond)
   - NO OLAS tokens move yet

2. ACTIVATION (min_staking_deposit = 5,000 OLAS for 10k contract)
   - Service Owner approves Token Utility for the security deposit
   - TX sends 1 wei native value (not 5k OLAS!)
   - Token Utility internally calls transferFrom() to move 5k OLAS
   - 5k OLAS moves: Service Owner → Token Utility

3. REGISTRATION (agent_bond = 5,000 OLAS for 10k contract)
   - Service Owner approves Token Utility for the bond amount
   - TX sends 1 wei native value per agent (not 5k OLAS!)
   - Token Utility internally calls transferFrom() to move 5k OLAS
   - 5k OLAS moves: Service Owner → Token Utility

4. DEPLOY
   - Creates the Safe multisig for the service
   - NO OLAS tokens move

5. STAKE (this module) ★
   - Only the Service NFT is approved to the staking contract
   - NO OLAS tokens move in this transaction!
   - The staking contract reads the deposited amounts from Token Utility
   - Service Registry L2 token (NFT) moves: Owner → Staking Contract

Key Insight:
    At stake time, the Service Owner's OLAS balance is 0 (all 10k was deposited
    during activation + registration). This is correct! The staking contract
    pulls position data from the Token Utility, not from the owner's wallet.

Contract Addresses (Gnosis):
    - Token Utility: 0xa45E...8eD8
    - Service Registry L2: 0x9338...55fD
    - OLAS Token: 0xcE11...d9f
"""

from datetime import datetime, timezone
from typing import Optional

from loguru import logger
from web3 import Web3

from iwa.core.contracts.cache import ContractCache
from iwa.core.types import EthereumAddress
from iwa.core.utils import get_tx_hash
from iwa.plugins.olas.contracts.staking import StakingContract, StakingState
from iwa.plugins.olas.models import StakingStatus


class StakingManagerMixin:
    """Mixin for staking operations on OLAS services.

    This mixin handles the final step of the service lifecycle: staking a
    deployed service into a staking contract to earn OLAS rewards.

    Important: By the time stake() is called, all OLAS tokens have already
    been deposited to the Token Utility during activation and registration.
    The stake transaction only transfers the Service NFT, not OLAS tokens.

    Staking Requirements:
        - Service must be in DEPLOYED state
        - Service must be created with OLAS token (not native currency)
        - Staking contract must have available slots
        - Service token must match staking contract's required token
    """

    def _get_label(self, address: str) -> str:
        """Resolve address to a human-readable label."""
        if not address:
            return "None"

        # Try account service tags first (wallets, safes)
        try:
            tag = self.wallet.account_service.get_tag_by_address(address)
            if tag:
                return tag
        except AttributeError:
            pass

        # Try token/contract names
        try:
            from iwa.core.chain import ChainInterfaces

            chain_interface = ChainInterfaces().get(self.chain_name)
            token_name = chain_interface.chain.get_token_name(address)
            if token_name:
                return token_name
        except Exception:
            pass

        return address

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
            staking = ContractCache().get_contract(
                StakingContract, str(staking_address), chain_name=self.chain_name
            )
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
            logger.debug(f"min_staking_duration: {min_duration}")
        except Exception as e:
            logger.error(f"Failed to get min_staking_duration: {e}")
            min_duration = 0

        unstake_at = None
        ts_start = info.get("ts_start", 0)
        logger.debug(f"ts_start: {ts_start}")

        if ts_start > 0:
            try:
                unstake_ts = ts_start + min_duration
                unstake_at = datetime.fromtimestamp(
                    unstake_ts,
                    tz=timezone.utc,
                ).isoformat()
                logger.debug(f"unstake_available_at: {unstake_at} (ts={unstake_ts})")
            except Exception as e:
                logger.error(f"calc error: {e}")
                pass
        else:
            logger.debug("ts_start is 0, cannot calculate unstake time")

        return unstake_at, ts_start, min_duration

    def stake(self, staking_contract) -> bool:
        """Stake the service in a staking contract.

        This is the final step after create → activate → register → deploy.
        At this point, all OLAS tokens are already in the Token Utility.

        Token Flow at Stake Time:
            ┌─────────────────────────────────────────────────────────────────┐
            │  What Moves:                                                    │
            │    • Service NFT (ERC-721): Owner → Staking Contract            │
            │                                                                 │
            │  What does NOT Move:                                            │
            │    • OLAS tokens - already in Token Utility from earlier steps  │
            └─────────────────────────────────────────────────────────────────┘

        Why no OLAS transfer?
            The staking contract reads the service's bond/deposit from the
            Token Utility contract. It doesn't need a new transfer - it just
            verifies the amounts are sufficient and locks the service.

        Process:
            1. Validate requirements (state, token, slots)
            2. Approve Service NFT to staking contract
            3. Call stake(serviceId) on staking contract
            4. Verify ServiceStaked event

        Args:
            staking_contract: StakingContract instance to stake in.

        Returns:
            True if staking succeeded, False otherwise.

        """
        logger.info("=" * 50)
        logger.info(f"[STAKE] Starting staking for service {self.service.service_id}")
        logger.info(f"[STAKE] Contract: {self._get_label(staking_contract.address)}")
        logger.info("=" * 50)

        # 1. Validation
        logger.info("[STAKE] Step 1: Checking requirements...")
        requirements = self._check_stake_requirements(staking_contract)
        if not requirements:
            logger.error("[STAKE] Step 1 FAILED: Requirements not met")
            return False
        logger.info("[STAKE] Step 1 OK: All requirements met")

        min_deposit = requirements["min_deposit"]
        logger.info(
            f"[STAKE] Min deposit required: {min_deposit} wei ({min_deposit / 1e18:.2f} OLAS)"
        )

        # 2. Approve Service NFT
        logger.info("[STAKE] Step 2: Approving service NFT...")
        if not self._approve_staking_tokens(staking_contract):
            logger.error("[STAKE] Step 2 FAILED: NFT approval failed")
            return False
        logger.info("[STAKE] Step 2 OK: Service NFT approved")

        # 3. Execute Stake Transaction
        logger.info("[STAKE] Step 3: Executing stake transaction...")
        result = self._execute_stake_transaction(staking_contract)
        if result:
            logger.info("[STAKE] Step 3 OK: Staking successful")
            logger.info("=" * 50)
            logger.info(f"[STAKE] COMPLETE - Service {self.service.service_id} is now staked")
            logger.info("=" * 50)
        else:
            logger.error("[STAKE] Step 3 FAILED: Stake transaction failed")
        return result

    def _check_stake_requirements(self, staking_contract) -> Optional[dict]:
        """Validate all conditions required for staking.

        Checks performed:
            1. Service State: Must be DEPLOYED (multisig created)
            2. Token Match: Service token == Staking contract's staking_token
            3. Agent Bond: Logged (may show 1 wei on-chain, this is normal)
            4. Available Slots: Contract must have free slots

        Note on OLAS Balance:
            We do NOT check owner's OLAS balance here. By this point:
            - 5k OLAS was transferred during activation (to Token Utility)
            - 5k OLAS was transferred during registration (to Token Utility)
            - Owner's OLAS balance is 0, and that's correct!

        Args:
            staking_contract: StakingContract to validate against.

        Returns:
            Dict with {min_deposit, staking_token} if valid, None otherwise.

        """
        from iwa.plugins.olas.contracts.service import ServiceState

        logger.debug("[STAKE] Fetching contract requirements...")
        reqs = staking_contract.get_requirements()
        min_deposit = reqs["min_staking_deposit"]
        required_bond = reqs["required_agent_bond"]
        staking_token = Web3.to_checksum_address(reqs["staking_token"])
        staking_token_lower = staking_token.lower()

        logger.info("[STAKE] Contract requirements:")
        logger.info(f"[STAKE]   - min_staking_deposit: {min_deposit} wei")
        logger.info(f"[STAKE]   - required_agent_bond: {required_bond} wei")
        logger.info(f"[STAKE]   - staking_token: {staking_token}")

        # Check service state
        logger.debug("[STAKE] Checking service state...")
        service_info = self.registry.get_service(self.service.service_id)
        service_state = service_info["state"]
        logger.info(f"[STAKE] Service state: {service_state.name}")

        if service_state != ServiceState.DEPLOYED:
            logger.error(f"[STAKE] FAIL: Service is {service_state.name}, expected DEPLOYED")
            return None
        logger.debug("[STAKE] OK: Service is DEPLOYED")

        # Check token compatibility
        service_token = (self.service.token_address or "").lower()
        logger.debug(f"[STAKE] Service token: {service_token}")
        if service_token != staking_token_lower:
            logger.error(
                f"[STAKE] FAIL: Token mismatch - service={service_token or 'native'}, "
                f"contract requires={staking_token_lower}"
            )
            return None
        logger.debug("[STAKE] OK: Token matches")

        # Check agent bond
        # NOTE: On-chain bond values often show 1 wei regardless of what was passed
        # during service creation. This is a known issue with the OLAS contracts.
        # We log a warning but don't block staking because of this discrepancy.
        logger.debug("[STAKE] Checking agent bond...")
        try:
            agent_ids = service_info["agent_ids"]
            if not agent_ids:
                logger.error("[STAKE] FAIL: No agent IDs found")
                return None

            params_list = self.registry.get_agent_params(self.service.service_id)
            agent_params = params_list[0]
            current_bond = agent_params["bond"]
            logger.info(
                f"[STAKE] Agent bond on-chain: {current_bond} wei (required: {required_bond} wei)"
            )

            if current_bond < required_bond:
                logger.warning(
                    f"[STAKE] WARN: On-chain bond ({current_bond}) < required ({required_bond}). "
                    "This is a known on-chain reporting issue. Proceeding anyway."
                )
            else:
                logger.debug("[STAKE] OK: Agent bond sufficient")
        except Exception as e:
            logger.warning(f"[STAKE] WARN: Could not verify agent bond: {e}")

        # Check free slots
        logger.debug("[STAKE] Checking available slots...")
        staked_count = len(staking_contract.get_service_ids())
        max_services = staking_contract.max_num_services
        free_slots = max_services - staked_count
        logger.info(f"[STAKE] Slots: {staked_count}/{max_services} used, {free_slots} free")

        if staked_count >= max_services:
            logger.error("[STAKE] FAIL: No free slots")
            return None
        logger.debug("[STAKE] OK: Slots available")

        # NOTE: We don't check OLAS balance here because OLAS was already
        # deposited to the Token Utility during activation (min_staking_deposit)
        # and registration (agent_bond). The staking contract pulls from there.
        logger.debug(
            "[STAKE] OLAS already deposited to Token Utility during activation/registration"
        )

        return {"min_deposit": min_deposit, "staking_token": staking_token}

    def _approve_staking_tokens(self, staking_contract) -> bool:
        """Approve the Service NFT for transfer to the staking contract.

        What This Does:
            Calls approve(stakingContract, serviceId) on the Service Registry L2.
            This allows the staking contract to transferFrom the NFT.

        What This Does NOT Do:
            - Does NOT approve OLAS tokens (they're already in Token Utility)
            - Does NOT transfer any tokens (that happens in _execute_stake_transaction)

        Token/NFT Movement:
            BEFORE: Owner has NFT, staking contract has no approval
            AFTER:  Owner has NFT, staking contract is approved to take it

        Who Signs:
            Master account (must be service owner)

        Returns:
            True if approval succeeded, False otherwise.

        """
        # Use service owner which holds the NFT (not necessarily master)
        owner_address = self.service.service_owner_address or self.wallet.master_account.address

        # Approve service NFT - this is an ERC-721 approval, not ERC-20
        logger.debug(
            f"[STAKE] Approving service NFT for staking contract from {self._get_label(owner_address)}..."
        )
        approve_tx = self.registry.prepare_approve_tx(
            from_address=owner_address,
            spender=staking_contract.address,
            id_=self.service.service_id,
        )

        success, receipt = self.wallet.sign_and_send_transaction(
            transaction=approve_tx,
            signer_address_or_tag=owner_address,
            chain_name=self.chain_name,
            tags=["olas_approve_service_nft"],
        )

        if not success:
            logger.error("[STAKE] FAIL: Service NFT approval failed")
            return False

        tx_hash = get_tx_hash(receipt)
        logger.info(f"[STAKE] Service NFT approved: {tx_hash}")
        return True

    def _execute_stake_transaction(self, staking_contract) -> bool:
        """Execute the actual stake transaction on the staking contract.

        What Happens Internally:
            1. Staking contract calls transferFrom to take the Service NFT
            2. Staking contract reads bond/deposit from Token Utility
            3. Staking contract records the service as staked
            4. ServiceStaked event is emitted

        Token Movement:
            - Service NFT: Owner → Staking Contract (via transferFrom)
            - OLAS tokens: None! Already in Token Utility

        Why No OLAS Transfer?
            The staking contract calls ServiceRegistryTokenUtility.getOperatorBalance()
            to verify the deposited amounts. It doesn't need a new transfer.

        Returns:
            True if stake succeeded and ServiceStaked event was found.

        """
        # Use service owner which holds the NFT (not necessarily master)
        owner_address = self.service.service_owner_address or self.wallet.master_account.address

        logger.debug(
            f"[STAKE] Preparing stake transaction from {self._get_label(owner_address)}..."
        )
        stake_tx = staking_contract.prepare_stake_tx(
            from_address=owner_address,
            service_id=self.service.service_id,
        )
        logger.debug(f"[STAKE] TX prepared: to={stake_tx.get('to')}")

        success, receipt = self.wallet.sign_and_send_transaction(
            transaction=stake_tx,
            signer_address_or_tag=owner_address,
            chain_name=self.chain_name,
            tags=["olas_stake_service"],
        )

        if not success:
            if receipt and "status" in receipt and receipt["status"] == 0:
                logger.error(f"[STAKE] TX reverted. Receipt: {receipt}")
            logger.error("[STAKE] Stake transaction failed")
            return False

        tx_hash = get_tx_hash(receipt)
        logger.info(f"[STAKE] TX sent: {tx_hash}")

        events = staking_contract.extract_events(receipt)
        event_names = [event["name"] for event in events]
        logger.debug(f"[STAKE] Events: {event_names}")

        if "ServiceStaked" not in event_names:
            logger.error("[STAKE] ServiceStaked event not found")
            return False
        logger.debug("[STAKE] ServiceStaked event confirmed")

        # Verify state
        staking_state = staking_contract.get_staking_state(self.service.service_id)
        logger.debug(f"[STAKE] Final staking state: {staking_state.name}")

        if staking_state != StakingState.STAKED:
            logger.error(f"[STAKE] FAIL: Service not staked (state={staking_state.name})")
            return False

        # Update local state
        self.service.staking_contract_address = EthereumAddress(staking_contract.address)
        self._update_and_save_service_state()

        logger.info(f"[STAKE] Service {self.service.service_id} is now STAKED")
        return True

    def unstake(self, staking_contract) -> bool:  # noqa: C901
        """Unstake the service from the staking contract."""
        if not self.service:
            logger.error("No active service")
            return False

        logger.info(
            f"Preparing to unstake service {self.service.service_id} from {self._get_label(staking_contract.address)}"
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

        # Use service owner which holds the NFT (not necessarily master)
        owner_address = self.service.service_owner_address or self.wallet.master_account.address

        # Unstake the service
        try:
            logger.info(
                f"Preparing unstake transaction for service {self.service.service_id} from {self._get_label(owner_address)}"
            )
            unstake_tx = staking_contract.prepare_unstake_tx(
                from_address=owner_address,
                service_id=self.service.service_id,
            )
            logger.info("Unstake transaction prepared successfully")

        except Exception as e:
            logger.exception(f"Failed to prepare unstake tx: {e}")
            return False

        success, receipt = self.wallet.sign_and_send_transaction(
            transaction=unstake_tx,
            signer_address_or_tag=owner_address,
            chain_name=self.chain_name,
            tags=["olas_unstake_service"],
        )
        if not success:
            logger.error(f"Failed to unstake service {self.service.service_id}: Transaction failed")
            return False

        tx_hash = get_tx_hash(receipt)
        logger.info(f"Unstake transaction sent: {tx_hash if receipt else 'No Receipt'}")

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
                staking_contract = ContractCache().get_contract(
                    StakingContract,
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
