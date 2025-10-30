import logging
from typing import Dict, Optional

from triton.key_storage import TritonWallet
from triton.models import ServiceConfig
from web3 import Web3

from iwa.core.constants import (
    DEFAULT_TOKEN_ADDRESS,
    SERVICE_MANAGER_ADDRESS_GNOSIS,
    SERVICE_REGISTRY_ADDRESS_GNOSIS,
    SERVICE_REGISTRY_TOKEN_UTILITY_ADDRESS_GNOSIS,
    TRADER_AGENT_ID,
    TRADER_CONFIG_HASH,
)
from iwa.core.contracts.ERC20 import ERC20Contract
from iwa.protocols.olas.contracts.service import (
    ServiceManagerContract,
    ServiceRegistryContract,
    ServiceState,
)
from iwa.protocols.olas.contracts.staking import StakingState

logger = logging.getLogger("service")


class ServiceManager:
    """ServiceManager"""

    def __init__(self, config: ServiceConfig):
        self.config = config
        self.registry = ServiceRegistryContract(SERVICE_REGISTRY_ADDRESS_GNOSIS)
        self.manager = ServiceManagerContract(SERVICE_MANAGER_ADDRESS_GNOSIS)
        self.wallet = TritonWallet()

    def get(self) -> Optional[Dict]:
        """Get service details by ID."""
        return self.registry.get_service(self.config.service_id)

    def create(self, erc20_contract=None, bond_amount: int = 1) -> Optional[int]:
        """Create a new service."""
        create_tx = self.manager.prepare_create_tx(
            from_address=self.wallet.master_account.address,
            service_owner=self.wallet.master_account.address,
            token_address=erc20_contract.address if erc20_contract else DEFAULT_TOKEN_ADDRESS,
            config_hash=bytes.fromhex(TRADER_CONFIG_HASH),
            agent_ids=[25],
            agent_params=[[1, bond_amount]],
            threshold=1,
        )
        success, receipt = self.wallet.master_account.send_transaction(create_tx)

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

        self.config.service_id = service_id

        # Approve the service registry token utility contract to move OLAS
        approve_tx = erc20_contract.prepare_approve_tx(
            from_address=self.wallet.master_account.address,
            spender=SERVICE_REGISTRY_TOKEN_UTILITY_ADDRESS_GNOSIS,
            amount=2 * bond_amount,
        )

        success, receipt = self.wallet.master_account.send_transaction(approve_tx)
        logger.info("Approving OLAS token for staking contract")

        if not success:
            logger.error("Failed to approve staking contract [ERC20]")
            return False

        logger.info("OLAS token approved for staking contract")

        return service_id

    def activate_registration(self) -> bool:
        """Activate registration for the service."""
        # Check that the service is created
        service_state = self.registry.get_service(self.config.service_id)["state"]
        if service_state != ServiceState.PRE_REGISTRATION:
            logger.error("Service is not created, cannot activate registration")
            return False

        activate_tx = self.manager.prepare_activate_registration_tx(
            from_address=self.wallet.master_account.address, service_id=self.config.service_id
        )
        success, receipt = self.wallet.master_account.send_transaction(activate_tx)

        if not success:
            logger.error("Failed to activate registration")
            return False

        logger.info("Registration activation transaction sent successfully")

        events = self.registry.extract_events(receipt)

        if "ActivateRegistration" not in [event["name"] for event in events]:
            logger.error("Activation event not found")
            return False

        return True

    def register_agent(self) -> bool:
        """Register an agent for the service."""
        # Check that the service is in active registration
        service_state = self.registry.get_service(self.config.service_id)["state"]
        if service_state != ServiceState.ACTIVE_REGISTRATION:
            logger.error("Service is not in active registration, cannot register agent")
            return False

        # Create a new account for the service
        agent_account = self.wallet.create_new_account()

        # Fund the agent
        success, receipt = self.wallet.master_account.transfer_native_from_eoa(
            agent_account.address,
            amount=Web3.to_wei(1, "ether"),  # 1 xDAI
        )

        # Register the agent
        register_tx = self.manager.prepare_register_agents_tx(
            from_address=self.wallet.master_account.address,
            service_id=self.config.service_id,
            agent_instances=[agent_account.address],
            agent_ids=[TRADER_AGENT_ID],
        )
        success, receipt = self.wallet.master_account.send_transaction(register_tx)

        if not success:
            logger.error("Failed to register agent")
            return False

        logger.info("Agent registration transaction sent successfully")

        events = self.registry.extract_events(receipt)

        if "RegisterInstance" not in [event["name"] for event in events]:
            logger.error("Agent registration event not found")
            return False

        self.config.agent_address = agent_account.address
        return True

    def deploy(self) -> Optional[str]:
        """Deploy the service."""
        # Check that the service has finished registration
        service_state = self.registry.get_service(self.config.service_id)["state"]
        if service_state != ServiceState.FINISHED_REGISTRATION:
            logger.error("Service registration is not finished, cannot deploy")
            return False

        deploy_tx = self.manager.prepare_deploy_tx(
            from_address=self.wallet.master_account.address,
            service_id=self.config.service_id,
        )

        success, receipt = self.wallet.master_account.send_transaction(deploy_tx)

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

        self.config.multisig_address = multisig_address
        logger.info("Service deployed successfully")
        return multisig_address

    def terminate(self) -> bool:
        """Terminate the service."""
        # Check that the service is deployed
        service_state = self.registry.get_service(self.config.service_id)["state"]
        if service_state != ServiceState.DEPLOYED:
            logger.error("Service is not deployed, cannot terminate")
            return False

        # Check that the service is not staked
        if self.config.staking_contract_address:
            logger.error("Service is staked, cannot terminate")
            return False

        terminate_tx = self.manager.prepare_terminate_tx(
            from_address=self.wallet.master_account.address,
            service_id=self.config.service_id,
        )

        success, receipt = self.wallet.master_account.send_transaction(terminate_tx)

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
        service_state = self.registry.get_service(self.config.service_id)["state"]
        if service_state != ServiceState.TERMINATED_BONDED:
            logger.error("Service is not terminated, cannot unbond")
            return False

        unbond_tx = self.manager.prepare_unbond_tx(
            from_address=self.wallet.master_account.address,
            service_id=self.config.service_id,
        )

        success, receipt = self.wallet.master_account.send_transaction(unbond_tx)

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
        service_state = self.registry.get_service(self.config.service_id)["state"]
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
            id=self.config.service_id,
        )

        success, receipt = self.wallet.master_account.send_transaction(approve_tx)
        logger.info("Approving service token for staking contract")

        if not success:
            logger.error("Failed to approve staking contract [Service Registry]")
            return False

        logger.info("Service token approved for staking contract")

        # Stake the service
        stake_tx = staking_contract.prepare_stake_tx(
            from_address=self.wallet.master_account.address,
            service_id=self.config.service_id,
        )

        success, receipt = self.wallet.master_account.send_transaction(stake_tx)

        if not success:
            logger.error("Failed to stake service")
            return False

        logger.info("Service stake transaction sent successfully")

        events = staking_contract.extract_events(receipt)

        if "ServiceStaked" not in [event["name"] for event in events]:
            logger.error("Stake service event not found")
            return False

        if staking_contract.get_staking_state(self.config.service_id) != StakingState.STAKED:
            logger.error("Service is not staked after transaction")
            return False

        self.config.staking_contract_address = staking_contract.address
        logger.info("Service staked successfully")
        return True

    def unstake(self, staking_contract) -> bool:
        """Unstake the service from the staking contract."""
        # Check that the service is staked
        staking_state = staking_contract.get_staking_state(self.config.service_id)
        if staking_state != StakingState.STAKED:
            logger.error("Service is not staked, cannot unstake")
            return False

        # Check that enough time has passed since staking
        # TODO

        # Unstake the service
        unstake_tx = staking_contract.prepare_unstake_tx(
            from_address=self.wallet.master_account.address,
            service_id=self.config.service_id,
        )

        success, receipt = self.wallet.master_account.send_transaction(unstake_tx)

        if not success:
            logger.error("Failed to unstake service")
            return False

        logger.info("Service unstake transaction sent successfully")

        events = staking_contract.extract_events(receipt)

        if "ServiceUnstaked" not in [event["name"] for event in events]:
            logger.error("Unstake service event not found")
            return False

        self.config.staking_contract_address = None

        logger.info("Service unstaked successfully")
        return True
