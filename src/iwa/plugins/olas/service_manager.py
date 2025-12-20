"""Olas service manager."""

from typing import Dict, List, Optional, Union

from web3 import Web3

from iwa.core.chain import ChainInterfaces
from iwa.core.contracts.erc20 import ERC20Contract
from iwa.core.models import Config
from iwa.core.utils import configure_logger
from iwa.core.wallet import Wallet
from iwa.plugins.olas.constants import (
    DEFAULT_TOKEN_ADDRESS,
    SERVICE_MANAGER_ADDRESS_GNOSIS,
    SERVICE_REGISTRY_ADDRESS_GNOSIS,
    SERVICE_REGISTRY_TOKEN_UTILITY_ADDRESS_GNOSIS,
    TRADER_CONFIG_HASH,
    AgentType,
)
from iwa.plugins.olas.contracts.service import (
    ServiceManagerContract,
    ServiceRegistryContract,
    ServiceState,
)
from iwa.plugins.olas.contracts.staking import StakingState
from iwa.plugins.olas.models import OlasConfig, Service

logger = configure_logger()


class ServiceManager:
    """ServiceManager for OLAS services with multi-service support."""

    def __init__(self, wallet: Wallet, service_key: Optional[str] = None):
        """Initialize ServiceManager.

        Args:
            wallet: The wallet instance for signing transactions.
            service_key: Optional key (chain_name:service_id) to select a specific service.
                        If not provided, uses the active_service_key from config.

        """
        self.wallet = wallet
        self.global_config = Config()

        # Get or create OlasConfig
        if "olas" not in self.global_config.plugins:
            self.global_config.plugins["olas"] = OlasConfig()

        self.olas_config: OlasConfig = self.global_config.plugins["olas"]

        # Set active service if key provided
        if service_key:
            self.olas_config.active_service_key = service_key

        # Get active service (may be None for new services)
        self.service = self.olas_config.get_active_service()

        # Initialize contracts (default to gnosis)
        chain_name = self.service.chain_name if self.service else "gnosis"
        self._init_contracts(chain_name)

    def _init_contracts(self, chain_name: str) -> None:
        """Initialize contracts for the given chain."""
        # TODO: Support multiple chains with different contract addresses
        self.registry = ServiceRegistryContract(SERVICE_REGISTRY_ADDRESS_GNOSIS)
        self.manager = ServiceManagerContract(SERVICE_MANAGER_ADDRESS_GNOSIS)
        self.chain_name = chain_name

    def _save_config(self) -> None:
        """Persist configuration to config.toml."""
        self.global_config.save_config()

    def get(self) -> Optional[Dict]:
        """Get service details by ID."""
        if not self.service:
            logger.error("No active service")
            return None
        return self.registry.get_service(self.service.service_id)


    def create(
        self,
        chain_name: str = "gnosis",
        service_name: Optional[str] = None,
        agent_ids: Optional[List[Union[AgentType, int]]] = None,
        service_owner_address_or_tag: Optional[str] = None,
        token_address_or_tag: Optional[str] = None,
        bond_amount: int = 1,
    ) -> Optional[int]:
        """Create a new service.

        Args:
            chain_name: The blockchain to create the service on.
            service_name: Human-readable name for the service (auto-generated if not provided).
            agent_ids: List of agent type IDs or AgentType enum values.
                       Defaults to [AgentType.TRADER] if not provided.
            service_owner_address_or_tag: The owner address or tag.
            token_address_or_tag: Token address for staking (optional).
            bond_amount: Bond amount in tokens.

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

        # Create agent_params: [[instances_per_agent, bond_amount], ...]
        agent_params = [[1, bond_amount] for _ in agent_id_values]

        create_tx = self.manager.prepare_create_tx(
            from_address=self.wallet.master_account.address,
            service_owner=service_owner_account.address,
            token_address=token_address if token_address else DEFAULT_TOKEN_ADDRESS,
            config_hash=bytes.fromhex(TRADER_CONFIG_HASH),
            agent_ids=agent_id_values,
            agent_params=agent_params,
            threshold=1,
        )
        success, receipt = self.wallet.sign_and_send_transaction(
            transaction=create_tx,
            signer_address_or_tag=self.wallet.master_account.address,
            chain_name=chain_name,
        )

        if not success:
            logger.error("Failed to create service")
            return None

        logger.info("Service creation transaction sent successfully")

        events = self.registry.extract_events(receipt)

        service_id = None

        for event in events:
            if event["name"] == "CreateService":
                service_id = event["args"]["serviceId"]
                logger.info(f"Service created with ID: {service_id}")
                break

        if service_id is None:
            logger.error("Service creation event not found")
            return None

        # Create Service model and add to config
        new_service = Service(
            service_name=service_name or f"service_{service_id}",
            chain_name=chain_name,
            service_id=service_id,
            agent_ids=agent_id_values,
            service_owner_address=service_owner_account.address,
        )

        self.olas_config.add_service(new_service)
        self.olas_config.active_service_key = new_service.key
        self.service = new_service

        # Persist configuration
        self._save_config()

        # If no token address is provided, skip approving staking tokens
        if not token_address:
            return service_id

        erc20_contract = ERC20Contract(token_address)

        # Approve the service registry token utility contract to spend the staking tokens
        approve_tx = erc20_contract.prepare_approve_tx(
            from_address=self.wallet.master_account.address,
            spender=SERVICE_REGISTRY_TOKEN_UTILITY_ADDRESS_GNOSIS,
            amount_wei=2 * bond_amount,
        )

        logger.info("Approving OLAS token for staking contract")
        success, receipt = self.wallet.sign_and_send_transaction(
            transaction=approve_tx,
            signer_address_or_tag=self.wallet.master_account.address,
            chain_name=chain_name,
        )

        if not success:
            logger.error("Failed to approve staking contract [ERC20]")
            return False

        logger.info("OLAS token approved for staking contract")

        return service_id


    def activate_registration(self) -> bool:
        """Activate registration for the service."""
        # Check that the service is created
        service_state = self.registry.get_service(self.service.service_id)["state"]
        if service_state != ServiceState.PRE_REGISTRATION:
            logger.error("Service is not created, cannot activate registration")
            return False

        activate_tx = self.manager.prepare_activate_registration_tx(
            from_address=self.wallet.master_account.address, service_id=self.service.service_id
        )
        success, receipt = self.wallet.sign_and_send_transaction(
            transaction=activate_tx,
            signer_address_or_tag=self.wallet.master_account.address,
            chain_name=self.service.chain_name,
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

    def register_agent(self, agent_address: Optional[str] = None) -> bool:
        """Register an agent for the service.

        Args:
            agent_address: Optional existing agent address to use.
                           If not provided, a new agent account will be created and funded.

        Returns:
            True if registration succeeded, False otherwise.

        """
        # Check that the service is in active registration
        service_state = self.registry.get_service(self.service.service_id)["state"]
        if service_state != ServiceState.ACTIVE_REGISTRATION:
            logger.error("Service is not in active registration, cannot register agent")
            return False

        # Use existing agent or create a new one
        if agent_address:
            agent_account_address = agent_address
            logger.info(f"Using existing agent address: {agent_address}")
        else:
            # Create a new account for the service
            agent_tag = f"service_{self.service.service_id}_agent"
            agent_account = self.wallet.key_storage.create_account(agent_tag)
            agent_account_address = agent_account.address
            logger.info(f"Created new agent account: {agent_account_address}")

            # Fund the agent (only for newly created accounts)
            tx_hash = self.wallet.send(
                from_address_or_tag=self.wallet.master_account.address,
                to_address_or_tag=agent_account_address,
                token_address_or_name="native",
                amount_wei=Web3.to_wei(1, "ether"),  # 1 xDAI
            )
            if not tx_hash:
                logger.error("Failed to fund agent account")
                return False

        # Register the agent
        register_tx = self.manager.prepare_register_agents_tx(
            from_address=self.wallet.master_account.address,
            service_id=self.service.service_id,
            agent_instances=[agent_account_address],
            agent_ids=self.service.agent_ids,
        )
        success, receipt = self.wallet.sign_and_send_transaction(
            transaction=register_tx,
            signer_address_or_tag=self.wallet.master_account.address,
            chain_name=self.service.chain_name,
        )

        if not success:
            logger.error("Failed to register agent")
            return False

        logger.info("Agent registration transaction sent successfully")

        events = self.registry.extract_events(receipt)

        if "RegisterInstance" not in [event["name"] for event in events]:
            logger.error("Agent registration event not found")
            return False

        self.service.agent_address = agent_account_address
        self._save_config()
        return True

    def deploy(self) -> Optional[str]:
        """Deploy the service."""
        # Check that the service has finished registration
        service_state = self.registry.get_service(self.service.service_id)["state"]
        if service_state != ServiceState.FINISHED_REGISTRATION:
            logger.error("Service registration is not finished, cannot deploy")
            return False

        deploy_tx = self.manager.prepare_deploy_tx(
            from_address=self.wallet.master_account.address,
            service_id=self.service.service_id,
        )

        success, receipt = self.wallet.sign_and_send_transaction(
            transaction=deploy_tx,
            signer_address_or_tag=self.wallet.master_account.address,
            chain_name=self.service.chain_name,
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

        self.service.multisig_address = multisig_address
        self._save_config()
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

        terminate_tx = self.manager.prepare_terminate_tx(
            from_address=self.wallet.master_account.address,
            service_id=self.service.service_id,
        )

        success, receipt = self.wallet.sign_and_send_transaction(
            transaction=terminate_tx,
            signer_address_or_tag=self.wallet.master_account.address,
            chain_name=self.service.chain_name,
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
            from_address=self.wallet.master_account.address,
            service_id=self.service.service_id,
        )

        success, receipt = self.wallet.sign_and_send_transaction(
            transaction=unbond_tx,
            signer_address_or_tag=self.wallet.master_account.address,
            chain_name=self.service.chain_name,
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

    def stake(self, staking_contract) -> bool:
        """Stake the service in a staking contract."""
        erc20_contract = ERC20Contract(staking_contract.staking_token_address)

        # Check that she service is deployed
        service_state = self.registry.get_service(self.service.service_id)["state"]
        if service_state != ServiceState.DEPLOYED:
            logger.error("Service is not deployed, cannot stake")
            return False

        logger.info("Service is deployed")

        # Check that there are free slots
        if staking_contract.get_service_ids() == staking_contract.max_num_services:
            logger.error("Staking contract is full, no free slots available")
            return False

        # Check that there are enough OLAS
        if (
            erc20_contract.balance_of_wei(self.wallet.master_account.address)
            < staking_contract.min_staking_deposit
        ):
            logger.error("Not enough tokens to stake service")
            return False

        # Approve the staking contract to move the service token
        approve_tx = self.registry.prepare_approve_tx(
            from_address=self.wallet.master_account.address,
            spender=staking_contract.address,
            id_=self.service.service_id,
        )

        success, receipt = self.wallet.sign_and_send_transaction(
            transaction=approve_tx,
            signer_address_or_tag=self.wallet.master_account.address,
            chain_name=self.service.chain_name,
        )
        logger.info("Approving service token for staking contract")

        if not success:
            logger.error("Failed to approve staking contract [Service Registry]")
            return False

        logger.info("Service token approved for staking contract")

        # Stake the service
        stake_tx = staking_contract.prepare_stake_tx(
            from_address=self.wallet.master_account.address,
            service_id=self.service.service_id,
        )

        success, receipt = self.wallet.sign_and_send_transaction(
            transaction=stake_tx,
            signer_address_or_tag=self.wallet.master_account.address,
            chain_name=self.service.chain_name,
        )

        if not success:
            logger.error("Failed to stake service")
            return False

        logger.info("Service stake transaction sent successfully")

        events = staking_contract.extract_events(receipt)

        if "ServiceStaked" not in [event["name"] for event in events]:
            logger.error("Stake service event not found")
            return False

        if staking_contract.get_staking_state(self.service.service_id) != StakingState.STAKED:
            logger.error("Service is not staked after transaction")
            return False

        self.service.staking_contract_address = staking_contract.address
        self._save_config()
        logger.info("Service staked successfully")
        return True

    def unstake(self, staking_contract) -> bool:
        """Unstake the service from the staking contract."""
        # Check that the service is staked
        staking_state = staking_contract.get_staking_state(self.service.service_id)
        if staking_state != StakingState.STAKED:
            logger.error("Service is not staked, cannot unstake")
            return False

        # Check that enough time has passed since staking
        # TODO

        # Unstake the service
        unstake_tx = staking_contract.prepare_unstake_tx(
            from_address=self.wallet.master_account.address,
            service_id=self.service.service_id,
        )

        success, receipt = self.wallet.sign_and_send_transaction(
            transaction=unstake_tx,
            signer_address_or_tag=self.wallet.master_account.address,
            chain_name=self.service.chain_name,
        )

        if not success:
            logger.error("Failed to unstake service")
            return False

        logger.info("Service unstake transaction sent successfully")

        events = staking_contract.extract_events(receipt)

        if "ServiceUnstaked" not in [event["name"] for event in events]:
            logger.error("Unstake service event not found")
            return False

        self.service.staking_contract_address = None
        self._save_config()

        logger.info("Service unstaked successfully")
        return True

    def spin_up(  # noqa: C901
        self,
        staking_contract=None,
        agent_address: Optional[str] = None,
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
            staking_contract: Optional staking contract to stake after deployment.
            agent_address: Optional pre-existing agent address to use for registration.

        Returns:
            True if service reached DEPLOYED (and staked if requested), False otherwise.

        """
        service_id = self.service.service_id
        logger.info(f"Spinning up service {service_id}")

        # Get current state
        current_state = self.registry.get_service(service_id)["state"]
        logger.info(f"Service {service_id} current state: {current_state.name}")

        # Step 1: Activate registration if in PRE_REGISTRATION
        if current_state == ServiceState.PRE_REGISTRATION:
            logger.info("Activating registration...")
            if not self.activate_registration():
                logger.error("Failed to activate registration")
                return False

            # Verify state changed
            current_state = self.registry.get_service(service_id)["state"]
            if current_state != ServiceState.ACTIVE_REGISTRATION:
                logger.error(
                    f"State did not change to ACTIVE_REGISTRATION after activation, got {current_state.name}"
                )
                return False
            logger.info("Registration activated successfully")

        # Step 2: Register agent if in ACTIVE_REGISTRATION
        if current_state == ServiceState.ACTIVE_REGISTRATION:
            logger.info("Registering agent...")
            if not self.register_agent(agent_address=agent_address):
                logger.error("Failed to register agent")
                return False

            # Verify state changed
            current_state = self.registry.get_service(service_id)["state"]
            if current_state != ServiceState.FINISHED_REGISTRATION:
                logger.error(
                    f"State did not change to FINISHED_REGISTRATION after registration, got {current_state.name}"
                )
                return False
            logger.info("Agent registered successfully")

        # Step 3: Deploy if in FINISHED_REGISTRATION
        if current_state == ServiceState.FINISHED_REGISTRATION:
            logger.info("Deploying service...")
            multisig_address = self.deploy()
            if not multisig_address:
                logger.error("Failed to deploy service")
                return False

            # Verify state changed
            current_state = self.registry.get_service(service_id)["state"]
            if current_state != ServiceState.DEPLOYED:
                logger.error(f"State did not change to DEPLOYED after deploy, got {current_state.name}")
                return False
            logger.info(f"Service deployed successfully with multisig: {multisig_address}")

        # Step 4: Stake if staking contract provided and service is DEPLOYED
        if current_state == ServiceState.DEPLOYED and staking_contract:
            logger.info("Staking service...")
            if not self.stake(staking_contract):
                logger.error("Failed to stake service")
                return False
            logger.info("Service staked successfully")

        # Final verification
        final_state = self.registry.get_service(service_id)["state"]
        if final_state != ServiceState.DEPLOYED:
            logger.error(f"Service {service_id} is not in DEPLOYED state, got {final_state.name}")
            return False

        logger.info(f"Service {service_id} spin up complete. State: {final_state.name}")
        return True

    def wind_down(self, staking_contract=None) -> bool:  # noqa: C901
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
        service_id = self.service.service_id
        logger.info(f"Winding down service {service_id}")

        # Get current state
        current_state = self.registry.get_service(service_id)["state"]
        logger.info(f"Service {service_id} current state: {current_state.name}")

        # Already in target state
        if current_state == ServiceState.PRE_REGISTRATION:
            logger.info(f"Service {service_id} is already in PRE_REGISTRATION state")
            return True

        # Step 1: Unstake if staked
        if current_state == ServiceState.DEPLOYED and self.service.staking_contract_address:
            if not staking_contract:
                logger.error("Service is staked but no staking contract provided for unstaking")
                return False

            logger.info("Unstaking service...")
            if not self.unstake(staking_contract):
                logger.error("Failed to unstake service")
                return False
            logger.info("Service unstaked successfully")

        # Refresh state after potential unstake
        current_state = self.registry.get_service(service_id)["state"]

        # Step 2: Terminate if DEPLOYED
        if current_state == ServiceState.DEPLOYED:
            logger.info("Terminating service...")
            if not self.terminate():
                logger.error("Failed to terminate service")
                return False

            # Verify state changed
            current_state = self.registry.get_service(service_id)["state"]
            if current_state != ServiceState.TERMINATED_BONDED:
                logger.error(
                    f"State did not change to TERMINATED_BONDED after terminate, got {current_state.name}"
                )
                return False
            logger.info("Service terminated successfully")

        # Step 3: Unbond if TERMINATED_BONDED
        if current_state == ServiceState.TERMINATED_BONDED:
            logger.info("Unbonding service...")
            if not self.unbond():
                logger.error("Failed to unbond service")
                return False

            # Verify state changed
            current_state = self.registry.get_service(service_id)["state"]
            if current_state != ServiceState.PRE_REGISTRATION:
                logger.error(
                    f"State did not change to PRE_REGISTRATION after unbond, got {current_state.name}"
                )
                return False
            logger.info("Service unbonded successfully")

        # Final verification
        final_state = self.registry.get_service(service_id)["state"]
        if final_state != ServiceState.PRE_REGISTRATION:
            logger.error(f"Service {service_id} is not in PRE_REGISTRATION state, got {final_state.name}")
            return False

        logger.info(f"Service {service_id} wind down complete. State: {final_state.name}")
        return True
