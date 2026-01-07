"""Drain manager mixin."""

from typing import Any, Dict, Optional, Tuple

from loguru import logger

from iwa.core.contracts.erc20 import ERC20Contract
from iwa.plugins.olas.constants import OLAS_TOKEN_ADDRESS_GNOSIS
from iwa.plugins.olas.contracts.staking import StakingContract, StakingState


class DrainManagerMixin:
    """Mixin for draining and service token management."""

    def claim_rewards(self, staking_contract: Optional[StakingContract] = None) -> Tuple[bool, int]:
        """Claim staking rewards for the active service.

        The claimed OLAS tokens will be sent to the service's multisig (Safe).

        Args:
            staking_contract: Optional pre-loaded StakingContract. If not provided,
                              it will be loaded from the service's staking_contract_address.

        Returns:
            Tuple of (success, claimed_amount_wei).

        """
        if not self.service:
            logger.error("No active service")
            return False, 0

        if not self.service.staking_contract_address:
            logger.error("Service is not staked")
            return False, 0

        # Load staking contract if not provided
        if not staking_contract:
            try:
                staking_contract = StakingContract(
                    str(self.service.staking_contract_address),
                    chain_name=self.chain_name,
                )
            except Exception as e:
                logger.error(f"Failed to load staking contract: {e}")
                return False, 0

        service_id = self.service.service_id

        # Check if actually staked
        if staking_contract.get_staking_state(service_id) != StakingState.STAKED:
            logger.info("Service not staked, skipping claim")
            return False, 0

        # Check accrued rewards
        accrued_rewards = staking_contract.get_accrued_rewards(service_id)
        if accrued_rewards == 0:
            logger.info("No accrued rewards to claim")
            return False, 0

        logger.info(f"Claiming {accrued_rewards / 1e18:.4f} OLAS rewards for service {service_id}")

        # Prepare and send claim transaction
        claim_tx = staking_contract.prepare_claim_tx(
            from_address=self.wallet.master_account.address,
            service_id=service_id,
        )

        if not claim_tx:
            logger.error("Failed to prepare claim transaction")
            return False, 0

        success, receipt = self.wallet.sign_and_send_transaction(
            claim_tx,
            signer_address_or_tag=self.wallet.master_account.address,
            chain_name=self.chain_name,
            tags=["olas_claim_rewards"],
        )
        if not success:
            logger.error("Failed to send claim transaction")
            return False, 0

        events = staking_contract.extract_events(receipt)
        if "RewardClaimed" not in [event["name"] for event in events]:
            logger.warning("RewardClaimed event not found, but transaction succeeded")

        logger.info(f"Successfully claimed {accrued_rewards / 1e18:.4f} OLAS rewards")
        return True, accrued_rewards

    def withdraw_rewards(self) -> Tuple[bool, float]:
        """Withdraw OLAS from the service Safe to the configured withdrawal address.

        The OLAS tokens are transferred from the service's multisig to the
        withdrawal_address configured in the OlasConfig.

        Returns:
            Tuple of (success, olas_amount_transferred).

        """
        if not self.service:
            logger.error("No active service")
            return False, 0

        if not self.service.multisig_address:
            logger.error("Service has no multisig address")
            return False, 0

        if not self.olas_config.withdrawal_address:
            logger.error("No withdrawal address configured in OlasConfig")
            return False, 0

        multisig_address = str(self.service.multisig_address)
        withdrawal_address = str(self.olas_config.withdrawal_address)

        # Get OLAS balance of the Safe
        olas_token = ERC20Contract(
            str(OLAS_TOKEN_ADDRESS_GNOSIS),
            chain_name=self.chain_name,
        )

        olas_balance = olas_token.balance_of_wei(multisig_address)
        if olas_balance == 0:
            logger.info("No OLAS balance to withdraw")
            return False, 0

        olas_amount = olas_balance / 1e18
        logger.info(
            f"Withdrawing {olas_amount:.4f} OLAS from {multisig_address} to {withdrawal_address}"
        )

        # Transfer from Safe to withdrawal address
        tx_hash = self.wallet.send(
            from_address_or_tag=multisig_address,
            to_address_or_tag=withdrawal_address,
            amount_wei=olas_balance,
            token_address_or_name=str(OLAS_TOKEN_ADDRESS_GNOSIS),
            chain_name=self.chain_name,
        )

        if not tx_hash:
            logger.error("Failed to transfer OLAS")
            return False, 0

        logger.info(f"Withdrew {olas_amount:.4f} OLAS to {withdrawal_address}")
        return True, olas_amount

    def drain_service(
        self,
        target_address: Optional[str] = None,
        claim_rewards: bool = True,
    ) -> Dict[str, Dict[str, float]]:
        """Drain all service accounts to a target address.

        This method:
        1. Claims any pending staking rewards (if staked and claim_rewards=True)
        2. Drains the Safe (multisig) - native + OLAS tokens
        3. Drains the Agent account - native + OLAS tokens
        4. Drains the Owner account - native + OLAS tokens

        All assets are transferred to the target address (defaults to master account).

        Args:
            target_address: Address to receive drained funds. Defaults to master account.
            claim_rewards: Whether to claim staking rewards before draining.

        Returns:
            Dict with drained amounts per account.

        """
        if not self.service:
            logger.error("No active service")
            return {}

        target = target_address or self.wallet.master_account.address
        chain = self.chain_name
        drained: Dict[str, Any] = {}

        logger.info(f"Draining service {self.service.key} to {target}")

        # Step 1: Claim rewards if staked
        claimed_rewards = self._claim_rewards_if_needed(claim_rewards)

        # Step 2: Drain the Safe
        safe_result = self._drain_safe_account(target, chain, claimed_rewards)
        if safe_result:
            drained["safe"] = safe_result

        # Step 3: Drain the Agent account
        agent_result = self._drain_agent_account(target, chain)
        if agent_result:
            drained["agent"] = agent_result

        # Step 4: Drain the Owner account
        owner_result = self._drain_owner_account(target, chain)
        if owner_result:
            drained["owner"] = owner_result

        # Handle partial success (rewards claimed but no drain)
        if not drained and claimed_rewards > 0:
            logger.info("Drain returned empty but rewards were claimed. Reporting partial success.")
            drained["safe_rewards_only"] = {"olas": claimed_rewards / 1e18}

        logger.info(f"Drain complete. Accounts drained: {list(drained.keys())}")
        return drained

    def _claim_rewards_if_needed(self, claim_rewards: bool) -> int:
        """Claim rewards if applicable."""
        if claim_rewards and self.service.staking_contract_address:
            try:
                success, amount = self.claim_rewards()
                if success and amount > 0:
                    logger.info(f"Claimed {amount / 1e18:.4f} OLAS rewards")
                    return amount
            except Exception as e:
                logger.warning(f"Could not claim rewards: {e}")
        return 0

    def _drain_safe_account(self, target: str, chain: str, claimed_rewards: int) -> Optional[Any]:
        """Drain the Safe account with retry logic for rewards."""
        if not self.service.multisig_address:
            return None

        safe_addr = str(self.service.multisig_address)
        logger.info(f"Attempting to drain Safe: {safe_addr}")

        # Retry loop if we claimed rewards to allow for RPC indexing
        max_retries = 6 if claimed_rewards > 0 else 1

        for attempt in range(max_retries):
            try:
                result = self.wallet.drain(
                    from_address_or_tag=safe_addr,
                    to_address_or_tag=target,
                    chain_name=chain,
                )
                logger.info(f"Safe drain result (attempt {attempt + 1}): {result}")

                normalized_result = self._normalize_drain_result(result)
                if normalized_result:
                    logger.info(f"Drained Safe: {normalized_result}")
                    return normalized_result

                if attempt < max_retries - 1:
                    logger.info(
                        f"Waiting for rewards to appear in balance (attempt {attempt + 1})..."
                    )
                    import time

                    time.sleep(3)

            except Exception as e:
                logger.warning(f"Could not drain Safe: {e}")
                import traceback

                logger.warning(f"Safe traceback: {traceback.format_exc()}")
                if attempt < max_retries - 1:
                    import time

                    time.sleep(3)
        return None

    def _drain_agent_account(self, target: str, chain: str) -> Optional[Any]:
        """Drain the Agent account."""
        if not self.service.agent_address:
            return None

        agent_addr = str(self.service.agent_address)
        logger.info(f"Attempting to drain Agent: {agent_addr}")
        try:
            result = self.wallet.drain(
                from_address_or_tag=agent_addr,
                to_address_or_tag=target,
                chain_name=chain,
            )
            logger.info(f"Agent drain result: {result}")
            normalized = self._normalize_drain_result(result)
            if normalized:
                logger.info(f"Drained Agent: {normalized}")
                return normalized
            else:
                logger.warning("Agent drain returned None/empty")
        except Exception as e:
            logger.warning(f"Could not drain Agent: {e}")
            import traceback

            logger.warning(f"Agent traceback: {traceback.format_exc()}")
        return None

    def _drain_owner_account(self, target: str, chain: str) -> Optional[Any]:
        """Drain the Owner account."""
        if not self.service.service_owner_address:
            return None

        owner_addr = str(self.service.service_owner_address)

        # Skip if owner == target (owner is already the destination, e.g., master)
        if owner_addr.lower() == target.lower():
            logger.info("Skipping owner drain: owner is already the target address")
            return None

        logger.info(f"Attempting to drain Owner: {owner_addr}")
        try:
            result = self.wallet.drain(
                from_address_or_tag=owner_addr,
                to_address_or_tag=target,
                chain_name=chain,
            )
            logger.info(f"Owner drain result: {result}")
            normalized = self._normalize_drain_result(result)
            if normalized:
                logger.info(f"Drained Owner: {normalized}")
                return normalized
            else:
                logger.warning("Owner drain returned None/empty")
        except Exception as e:
            logger.warning(f"Could not drain Owner: {e}")
            import traceback

            logger.warning(f"Owner traceback: {traceback.format_exc()}")
        return None

    def _normalize_drain_result(self, result: Any) -> Any:
        """Normalize the result from wallet.drain to a transaction hash string or dict."""
        if not result:
            return None

        # Handle Tuple[bool, dict] from EOA/TransactionService
        if isinstance(result, tuple) and len(result) >= 2:
            success, receipt = result
            if success:
                tx_hash = receipt.get("transactionHash")
                if hasattr(tx_hash, "hex"):
                    return tx_hash.hex()
                return str(tx_hash)
            return None

        return result
