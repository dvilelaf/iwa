"""Olas service manager."""

from typing import Dict, List, Optional, Union

from web3 import Web3
from web3.types import Wei

from iwa.core.chain import ChainInterfaces
from iwa.core.constants import NATIVE_CURRENCY_ADDRESS
from iwa.core.contracts.erc20 import ERC20Contract
from iwa.core.models import Config
from iwa.core.utils import configure_logger
from iwa.core.wallet import Wallet
from iwa.plugins.olas.constants import (
    OLAS_CONTRACTS,
    PAYMENT_TYPE_NATIVE,
    TRADER_CONFIG_HASH,
    AgentType,
)
from iwa.plugins.olas.contracts.mech import MechContract
from iwa.plugins.olas.contracts.mech_marketplace import MechMarketplaceContract
from iwa.plugins.olas.contracts.service import (
    ServiceManagerContract,
    ServiceRegistryContract,
    ServiceState,
)
from iwa.plugins.olas.contracts.staking import StakingContract, StakingState
from iwa.plugins.olas.models import OlasConfig, Service, StakingStatus

logger = configure_logger()


class ServiceManager:
    """ServiceManager for OLAS services with multi-service support."""

    def __init__(self, wallet: Wallet, service_key: Optional[str] = None):
        """Initialize ServiceManager.

        Args:
            wallet: The wallet instance for signing transactions.
            service_key: Optional key (chain_name:service_id) to select a specific service.
                        If not provided, service operations require explicit service selection.

        """
        self.wallet = wallet
        self.global_config = Config()

        # Get or create OlasConfig
        if "olas" not in self.global_config.plugins:
            self.global_config.plugins["olas"] = OlasConfig()

        self.olas_config: OlasConfig = self.global_config.plugins["olas"]

        # Get service by key if provided
        self.service = None
        if service_key and ":" in service_key:
            chain_name, service_id = service_key.split(":", 1)
            self.service = self.olas_config.get_service(chain_name, int(service_id))

        # Initialize contracts (default to gnosis)
        chain_name = self.service.chain_name if self.service else "gnosis"
        self._init_contracts(chain_name)

        # Initialize TransferService from wallet
        self.transfer_service = self.wallet.transfer_service

    def _init_contracts(self, chain_name: str) -> None:
        """Initialize contracts for the given chain."""
        chain_interface = ChainInterfaces().get(chain_name)

        # Get protocol contracts from plugin-local constants
        protocol_contracts = OLAS_CONTRACTS.get(chain_name.lower(), {})
        registry_address = protocol_contracts.get("OLAS_SERVICE_REGISTRY")
        manager_address = protocol_contracts.get("OLAS_SERVICE_MANAGER")

        if not registry_address or not manager_address:
            raise ValueError(f"OLAS contracts not found for chain: {chain_name}")

        self.registry = ServiceRegistryContract(registry_address, chain_name=chain_name)
        self.manager = ServiceManagerContract(manager_address, chain_name=chain_name)
        self.chain_interface = chain_interface
        self.chain_name = chain_interface.chain.name.lower()

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

        # Create agent_params: [[instances_per_agent, bond_amount_wei], ...]
        # agent_params = [[1, bond_amount_wei] for _ in agent_id_values]
        # Use dictionary for explicit struct encoding
        agent_params = [{"slots": 1, "bond": bond_amount_wei} for _ in agent_id_values]

        print(
            f"DEBUG: ServiceManager.create bond_amount_wei={bond_amount_wei} agent_params={agent_params}"
        )

        create_tx = self.manager.prepare_create_tx(
            from_address=self.wallet.master_account.address,
            service_owner=service_owner_account.address,
            token_address=token_address if token_address else NATIVE_CURRENCY_ADDRESS,
            config_hash=bytes.fromhex(TRADER_CONFIG_HASH),
            agent_ids=agent_id_values,
            agent_params=agent_params,
            threshold=1,
        )

        print(
            f"DEBUG: ServiceManager.create token_address={token_address if token_address else NATIVE_CURRENCY_ADDRESS}"
        )
        print(f"DEBUG: ServiceManager.create tx_data={create_tx.get('data')}")
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

        if not service_id:
            logger.error("Service creation event not found or service ID not in event")
            return None

        # Create service model
        new_service = Service(
            service_name=service_name or f"service_{service_id}",
            chain_name=chain_name,
            service_id=service_id,
            agent_ids=[int(a) for a in agent_ids],
            service_owner_address=service_owner_account.address,
            token_address=token_address,
        )

        self.olas_config.add_service(new_service)
        self.service = new_service

        # Persist configuration
        self._save_config()

        # If no token address is provided, skip approving staking tokens
        if not token_address:
            return service_id

        # Approve the service registry token utility contract
        protocol_contracts = OLAS_CONTRACTS.get(chain_name.lower(), {})
        utility_address = protocol_contracts.get("OLAS_SERVICE_REGISTRY_TOKEN_UTILITY")

        if not utility_address:
            logger.error(f"OLAS Service Registry Token Utility not found for chain: {chain_name}")
            return service_id  # Return service_id anyway, but log error (or should we fail?)

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
            return service_id
        return service_id

    def activate_registration(self) -> bool:
        """Activate registration for the service."""
        service_id = self.service.service_id
        # Check that the service is created
        service_info = self.registry.get_service(service_id)
        service_state = service_info["state"]
        if service_state != ServiceState.PRE_REGISTRATION:
            logger.error("Service is not created, cannot activate registration")
            return False

        token_address = self.service.token_address
        if not token_address:
            try:
                token_address = self.registry.get_token(service_id)
            except Exception:
                # Default to native if query fails
                token_address = "0x0000000000000000000000000000000000000000"

        security_deposit = service_info["security_deposit"]

        # Prepare activation transaction
        # NOTE: For token-based services, we created an approval in create() for the bond amount.
        # Here we only need to provide the 'security_deposit' (native value) which is typically 1 wei
        # for token services, or the full bond for native services.
        activate_tx = self.manager.prepare_activate_registration_tx(
            from_address=self.wallet.master_account.address,
            service_id=service_id,
            value=security_deposit,
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

    def register_agent(  # noqa: C901
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
            # Create a new account for the service (or use existing if found)
            agent_tag = f"service_{self.service.service_id}_agent"
            try:
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
                logger.info(f"Funded agent account: {tx_hash}")
            except ValueError:
                # Handle case where account already exists
                agent_account = self.wallet.key_storage.get_account(agent_tag)
                agent_account_address = agent_account.address
                logger.info(f"Using existing agent account: {agent_account_address}")
        # Register the agent
        service_id = self.service.service_id
        service_info = self.registry.get_service(service_id)
        token_address = self.service.token_address
        if not token_address:
            try:
                token_address = self.registry.get_token(service_id)
            except Exception:
                token_address = "0x0000000000000000000000000000000000000000"

        security_deposit = service_info["security_deposit"]
        is_native = str(token_address) == "0x0000000000000000000000000000000000000000"

        if not is_native:
            if not bond_amount_wei:
                logger.warning(
                    "No bond amount provided for token bonding. Agent might fail to bond."
                )
            else:
                # 1. Fund Agent with Bond Amount (Token)
                logger.info(
                    f"Funding agent {agent_account_address} with {bond_amount_wei} of token {token_address}"
                )
                fund_success = self.wallet.transfer_service.send(
                    from_address_or_tag=self.wallet.master_account.address,
                    to_address_or_tag=agent_account_address,
                    token_address_or_name=token_address,
                    amount_wei=bond_amount_wei,
                    chain_name=self.service.chain_name,
                )
                if not fund_success:
                    logger.error("Failed to fund agent with bond tokens")
                    return False

                # 2. Agent Approves Token Utility
                logger.info(f"Agent {agent_account_address} approving Token Utility for bond")
                # Need to use agent account as signer. It's stored in key_storage.
                # Wallet doesn't expose 'approve_erc20' with custom signer object directly?
                # TransferService.approve_erc20 takes 'owner_address_or_tag'.
                # Assuming 'agent_account_address' is recognized by wallet key_storage (it is, created there).
                utility_address = str(
                    OLAS_CONTRACTS[self.service.chain_name]["OLAS_SERVICE_REGISTRY_TOKEN_UTILITY"]
                )

                approve_success = self.wallet.transfer_service.approve_erc20(
                    token_address_or_name=token_address,
                    spender_address_or_tag=utility_address,
                    amount_wei=bond_amount_wei,
                    owner_address_or_tag=agent_account_address,
                    chain_name=self.service.chain_name,
                )
                if not approve_success:
                    logger.error("Failed to approve token for agent registration")
                    return False

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

        # Register multisig in wallet KeyStorage
        try:
            from iwa.core.models import StoredSafeAccount

            _, agent_instances = self.registry.call("getAgentInstances", self.service.service_id)
            service_info = self.registry.get_service(self.service.service_id)
            threshold = service_info["threshold"]

            safe_account = StoredSafeAccount(
                tag=f"{self.service.service_name}_multisig",
                address=multisig_address,
                chains=[self.service.chain_name],
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
        if not self.service:
            logger.error("No active service")
            return False

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
        except Exception as e:
            logger.error(f"Failed to get service info: {e}")
            return StakingStatus(
                is_staked=True,
                staking_state=staking_state.name,
                staking_contract_address=str(staking_address),
            )

        return StakingStatus(
            is_staked=True,
            staking_state=staking_state.name,
            staking_contract_address=str(staking_address),
            mech_requests_this_epoch=info["mech_requests_this_epoch"],
            required_mech_requests=info["required_mech_requests"],
            remaining_mech_requests=info["remaining_mech_requests"],
            has_enough_requests=info["has_enough_requests"],
            liveness_ratio_passed=info["liveness_ratio_passed"],
            accrued_reward_wei=info["accrued_reward_wei"],
            epoch_end_utc=info["epoch_end_utc"].isoformat() if info["epoch_end_utc"] else None,
            remaining_epoch_seconds=info["remaining_epoch_seconds"],
            activity_checker_address=staking.activity_checker_address,
            liveness_ratio=staking.activity_checker.liveness_ratio,
        )

    def claim_rewards(self, staking_contract: Optional[StakingContract] = None) -> tuple[bool, int]:
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
                    chain_name=self.service.chain_name,
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
            claim_tx, signer_address_or_tag=self.wallet.master_account.address
        )
        if not success:
            logger.error("Failed to send claim transaction")
            return False, 0

        events = staking_contract.extract_events(receipt)
        if "RewardClaimed" not in [event["name"] for event in events]:
            logger.warning("RewardClaimed event not found, but transaction succeeded")

        logger.info(f"Successfully claimed {accrued_rewards / 1e18:.4f} OLAS rewards")
        return True, accrued_rewards

    def withdraw_rewards(self) -> tuple[bool, float]:
        """Withdraw OLAS from the service Safe to the configured withdrawal address.

        The OLAS tokens are transferred from the service's multisig to the
        withdrawal_address configured in the OlasConfig.

        Returns:
            Tuple of (success, olas_amount_transferred).

        """
        from iwa.plugins.olas.constants import OLAS_TOKEN_ADDRESS_GNOSIS

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
            chain_name=self.service.chain_name,
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
            chain_name=self.service.chain_name,
        )

        if not tx_hash:
            logger.error("Failed to transfer OLAS")
            return False, 0

        logger.info(f"Withdrew {olas_amount:.4f} OLAS to {withdrawal_address}")
        return True, olas_amount

    def call_checkpoint(
        self,
        staking_contract: Optional[StakingContract] = None,
        grace_period_seconds: int = 600,
    ) -> bool:
        """Call the checkpoint on the staking contract to close the current epoch.

        The checkpoint closes the current epoch, calculates rewards for all staked
        services, and starts a new epoch. Anyone can call this once the epoch has ended.

        This method will:
        1. Check if the service is staked
        2. Verify that the epoch has ended (with a grace period)
        3. Send the checkpoint transaction

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
            checkpoint_tx, signer_address_or_tag=self.wallet.master_account.address
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

    def spin_up(  # noqa: C901
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
            if not self.register_agent(
                agent_address=agent_address, bond_amount_wei=bond_amount_wei
            ):
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
                logger.error(
                    f"State did not change to DEPLOYED after deploy, got {current_state.name}"
                )
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
        if not self.service:
            logger.error("No active service")
            return False
        service_id = self.service.service_id
        logger.info(f"Winding down service {service_id}")

        # Get service state
        current_state = self.registry.get_service(service_id)["state"]
        logger.info(f"Current service state: {current_state.name}")

        if current_state == ServiceState.NON_EXISTENT:
            logger.error(f"Service {service_id} does not exist, cannot wind down")
            return False
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
            logger.error(
                f"Service {service_id} is not in PRE_REGISTRATION state, got {final_state.name}"
            )
            return False

        logger.info(f"Service {service_id} wind down complete. State: {final_state.name}")
        return True

    def send_mech_request(
        self,
        data: bytes,
        value: Optional[int] = None,
        mech_address: Optional[str] = None,
        use_marketplace: bool = False,
        use_new_abi: bool = False,
        priority_mech: Optional[str] = None,
        max_delivery_rate: Optional[int] = None,
        payment_type: Optional[bytes] = None,
        payment_data: bytes = b"",
        response_timeout: int = 300,
    ) -> Optional[str]:
        """Send a Mech request from the service multisig.

        Args:
            data: The request data (IPFS hash bytes).
            value: Payment value in wei. For marketplace, should match mech's maxDeliveryRate.
            mech_address: Address of the Mech contract (for legacy/direct flow).
            use_marketplace: Whether to use the Mech Marketplace flow.
            use_new_abi: Whether to use new ABI for legacy flow.
            priority_mech: Priority mech address (required for marketplace).
            max_delivery_rate: Max delivery rate in wei (for marketplace). If None, uses value.
            payment_type: Payment type bytes32 (for marketplace). Defaults to NATIVE.
            payment_data: Payment data (for marketplace).
            response_timeout: Timeout in seconds for marketplace request (60-300).

        Returns:
            The transaction hash if successful, None otherwise.

        """
        if not self.service:
            logger.error("No active service loaded")
            return None

        service_id = self.service.service_id
        multisig_address = self.service.multisig_address

        if not multisig_address:
            logger.error(f"Service {service_id} has no multisig address")
            return None

        if use_marketplace:
            return self._send_marketplace_mech_request(
                data=data,
                value=value,
                priority_mech=priority_mech,
                max_delivery_rate=max_delivery_rate,
                payment_type=payment_type,
                payment_data=payment_data,
                response_timeout=response_timeout,
            )
        else:
            return self._send_legacy_mech_request(
                data=data,
                value=value,
                mech_address=mech_address,
                use_new_abi=use_new_abi,
            )

    def _send_legacy_mech_request(
        self,
        data: bytes,
        value: Optional[int] = None,
        mech_address: Optional[str] = None,
        use_new_abi: bool = False,
    ) -> Optional[str]:
        """Send a legacy (direct) mech request."""
        if not self.service:
            logger.error("No active service")
            return None

        multisig_address = self.service.multisig_address
        protocol_contracts = OLAS_CONTRACTS.get(self.chain_name, {})
        mech_address = mech_address or protocol_contracts.get("OLAS_MECH")

        if not mech_address:
            logger.error(f"Legacy mech address not found for chain {self.chain_name}")
            return None

        mech = MechContract(str(mech_address), chain_name=self.chain_name, use_new_abi=use_new_abi)

        # Get mech price if value not provided
        if value is None:
            value = mech.get_price()
            logger.info(f"Using mech price: {value} wei")

        tx_data = mech.prepare_request_tx(
            from_address=multisig_address,
            data=data,
            value=value,
        )

        if not tx_data:
            logger.error("Failed to prepare legacy mech request transaction")
            return None

        return self._execute_mech_tx(
            tx_data=tx_data,
            to_address=str(mech_address),
            contract_instance=mech,
            expected_event="Request",
        )

    def _send_marketplace_mech_request(  # noqa: C901
        self,
        data: bytes,
        value: Optional[int] = None,
        priority_mech: Optional[str] = None,
        max_delivery_rate: Optional[int] = None,
        payment_type: Optional[bytes] = None,
        payment_data: bytes = b"",
        response_timeout: int = 300,
    ) -> Optional[str]:
        """Send a marketplace mech request with validation."""
        if not self.service:
            logger.error("No active service")
            return None

        multisig_address = self.service.multisig_address
        chain_name = (
            self.service.chain_name if self.service else getattr(self, "chain_name", "gnosis")
        )
        protocol_contracts = OLAS_CONTRACTS.get(chain_name, {})
        marketplace_address = protocol_contracts.get("OLAS_MECH_MARKETPLACE")

        if not marketplace_address:
            logger.error(f"Mech Marketplace address not found for chain {chain_name}")
            return None

        # Validate priority_mech is provided
        if not priority_mech:
            logger.error("priority_mech is required for marketplace requests")
            return None

        priority_mech = Web3.to_checksum_address(priority_mech)
        marketplace = MechMarketplaceContract(str(marketplace_address), chain_name=chain_name)

        # Validate priority mech is registered on marketplace
        try:
            mech_multisig = marketplace.call("checkMech", priority_mech)
            if mech_multisig == "0x0000000000000000000000000000000000000000":
                logger.error(f"Priority mech {priority_mech} is NOT registered on marketplace")
                return None
            logger.debug(f"Priority mech {priority_mech} -> multisig {mech_multisig}")
        except Exception as e:
            logger.error(f"Failed to verify priority mech registration: {e}")
            return None

        # Get mech's payment info for validation
        try:
            mech_factory = marketplace.call("mapAgentMechFactories", priority_mech)
            if mech_factory == "0x0000000000000000000000000000000000000000":
                logger.warning(
                    f"Priority mech {priority_mech} has no factory (may be unregistered)"
                )
            else:
                logger.debug(f"Priority mech factory: {mech_factory}")
        except Exception as e:
            logger.warning(f"Could not fetch mech factory: {e}")

        # Set defaults for payment
        if payment_type is None:
            payment_type = bytes.fromhex(PAYMENT_TYPE_NATIVE)

        # Default value: 0.01 xDAI
        if value is None:
            value = 10_000_000_000_000_000
            logger.info(f"Using default value: {value} wei (0.01 xDAI)")

        # max_delivery_rate should match value for fixed-price mechs
        if max_delivery_rate is None:
            max_delivery_rate = value
            logger.info(f"Using value as max_delivery_rate: {max_delivery_rate}")

        # Validate response_timeout is within marketplace bounds
        try:
            min_timeout = marketplace.call("minResponseTimeout")
            max_timeout = marketplace.call("maxResponseTimeout")
            if response_timeout < min_timeout or response_timeout > max_timeout:
                logger.error(
                    f"response_timeout {response_timeout} out of bounds [{min_timeout}, {max_timeout}]"
                )
                return None
            logger.debug(
                f"Response timeout {response_timeout}s within bounds [{min_timeout}, {max_timeout}]"
            )
        except Exception as e:
            logger.warning(f"Could not validate response_timeout bounds: {e}")

        # Validate payment type has balance tracker
        try:
            balance_tracker = marketplace.call("mapPaymentTypeBalanceTrackers", payment_type)
            if balance_tracker == "0x0000000000000000000000000000000000000000":
                logger.error(f"No balance tracker for payment type 0x{payment_type.hex()}")
                return None
            logger.debug(f"Payment type balance tracker: {balance_tracker}")
        except Exception as e:
            logger.warning(f"Could not validate payment type: {e}")

        # Prepare transaction
        tx_data = marketplace.prepare_request_tx(
            from_address=multisig_address,
            request_data=data,
            priority_mech=priority_mech,
            response_timeout=response_timeout,
            max_delivery_rate=max_delivery_rate,
            payment_type=payment_type,
            payment_data=payment_data,
            value=value,
        )

        if not tx_data:
            logger.error("Failed to prepare marketplace request transaction")
            return None

        return self._execute_mech_tx(
            tx_data=tx_data,
            to_address=str(marketplace_address),
            contract_instance=marketplace,
            expected_event="MarketplaceRequest",
        )

    def _execute_mech_tx(
        self,
        tx_data: dict,
        to_address: str,
        contract_instance,
        expected_event: str,
    ) -> Optional[str]:
        """Execute a mech transaction and verify the event."""
        if not self.service:
            logger.error("No active service")
            return None

        multisig_address = self.service.multisig_address
        tx_value = int(tx_data.get("value", 0))

        from iwa.core.models import StoredSafeAccount

        sender_account = self.wallet.account_service.resolve_account(str(multisig_address))
        is_safe = isinstance(sender_account, StoredSafeAccount)

        if is_safe:
            logger.info(f"Sending mech request via Safe {multisig_address} (value: {tx_value} wei)")
            try:
                tx_hash = self.wallet.safe_service.execute_safe_transaction(
                    safe_address_or_tag=str(multisig_address),
                    to=to_address,
                    value=tx_value,
                    chain_name=self.chain_name,
                    data=tx_data["data"],
                )
            except Exception as e:
                logger.error(f"Safe transaction failed: {e}")
                return None
        else:
            logger.info(f"Sending mech request via EOA {multisig_address} (value: {tx_value} wei)")
            tx = {
                "to": to_address,
                "value": tx_value,
                "data": tx_data["data"],
            }
            success, receipt = self.wallet.sign_and_send_transaction(
                transaction=tx,
                signer_address_or_tag=str(multisig_address),
                chain_name=self.chain_name,
            )
            tx_hash = receipt.get("transactionHash").hex() if success else None

        if not tx_hash:
            logger.error("Failed to send mech request transaction")
            return None

        logger.info(f"Mech request transaction sent: {tx_hash}")

        # Verify event emission
        try:
            receipt = self.registry.chain_interface.web3.eth.wait_for_transaction_receipt(tx_hash)
            events = contract_instance.extract_events(receipt)
            event_found = next((e for e in events if e["name"] == expected_event), None)

            if event_found:
                logger.info(f"Event '{expected_event}' verified successfully")
                return tx_hash
            else:
                logger.error(f"Event '{expected_event}' NOT found in transaction logs")
                logger.debug(f"Found events: {[e['name'] for e in events]}")
                return None
        except Exception as e:
            logger.error(f"Error verifying event emission: {e}")
            return None
