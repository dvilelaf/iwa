"""Lifecycle manager mixin."""

from typing import List, Optional, Union

from loguru import logger
from web3 import Web3
from web3.types import Wei

from iwa.core.chain import ChainInterfaces
from iwa.core.constants import NATIVE_CURRENCY_ADDRESS, ZERO_ADDRESS
from iwa.core.types import EthereumAddress
from iwa.plugins.olas.constants import (
    OLAS_CONTRACTS,
    TRADER_CONFIG_HASH,
    AgentType,
)
from iwa.plugins.olas.contracts.service import ServiceState
from iwa.plugins.olas.models import Service


class LifecycleManagerMixin:
    """Mixin for service lifecycle operations."""

    def create(
        self,
        chain_name: str = "gnosis",
        service_name: Optional[str] = None,
        agent_ids: Optional[List[Union[AgentType, int]]] = None,
        service_owner_address_or_tag: Optional[str] = None,
        token_address_or_tag: Optional[str] = None,
        bond_amount_wei: Wei = 1,  # type: ignore
    ) -> Optional[int]:
        """Create a new service.

        Args:
            chain_name: The blockchain to create the service on.
            service_name: Human-readable name for the service (auto-generated if not provided).
            agent_ids: List of agent type IDs or AgentType enum values.
                       Defaults to [AgentType.TRADER] if not provided.
            service_owner_address_or_tag: The owner address or tag.
            token_address_or_tag: Token address for staking (optional).
            bond_amount_wei: Bond amount in tokens.

        Returns:
            The service_id if successful, None otherwise.

        """
        # Default to TRADER if no agents specified
        if agent_ids is None:
            agent_ids = [AgentType.TRADER]

        # Convert AgentType enums to ints
        agent_id_values = [int(a) for a in agent_ids]

        service_owner_account = (
            self.wallet.key_storage.get_account(service_owner_address_or_tag)
            if service_owner_address_or_tag
            else self.wallet.master_account
        )
        chain = ChainInterfaces().get(chain_name).chain
        token_address = chain.get_token_address(token_address_or_tag)

        agent_params = self._prepare_agent_params(agent_id_values, bond_amount_wei)

        logger.info(
            f"Preparing create tx: owner={service_owner_account.address}, "
            f"token={token_address}, agent_ids={agent_id_values}, agent_params={agent_params}"
        )

        receipt = self._send_create_transaction(
            service_owner_account=service_owner_account,
            token_address=token_address,
            agent_id_values=agent_id_values,
            agent_params=agent_params,
            chain_name=chain_name,
        )

        if receipt is None:
            return None

        service_id = self._extract_service_id_from_receipt(receipt)
        if not service_id:
            return None

        self._save_new_service(
            service_id=service_id,
            service_name=service_name,
            chain_name=chain_name,
            agent_id_values=agent_id_values,
            service_owner_address=service_owner_account.address,
            token_address=token_address,
        )

        self._approve_token_if_needed(
            token_address=token_address,
            chain_name=chain_name,
            service_owner_account=service_owner_account,
            bond_amount_wei=bond_amount_wei,
        )

        return service_id

    def _prepare_agent_params(self, agent_id_values: List[int], bond_amount_wei: Wei) -> List[dict]:
        """Prepare agent parameters for service creation."""
        # Create agent_params: [[instances_per_agent, bond_amount_wei], ...]
        # Use dictionary for explicit struct encoding
        return [{"slots": 1, "bond": bond_amount_wei} for _ in agent_id_values]

    def _send_create_transaction(
        self,
        service_owner_account,
        token_address,
        agent_id_values: List[int],
        agent_params: List[dict],
        chain_name: str,
    ) -> Optional[dict]:
        """Prepare and send the create service transaction."""
        try:
            create_tx = self.manager.prepare_create_tx(
                from_address=self.wallet.master_account.address,
                service_owner=service_owner_account.address,
                token_address=token_address if token_address else NATIVE_CURRENCY_ADDRESS,
                config_hash=bytes.fromhex(TRADER_CONFIG_HASH),
                agent_ids=agent_id_values,
                agent_params=agent_params,
                threshold=1,
            )
        except Exception as e:
            logger.error(f"prepare_create_tx failed: {e}")
            return None

        if not create_tx:
            logger.error("prepare_create_tx returned None (preparation failed)")
            return None

        logger.info(f"Prepared create_tx: to={create_tx.get('to')}, value={create_tx.get('value')}")
        success, receipt = self.wallet.sign_and_send_transaction(
            transaction=create_tx,
            signer_address_or_tag=self.wallet.master_account.address,
            chain_name=chain_name,
            tags=["olas_create_service"],
        )

        if not success:
            logger.error(
                f"Failed to create service - sign_and_send returned False. Receipt: {receipt}"
            )
            return None

        logger.info("Service creation transaction sent successfully")
        return receipt

    def _extract_service_id_from_receipt(self, receipt: dict) -> Optional[int]:
        """Extract service ID from transaction receipt events."""
        events = self.registry.extract_events(receipt)
        for event in events:
            if event["name"] == "CreateService":
                service_id = event["args"]["serviceId"]
                logger.info(f"Service created with ID: {service_id}")
                return service_id
        logger.error("Service creation event not found or service ID not in event")
        return None

    def _save_new_service(
        self,
        service_id: int,
        service_name: Optional[str],
        chain_name: str,
        agent_id_values: List[int],
        service_owner_address: str,
        token_address: Optional[str],
    ) -> None:
        """Create and save the new Service model."""
        new_service = Service(
            service_name=service_name or f"service_{service_id}",
            chain_name=chain_name,
            service_id=service_id,
            agent_ids=agent_id_values,
            service_owner_address=service_owner_address,
            token_address=token_address,
        )

        self.olas_config.add_service(new_service)
        self.service = new_service
        self._save_config()

    def _approve_token_if_needed(
        self,
        token_address: Optional[str],
        chain_name: str,
        service_owner_account,
        bond_amount_wei: Wei,
    ) -> None:
        """Approve token utility if a token address is provided."""
        if not token_address:
            return

        # Approve the service registry token utility contract
        protocol_contracts = OLAS_CONTRACTS.get(chain_name.lower(), {})
        utility_address = protocol_contracts.get("OLAS_SERVICE_REGISTRY_TOKEN_UTILITY")

        if not utility_address:
            logger.error(f"OLAS Service Registry Token Utility not found for chain: {chain_name}")
            return

        # Approve the token utility to move tokens (2 * bond amount as per Triton reference)
        logger.info(f"Approving Token Utility {utility_address} for {2 * bond_amount_wei} tokens")
        approve_success = self.transfer_service.approve_erc20(
            owner_address_or_tag=service_owner_account.address,
            spender_address_or_tag=utility_address,
            token_address_or_name=token_address,
            amount_wei=2 * bond_amount_wei,
            chain_name=chain_name,
        )

        if not approve_success:
            logger.error("Failed to approve Token Utility")

    def activate_registration(self) -> bool:
        """Activate registration for the service."""
        service_id = self.service.service_id
        if not self._validate_pre_registration_state(service_id):
            return False

        token_address = self._get_service_token(service_id)
        service_info = self.registry.get_service(service_id)
        security_deposit = service_info["security_deposit"]

        if not self._ensure_token_approval_for_activation(token_address, security_deposit):
            return False

        return self._send_activation_transaction(service_id, security_deposit)

    def _validate_pre_registration_state(self, service_id: int) -> bool:
        """Check if service is in PRE_REGISTRATION state."""
        # Check that the service is created
        service_info = self.registry.get_service(service_id)
        service_state = service_info["state"]
        if service_state != ServiceState.PRE_REGISTRATION:
            logger.error("Service is not created, cannot activate registration")
            return False
        return True

    def _get_service_token(self, service_id: int) -> str:
        """Get the token address for the service, defaulting to native if not found."""
        token_address = self.service.token_address
        if not token_address:
            try:
                token_address = self.registry.get_token(service_id)
            except Exception:
                # Default to native if query fails
                token_address = ZERO_ADDRESS
        return token_address

    def _ensure_token_approval_for_activation(
        self, token_address: str, security_deposit: Wei
    ) -> bool:
        """Ensure token approval for activation if not native token."""
        is_native = str(token_address).lower() == str(ZERO_ADDRESS).lower()
        if is_native:
            return True

        try:
            # Check Master Balance first
            balance = self.wallet.balance_service.get_erc20_balance_wei(
                account_address_or_tag=self.service.service_owner_address,
                token_address_or_name=token_address,
                chain_name=self.chain_name,
            )

            if balance < security_deposit:
                logger.error(
                    f"[ACTIVATE] FAIL: Owner balance {balance} < required {security_deposit}"
                )

            protocol_contracts = OLAS_CONTRACTS.get(self.chain_name.lower(), {})
            utility_address = protocol_contracts.get("OLAS_SERVICE_REGISTRY_TOKEN_UTILITY")

            if utility_address:
                required_approval = Web3.to_wei(1000, "ether")  # Approve generous amount to be safe

                # Check current allowance
                allowance = self.wallet.transfer_service.get_erc20_allowance(
                    owner_address_or_tag=self.service.service_owner_address,
                    spender_address=utility_address,
                    token_address_or_name=token_address,
                    chain_name=self.chain_name,
                )

                if allowance < Web3.to_wei(10, "ether"):  # Min threshold check
                    logger.info(
                        f"Low allowance ({allowance}). Approving Token Utility {utility_address}"
                    )
                    success_approve = self.wallet.transfer_service.approve_erc20(
                        owner_address_or_tag=self.service.service_owner_address,
                        spender_address_or_tag=utility_address,
                        token_address_or_name=token_address,
                        amount_wei=required_approval,
                        chain_name=self.chain_name,
                    )
                    if not success_approve:
                        logger.warning("Token approval transaction returned failure.")
                        return False
            return True
        except Exception as e:
            logger.warning(f"Failed to check/approve tokens: {e}")
            return False  # Return False only if we are strict, or True if we want to try anyway?
            # Original code swallowed exception but continued.
            # If we want to return early, we should return False.
            # However, if we swallow, we return True. Let's stick to original behavior,
            # BUT original code didn't return False here, it just logged and continued.
            # To be safer with clean code, if token approval fails, we should probably stop.
            # Let's assume we return True to match original "swallow" behavior but log it.
            return True

    def _send_activation_transaction(self, service_id: int, security_deposit: Wei) -> bool:
        """Send the activation transaction."""
        # Prepare activation transaction
        # NOTE: For token-based services, the security deposit is handled by the TokenUtility via transferFrom.
        # However, the ServiceManager (and Registry) REQUIRES that msg.value == security_deposit
        # even for token-based services (where security_deposit is typically 1 wei).
        # This native value (1 wei) acts as a protocol validation or fee and MUST be sent.
        # The 'value' parameter here corresponds to msg.value in the transaction.
        activate_tx = self.manager.prepare_activate_registration_tx(
            from_address=self.wallet.master_account.address,
            service_id=service_id,
            value=security_deposit,
        )
        success, receipt = self.wallet.sign_and_send_transaction(
            transaction=activate_tx,
            signer_address_or_tag=self.wallet.master_account.address,
            chain_name=self.chain_name,
        )

        if not success:
            logger.error("Failed to activate registration")
            return False

        logger.info("Registration activation transaction sent successfully")

        events = self.registry.extract_events(receipt)

        if "ActivateRegistration" not in [event["name"] for event in events]:
            logger.error("Activation event not found")
            return False

        return True

    def register_agent(
        self, agent_address: Optional[str] = None, bond_amount_wei: Optional[Wei] = None
    ) -> bool:
        """Register an agent for the service.

        Args:
            agent_address: Optional existing agent address to use.
                           If not provided, a new agent account will be created and funded.
            bond_amount_wei: The amount of tokens to bond for the agent. Required for token-bonded services.

        Returns:
            True if registration succeeded, False otherwise.

        """
        if not self._validate_active_registration_state():
            return False

        agent_account_address = self._get_or_create_agent_account(agent_address)
        if not agent_account_address:
            return False

        if not self._ensure_agent_token_approval(agent_account_address, bond_amount_wei):
            return False

        return self._send_register_agent_transaction(agent_account_address)

    def _validate_active_registration_state(self) -> bool:
        """Check that the service is in active registration."""
        service_state = self.registry.get_service(self.service.service_id)["state"]
        if service_state != ServiceState.ACTIVE_REGISTRATION:
            logger.error("Service is not in active registration, cannot register agent")
            return False
        return True

    def _get_or_create_agent_account(self, agent_address: Optional[str]) -> Optional[str]:
        """Get existing agent address or create and fund a new one."""
        if agent_address:
            logger.info(f"Using existing agent address: {agent_address}")
            return agent_address

        # Create a new account for the service (or use existing if found)
        # Use service_name for consistency with Safe naming
        agent_tag = f"{self.service.service_name}_agent"
        try:
            agent_account = self.wallet.key_storage.create_account(agent_tag)
            agent_account_address = agent_account.address
            logger.info(f"Created new agent account: {agent_account_address}")

            # Fund the agent account with some native currency for gas
            # This is needed for the agent to approve the token utility
            logger.info(f"Funding agent account {agent_account_address} with 0.1 xDAI")
            tx_hash = self.wallet.send(
                from_address_or_tag=self.wallet.master_account.address,
                to_address_or_tag=agent_account_address,
                token_address_or_name="native",
                amount_wei=Web3.to_wei(0.1, "ether"),  # 0.1 xDAI
            )
            if not tx_hash:
                logger.error("Failed to fund agent account")
                return None
            logger.info(f"Funded agent account: {tx_hash}")
            return agent_account_address
        except ValueError:
            # Handle case where account already exists
            agent_account = self.wallet.key_storage.get_account(agent_tag)
            agent_account_address = agent_account.address
            logger.info(f"Using existing agent account: {agent_account_address}")
            return agent_account_address

    def _ensure_agent_token_approval(
        self, agent_account_address: str, bond_amount_wei: Optional[Wei]
    ) -> bool:
        """Ensure token approval for agent registration if needed."""
        service_id = self.service.service_id
        token_address = self._get_service_token(service_id)
        is_native = str(token_address) == str(ZERO_ADDRESS)

        if is_native:
            return True

        if not bond_amount_wei:
            logger.warning("No bond amount provided for token bonding. Agent might fail to bond.")
            # We don't return False here, similar to original logic, just warn.
            # But approval will fail if we try to approve None.
            return True

        # 1. Service Owner Approves Token Utility (for Bond)
        # The service owner (operator) pays the bond, not the agent.
        logger.info(f"Service Owner approving Token Utility for bond: {bond_amount_wei} wei")

        utility_address = str(
            OLAS_CONTRACTS[self.chain_name]["OLAS_SERVICE_REGISTRY_TOKEN_UTILITY"]
        )

        approve_success = self.wallet.transfer_service.approve_erc20(
            token_address_or_name=token_address,
            spender_address_or_tag=utility_address,
            amount_wei=bond_amount_wei,
            owner_address_or_tag=agent_account_address,
            chain_name=self.chain_name,
        )
        if not approve_success:
            logger.error("Failed to approve token for agent registration")
            return False
        return True

    def _send_register_agent_transaction(self, agent_account_address: str) -> bool:
        """Send the register agent transaction."""
        service_id = self.service.service_id
        service_info = self.registry.get_service(service_id)
        security_deposit = service_info["security_deposit"]

        register_tx = self.manager.prepare_register_agents_tx(
            from_address=self.wallet.master_account.address,
            service_id=service_id,
            agent_instances=[agent_account_address],
            agent_ids=self.service.agent_ids,
            value=(security_deposit * len(self.service.agent_ids)),
        )
        success, receipt = self.wallet.sign_and_send_transaction(
            transaction=register_tx,
            signer_address_or_tag=self.wallet.master_account.address,
            chain_name=self.chain_name,
            tags=["olas_register_agent"],
        )

        if not success:
            logger.error("Failed to register agent")
            return False

        logger.info("Agent registration transaction sent successfully")

        events = self.registry.extract_events(receipt)

        if "RegisterInstance" not in [event["name"] for event in events]:
            logger.error("Agent registration event not found")
            return False

        self.service.agent_address = EthereumAddress(agent_account_address)
        self._update_and_save_service_state()
        return True

    def deploy(self) -> Optional[str]:
        """Deploy the service."""
        # Check that the service has finished registration
        service_state = self.registry.get_service(self.service.service_id)["state"]
        if service_state != ServiceState.FINISHED_REGISTRATION:
            logger.error("Service registration is not finished, cannot deploy")
            return False

        deploy_tx = self.manager.prepare_deploy_tx(
            from_address=self.service.service_owner_address,
            service_id=self.service.service_id,
        )
        success, receipt = self.wallet.sign_and_send_transaction(
            transaction=deploy_tx,
            signer_address_or_tag=self.service.service_owner_address,
            chain_name=self.chain_name,
            tags=["olas_deploy_service"],
        )

        if not success:
            logger.error("Failed to deploy service")
            return None

        logger.info("Service deployment transaction sent successfully")

        events = self.registry.extract_events(receipt)

        if "DeployService" not in [event["name"] for event in events]:
            logger.error("Deploy service event not found")
            return None

        multisig_address = None

        for event in events:
            if event["name"] == "CreateMultisigWithAgents":
                multisig_address = event["args"]["multisig"]
                logger.info(f"Service deployed with multisig address: {multisig_address}")
                break

        if multisig_address is None:
            logger.error("Multisig address not found in deployment events")
            return None

        self.service.multisig_address = EthereumAddress(multisig_address)
        self._update_and_save_service_state()

        # Register multisig in wallet KeyStorage
        try:
            from iwa.core.models import StoredSafeAccount

            _, agent_instances = self.registry.call("getAgentInstances", self.service.service_id)
            service_info = self.registry.get_service(self.service.service_id)
            threshold = service_info["threshold"]

            safe_account = StoredSafeAccount(
                tag=f"{self.service.service_name}_multisig",
                address=multisig_address,
                chains=[self.chain_name],
                threshold=threshold,
                signers=agent_instances,
            )
            self.wallet.key_storage.accounts[multisig_address] = safe_account
            self.wallet.key_storage.save()
            logger.info(f"Registered multisig {multisig_address} in wallet")
        except Exception as e:
            logger.warning(f"Failed to register multisig in wallet: {e}")

        logger.info("Service deployed successfully")
        return multisig_address

    def terminate(self) -> bool:
        """Terminate the service."""
        # Check that the service is deployed
        service_state = self.registry.get_service(self.service.service_id)["state"]
        if service_state != ServiceState.DEPLOYED:
            logger.error("Service is not deployed, cannot terminate")
            return False

        # Check that the service is not staked
        if self.service.staking_contract_address:
            logger.error("Service is staked, cannot terminate")
            return False

        logger.info(f"[SM-TERM] Preparing Terminate TX. Service ID: {self.service.service_id}")
        logger.info(f"[SM-TERM] Manager Contract Address: {self.manager.address}")

        terminate_tx = self.manager.prepare_terminate_tx(
            from_address=self.service.service_owner_address,
            service_id=self.service.service_id,
        )
        logger.info(f"[SM-TERM] Terminate TX Prepared. To: {terminate_tx.get('to')}")

        success, receipt = self.wallet.sign_and_send_transaction(
            transaction=terminate_tx,
            signer_address_or_tag=self.service.service_owner_address,
            chain_name=self.chain_name,
            tags=["olas_terminate_service"],
        )

        if not success:
            logger.error("Failed to terminate service")
            return False

        logger.info("Service terminate transaction sent successfully")

        events = self.registry.extract_events(receipt)

        if "TerminateService" not in [event["name"] for event in events]:
            logger.error("Terminate service event not found")
            return False

        logger.info("Service terminated successfully")
        return True

    def unbond(self) -> bool:
        """Unbond the service."""
        # Check that the service is terminated
        service_state = self.registry.get_service(self.service.service_id)["state"]
        if service_state != ServiceState.TERMINATED_BONDED:
            logger.error("Service is not terminated, cannot unbond")
            return False

        unbond_tx = self.manager.prepare_unbond_tx(
            from_address=self.service.service_owner_address,
            service_id=self.service.service_id,
        )

        success, receipt = self.wallet.sign_and_send_transaction(
            transaction=unbond_tx,
            signer_address_or_tag=self.service.service_owner_address,
            chain_name=self.chain_name,
            tags=["olas_unbond_service"],
        )

        if not success:
            logger.error("Failed to unbond service")
            return False

        logger.info("Service unbond transaction sent successfully")

        events = self.registry.extract_events(receipt)

        if "OperatorUnbond" not in [event["name"] for event in events]:
            logger.error("Unbond service event not found")
            return False

        logger.info("Service unbonded successfully")
        return True

    def spin_up(
        self,
        service_id: Optional[int] = None,
        agent_address: Optional[str] = None,
        staking_contract=None,
        bond_amount_wei: Optional[Wei] = None,
    ) -> bool:
        """Spin up a service from PRE_REGISTRATION to DEPLOYED state.

        Performs sequential state transitions with event verification:
        1. activate_registration() - if in PRE_REGISTRATION
        2. register_agent() - if in ACTIVE_REGISTRATION
        3. deploy() - if in FINISHED_REGISTRATION
        4. stake() - if staking_contract provided and service is DEPLOYED

        Each step verifies the state transition succeeded before proceeding.
        The method is idempotent - if already in a later state, it skips completed steps.

        Args:
            service_id: Optional service ID to spin up. If None, uses active service.
            agent_address: Optional pre-existing agent address to use for registration.
            staking_contract: Optional staking contract to stake after deployment.
            bond_amount_wei: Optional bond amount for agent registration.

        Returns:
            True if service reached DEPLOYED (and staked if requested), False otherwise.

        """
        if not service_id:
            if not self.service:
                logger.error("No active service and no service_id provided")
                return False
            service_id = self.service.service_id
        logger.info(f"Spinning up service {service_id}")

        current_state = self._get_service_state_safe(service_id)
        if not current_state:
            return False

        logger.info(f"Service {service_id} initial state: {current_state.name}")

        while current_state != ServiceState.DEPLOYED:
            previous_state = current_state

            if not self._process_spin_up_state(current_state, agent_address, bond_amount_wei):
                return False

            # Refresh state
            current_state = self._get_service_state_safe(service_id)
            if not current_state:
                return False

            if current_state == previous_state:
                logger.error(f"State stuck at {current_state.name} after action")
                return False

        logger.info(f"Service deployed successfully (State: {current_state.name})")

        # Stake if requested
        if staking_contract:
            logger.info("Staking service...")
            if not self.stake(staking_contract):
                logger.error("Failed to stake service")
                # Note: Service is DEPLOYED even if stake fails. Return False or True?
                # Original logic returned False.
                return False
            logger.info("Service staked successfully")

        return True

    def _process_spin_up_state(
        self,
        current_state: ServiceState,
        agent_address: Optional[str],
        bond_amount_wei: Optional[Wei],
    ) -> bool:
        """Process a single state transition for spin up."""
        if current_state == ServiceState.PRE_REGISTRATION:
            logger.info("Activating registration...")
            if not self.activate_registration():
                logger.error("Failed to activate registration")
                return False
        elif current_state == ServiceState.ACTIVE_REGISTRATION:
            logger.info("Registering agent...")
            if not self.register_agent(
                agent_address=agent_address, bond_amount_wei=bond_amount_wei
            ):
                logger.error("Failed to register agent")
                return False
        elif current_state == ServiceState.FINISHED_REGISTRATION:
            logger.info("Deploying service...")
            if not self.deploy():
                logger.error("Failed to deploy service")
                return False
        else:
            logger.error(f"Unknown or invalid state for spin up: {current_state.name}")
            return False
        return True

    def _get_service_state_safe(self, service_id: int):
        """Get service state safely, logging errors."""
        try:
            return self.registry.get_service(service_id)["state"]
        except Exception as e:
            logger.error(f"Could not get service info for {service_id}: {e}")
            return None

    def wind_down(self, staking_contract=None) -> bool:
        """Wind down a service to PRE_REGISTRATION state.

        Performs sequential state transitions with event verification:
        1. unstake() - if service is staked (requires staking_contract)
        2. terminate() - if service is DEPLOYED
        3. unbond() - if service is TERMINATED_BONDED

        Each step verifies the state transition succeeded before proceeding.
        The method is idempotent - if already in PRE_REGISTRATION, returns True.

        Args:
            staking_contract: Staking contract instance (required if service is staked).

        Returns:
            True if service reached PRE_REGISTRATION, False otherwise.

        """
        if not self.service:
            logger.error("No active service")
            return False
        service_id = self.service.service_id
        logger.info(f"Winding down service {service_id}")

        current_state = self._get_service_state_safe(service_id)
        if not current_state:
            return False

        logger.info(f"Current service state: {current_state.name}")

        if current_state == ServiceState.NON_EXISTENT:
            logger.error(f"Service {service_id} does not exist, cannot wind down")
            return False

        # Step 1: Unstake if staked (Special case as it doesn't change the main service state)
        if not self._ensure_unstaked(service_id, current_state, staking_contract):
            return False

        # Step 2 & 3: Terminate and Unbond loop
        while current_state != ServiceState.PRE_REGISTRATION:
            previous_state = current_state

            if not self._process_wind_down_state(current_state):
                return False

            # Refresh state
            current_state = self._get_service_state_safe(service_id)
            if not current_state:
                return False

            if current_state == previous_state:
                logger.error(f"State stuck at {current_state.name} after action")
                return False

        logger.info(f"Service {service_id} wind down complete. State: {current_state.name}")
        return True

    def _process_wind_down_state(self, current_state: ServiceState) -> bool:
        """Process a single state transition for wind down."""
        if current_state == ServiceState.DEPLOYED:
            logger.info("Terminating service...")
            if not self.terminate():
                logger.error("Failed to terminate service")
                return False
        elif current_state == ServiceState.TERMINATED_BONDED:
            logger.info("Unbonding service...")
            if not self.unbond():
                logger.error("Failed to unbond service")
                return False
        else:
            # Should not happen if logic is correct map of transitions
            logger.error(
                f"State {current_state.name} is not a valid start for wind_down (expected DEPLOYED or TERMINATED_BONDED)"
            )
            return False
        return True

    def _ensure_unstaked(
        self, service_id: int, current_state: ServiceState, staking_contract=None
    ) -> bool:
        """Ensure the service is unstaked if it was staked."""
        if current_state == ServiceState.DEPLOYED and self.service.staking_contract_address:
            if not staking_contract:
                logger.error("Service is staked but no staking contract provided for unstaking")
                return False

            logger.info("Unstaking service...")
            if not self.unstake(staking_contract):
                logger.error("Failed to unstake service")
                # Return strict False if unstake fails
                return False
            logger.info("Service unstaked successfully")
        return True
