"""Lifecycle manager mixin for OLAS service lifecycle operations.

OLAS Service Lifecycle & Token Flow
====================================

This module handles the first 4 steps of the service lifecycle (staking is in staking.py).
Each step involves specific token movements as detailed below.

STEP 1: CREATE SERVICE
    - What happens:
        * Service is registered on-chain with metadata (config hash, agent IDs)
        * Service ownership NFT (ERC-721) is minted to service owner
        * Bond parameters are recorded but NO tokens move yet
    - Token Movement: None
    - Approval: Service Owner → Token Utility (for 2 × bond_amount OLAS)
    - Next State: PRE_REGISTRATION

STEP 2: ACTIVATE REGISTRATION
    - What happens:
        * Service Owner signals readiness to accept agent registrations
        * Token Utility pulls min_staking_deposit OLAS from owner via transferFrom()
    - Token Movement:
        * 5,000 OLAS: Service Owner → Token Utility (for 10k contract)
    - Native value sent: 1 wei (not 5k OLAS!)
        * This is MIN_AGENT_BOND, a placeholder for native-bonded services
        * For OLAS-bonded services, tokens move via Token Utility, not via msg.value
    - Next State: ACTIVE_REGISTRATION

STEP 3: REGISTER AGENT
    - What happens:
        * Agent instance address is registered to the service
        * Token Utility pulls agent_bond OLAS from owner via transferFrom()
    - Token Movement:
        * 5,000 OLAS: Service Owner → Token Utility (for 10k contract)
    - Native value sent: 1 wei per agent
        * Same logic as activation - tokens move via Token Utility
    - Next State: FINISHED_REGISTRATION

STEP 4: DEPLOY
    - What happens:
        * Safe multisig is created with agent instances as owners
        * Service transitions to operational state
    - Token Movement: None
    - Next State: DEPLOYED

After DEPLOYED, see staking.py for STEP 5: STAKE

Token Utility Contract:
    The Token Utility (0xa45E64d13A30a51b91ae0eb182e88a40e9b18eD8 on Gnosis) is the
    intermediary that holds OLAS deposits. When you call activateRegistration() or
    registerAgents() on the Service Manager, it internally calls Token Utility's
    transferFrom() to move OLAS from the service owner.

    This is why:
    1. We approve Token Utility BEFORE activation/registration
    2. We send 1 wei native value (not the OLAS amount) in TX
    3. The actual OLAS moves via transferFrom(), not msg.value
"""

from typing import List, Optional, Union

from loguru import logger
from web3 import Web3
from web3.types import Wei

from iwa.core.chain import ChainInterfaces
from iwa.core.constants import NATIVE_CURRENCY_ADDRESS, ZERO_ADDRESS
from iwa.core.contracts.cache import ContractCache
from iwa.core.types import EthereumAddress
from iwa.core.utils import get_tx_hash
from iwa.plugins.olas.constants import (
    OLAS_CONTRACTS,
    TRADER_CONFIG_HASH,
    AgentType,
)
from iwa.plugins.olas.contracts.service import ServiceState
from iwa.plugins.olas.models import Service


class LifecycleManagerMixin:
    """Mixin for OLAS service lifecycle operations.

    Handles the CREATE → ACTIVATE → REGISTER → DEPLOY flow for OLAS services.
    Each method transitions the service to the next state.

    Token Movement Summary:
        ┌───────────────┬────────────────────────────────────────────────────┐
        │ Step          │ OLAS Movement                                      │
        ├───────────────┼────────────────────────────────────────────────────┤
        │ create()      │ None (just approval to Token Utility)              │
        │ activate()    │ 5k OLAS → Token Utility (via transferFrom)         │
        │ register()    │ 5k OLAS → Token Utility (via transferFrom)         │
        │ deploy()      │ None (just creates Safe multisig)                  │
        └───────────────┴────────────────────────────────────────────────────┘

    Usage:
        manager = ServiceManager(wallet)
        service_id = manager.create(chain_name="gnosis", token_address_or_tag="OLAS")
        manager.spin_up(bond_amount_wei=5000e18, staking_contract=staking)
    """

    def _get_label(self, address: str) -> str:
        """Resolve address to a human-readable label."""
        if not address:
            return "None"

        # Try account service tags first (wallets, safes)
        tag = self.wallet.account_service.get_tag_by_address(address)
        if tag:
            return tag

        # Try token names
        chain_interface = ChainInterfaces().get(self.chain_name)
        token_name = chain_interface.chain.get_token_name(address)
        if token_name:
            return token_name

        return address

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
            f"Preparing create tx: owner={self._get_label(service_owner_account.address)}, "
            f"token={self._get_label(token_address)}, agent_ids={agent_id_values}, agent_params={agent_params}"
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
            service_owner_eoa_address=service_owner_account.address,
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
        service_owner_eoa_address: str,
        token_address: Optional[str],
    ) -> None:
        """Create and save the new Service model."""
        new_service = Service(
            service_name=service_name or f"service_{service_id}",
            chain_name=chain_name,
            service_id=service_id,
            agent_ids=agent_id_values,
            service_owner_eoa_address=service_owner_eoa_address,
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
        """Approve Token Utility to spend OLAS tokens (called during create).

        Why 2× bond amount?
            - Activation requires min_staking_deposit (= bond_amount)
            - Registration requires agent_bond (= bond_amount)
            - Total = 2 × bond_amount

        Token Movement: None (this is just an approval, not a transfer)

        Args:
            token_address: OLAS token address (or None for native).
            chain_name: Chain to operate on.
            service_owner_account: Account that owns the OLAS tokens.
            bond_amount_wei: Bond amount per agent in wei.

        """
        if not token_address:
            return

        # Approve the service registry token utility contract
        protocol_contracts = OLAS_CONTRACTS.get(chain_name.lower(), {})
        utility_address = protocol_contracts.get("OLAS_SERVICE_REGISTRY_TOKEN_UTILITY")

        if not utility_address:
            logger.error(f"OLAS Service Registry Token Utility not found for chain: {chain_name}")
            return

        # Approve the token utility to move tokens (2 * bond amount: activation + registration)
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
        """Activate registration for the service (Step 2 of lifecycle).

        What This Does:
            Transitions service from PRE_REGISTRATION → ACTIVE_REGISTRATION.
            Signals that the service owner is ready to accept agent registrations.

        Token Movement:
            5,000 OLAS (for 10k contract): Service Owner → Token Utility
            - Moved internally by Token Utility via transferFrom()
            - NOT sent as msg.value (that's just 1 wei)

        Native Value Sent:
            1 wei (MIN_AGENT_BOND placeholder, not the actual deposit)

        Prerequisites:
            - Service must be in PRE_REGISTRATION state
            - Token Utility must be approved to spend owner's OLAS

        Returns:
            True if activation succeeded, False otherwise.

        """
        service_id = self.service.service_id
        logger.info(f"[ACTIVATE] Starting activation for service {service_id}")

        if not self._validate_pre_registration_state(service_id):
            return False

        token_address = self._get_service_token(service_id)
        logger.debug(f"[ACTIVATE] Token address: {self._get_label(token_address)}")

        service_info = self.registry.get_service(service_id)
        security_deposit = service_info["security_deposit"]
        logger.info(f"[ACTIVATE] Security deposit required: {security_deposit} wei")

        if not self._ensure_token_approval_for_activation(token_address, security_deposit):
            logger.error("[ACTIVATE] Token approval failed")
            return False

        logger.info("[ACTIVATE] Sending activation transaction...")
        return self._send_activation_transaction(service_id, security_deposit)

    def _validate_pre_registration_state(self, service_id: int) -> bool:
        """Check if service is in PRE_REGISTRATION state."""
        service_info = self.registry.get_service(service_id)
        service_state = service_info["state"]
        logger.debug(f"[ACTIVATE] Current state: {service_state.name}")
        if service_state != ServiceState.PRE_REGISTRATION:
            logger.error(
                f"[ACTIVATE] Service is in {service_state.name}, expected PRE_REGISTRATION"
            )
            return False
        logger.debug("[ACTIVATE] State validated: PRE_REGISTRATION")
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
        """Ensure token approval for activation if not native token.

        For token-bonded services (e.g., OLAS), we need to approve the
        ServiceRegistryTokenUtility contract to spend the security deposit
        (agent bond) on our behalf.

        IMPORTANT: We query the exact bond amount from the Token Utility contract
        rather than approving a fixed amount, to match the official OLAS middleware.
        """
        is_native = str(token_address).lower() == str(ZERO_ADDRESS).lower()
        if is_native:
            return True

        try:
            # Get the exact agent bond from Token Utility contract
            bond_amount = self._get_agent_bond_from_token_utility()
            if bond_amount is None or bond_amount == 0:
                logger.warning(
                    "[ACTIVATE] Could not get agent bond from Token Utility, using security_deposit"
                )
                bond_amount = security_deposit

            logger.info(f"[ACTIVATE] Agent bond from Token Utility: {bond_amount} wei")

            # Check owner balance
            balance = self.wallet.balance_service.get_erc20_balance_wei(
                account_address_or_tag=self.service.service_owner_address,
                token_address_or_name=token_address,
                chain_name=self.chain_name,
            )

            if balance < bond_amount:
                logger.error(f"[ACTIVATE] FAIL: Owner balance {balance} < required {bond_amount}")
                return False

            protocol_contracts = OLAS_CONTRACTS.get(self.chain_name.lower(), {})
            utility_address = protocol_contracts.get("OLAS_SERVICE_REGISTRY_TOKEN_UTILITY")

            if utility_address:
                # Approve exactly the bond amount (not 1000 OLAS fixed!)
                # This matches the official OLAS middleware behavior
                required_approval = bond_amount

                # Check current allowance
                allowance = self.wallet.transfer_service.get_erc20_allowance(
                    owner_address_or_tag=self.service.service_owner_address,
                    spender_address=utility_address,
                    token_address_or_name=token_address,
                    chain_name=self.chain_name,
                )

                if allowance < required_approval:
                    logger.info(
                        f"[ACTIVATE] Allowance ({allowance}) < required ({required_approval}). "
                        f"Approving Token Utility {utility_address}"
                    )
                    success_approve = self.wallet.transfer_service.approve_erc20(
                        owner_address_or_tag=self.service.service_owner_address,
                        spender_address_or_tag=utility_address,
                        token_address_or_name=token_address,
                        amount_wei=required_approval,
                        chain_name=self.chain_name,
                    )
                    if not success_approve:
                        logger.error("[ACTIVATE] Token approval failed")
                        return False
                    logger.info(f"[ACTIVATE] Approved {required_approval} wei to Token Utility")
                else:
                    logger.debug(
                        f"[ACTIVATE] Sufficient allowance ({allowance} >= {required_approval})"
                    )
            return True
        except Exception as e:
            logger.error(f"[ACTIVATE] Failed to check/approve tokens: {e}")
            return False

    def _get_agent_bond_from_token_utility(self) -> Optional[int]:
        """Get the agent bond from the ServiceRegistryTokenUtility contract.

        This queries the on-chain Token Utility contract to get the exact bond
        amount required for the service, matching the official OLAS middleware.

        Returns:
            The agent bond in wei, or None if the query fails.

        """
        from iwa.plugins.olas.contracts.service import ServiceRegistryTokenUtilityContract

        try:
            protocol_contracts = OLAS_CONTRACTS.get(self.chain_name.lower(), {})
            utility_address = protocol_contracts.get("OLAS_SERVICE_REGISTRY_TOKEN_UTILITY")

            if not utility_address:
                logger.warning("[ACTIVATE] Token Utility address not found for chain")
                return None

            # Get agent ID (first agent in the service)
            service_info = self.registry.get_service(self.service.service_id)
            agent_ids = service_info.get("agent_ids", [])
            if not agent_ids:
                logger.warning("[ACTIVATE] No agent IDs found for service")
                return None
            agent_id = agent_ids[0]

            # Use the ServiceRegistryTokenUtilityContract with official ABI
            token_utility = ContractCache().get_contract(
                ServiceRegistryTokenUtilityContract,
                address=str(utility_address),
                chain_name=self.chain_name,
            )

            bond = token_utility.get_agent_bond(self.service.service_id, agent_id)

            logger.debug(
                f"[ACTIVATE] Token Utility getAgentBond({self.service.service_id}, {agent_id}) = {bond}"
            )
            return bond

        except Exception as e:
            logger.warning(f"[ACTIVATE] Failed to get agent bond from Token Utility: {e}")
            return None

    def _send_activation_transaction(self, service_id: int, security_deposit: Wei) -> bool:
        """Send the activation transaction.

        For token-bonded services (e.g., OLAS), we pass MIN_AGENT_BOND (1 wei) as native value.
        The Token Utility handles OLAS transfers internally based on the service configuration.
        For native currency services, we pass the full security_deposit.
        """
        # Determine if this is a token-bonded service
        token_address = self._get_service_token(service_id)
        is_native = str(token_address).lower() == str(ZERO_ADDRESS).lower()

        # For token services, use MIN_AGENT_BOND (1 wei) as native value
        # The OLAS token approval was done in _ensure_token_approval_for_activation
        activation_value = security_deposit if is_native else 1
        logger.info(
            f"[ACTIVATE] Token={self._get_label(token_address)}, is_native={is_native}, "
            f"activation_value={activation_value} wei"
        )

        # Use service owner which holds the NFT (not necessarily master)
        owner_address = self.service.service_owner_address or self.wallet.master_account.address

        logger.debug(
            f"[ACTIVATE] Preparing tx from {self._get_label(owner_address)}: service_id={service_id}, value={activation_value}"
        )
        activate_tx = self.manager.prepare_activate_registration_tx(
            from_address=owner_address,
            service_id=service_id,
            value=activation_value,
        )
        logger.debug(f"[ACTIVATE] TX prepared: to={activate_tx.get('to')}")

        success, receipt = self.wallet.sign_and_send_transaction(
            transaction=activate_tx,
            signer_address_or_tag=owner_address,
            chain_name=self.chain_name,
        )

        if not success:
            logger.error("[ACTIVATE] Transaction failed")
            return False

        tx_hash = get_tx_hash(receipt)
        logger.info(f"[ACTIVATE] TX sent: {tx_hash}")

        events = self.registry.extract_events(receipt)
        event_names = [e["name"] for e in events]
        logger.debug(f"[ACTIVATE] Events: {event_names}")

        if "ActivateRegistration" not in event_names:
            logger.error("[ACTIVATE] ActivateRegistration event not found")
            return False

        logger.info("[ACTIVATE] Success - service is now ACTIVE_REGISTRATION")
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
        logger.info(f"[REGISTER] Starting agent registration for service {self.service.service_id}")
        logger.debug(f"[REGISTER] agent_address={agent_address}, bond={bond_amount_wei}")

        if not self._validate_active_registration_state():
            return False

        agent_account_address = self._get_or_create_agent_account(agent_address)
        if not agent_account_address:
            logger.error("[REGISTER] Failed to get/create agent account")
            return False
        logger.info(f"[REGISTER] Agent address: {self._get_label(agent_account_address)}")

        if not self._ensure_agent_token_approval(agent_account_address, bond_amount_wei):
            logger.error("[REGISTER] Token approval failed")
            return False

        logger.info("[REGISTER] Sending register agent transaction...")
        return self._send_register_agent_transaction(agent_account_address)

    def _validate_active_registration_state(self) -> bool:
        """Check that the service is in active registration."""
        service_state = self.registry.get_service(self.service.service_id)["state"]
        logger.debug(f"[REGISTER] Current state: {service_state.name}")
        if service_state != ServiceState.ACTIVE_REGISTRATION:
            logger.error(
                f"[REGISTER] Service is in {service_state.name}, expected ACTIVE_REGISTRATION"
            )
            return False
        logger.debug("[REGISTER] State validated: ACTIVE_REGISTRATION")
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
            agent_account = self.wallet.key_storage.generate_new_account(agent_tag)
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
        """Ensure token approval for agent registration if needed.

        For token-bonded services, the service owner must approve the Token Utility
        contract to transfer the agent bond. We query the exact bond from the
        Token Utility contract to match the official OLAS middleware.
        """
        service_id = self.service.service_id
        token_address = self._get_service_token(service_id)
        is_native = str(token_address) == str(ZERO_ADDRESS)

        if is_native:
            return True

        # Get exact bond from Token Utility if not explicitly provided
        if not bond_amount_wei:
            bond_amount_wei = self._get_agent_bond_from_token_utility()
            if not bond_amount_wei:
                logger.warning(
                    "[REGISTER] Could not get bond from Token Utility, skipping approval"
                )
                return True

        logger.info(
            f"[REGISTER] Service Owner approving Token Utility for bond: {bond_amount_wei} wei"
        )

        utility_address = str(
            OLAS_CONTRACTS[self.chain_name]["OLAS_SERVICE_REGISTRY_TOKEN_UTILITY"]
        )

        # Check current allowance first
        allowance = self.wallet.transfer_service.get_erc20_allowance(
            owner_address_or_tag=self.service.service_owner_address,
            spender_address=utility_address,
            token_address_or_name=token_address,
            chain_name=self.chain_name,
        )

        if allowance >= bond_amount_wei:
            logger.debug(f"[REGISTER] Sufficient allowance ({allowance} >= {bond_amount_wei})")
            return True

        # Use service owner which holds the OLAS tokens (not necessarily master)
        approve_success = self.wallet.transfer_service.approve_erc20(
            token_address_or_name=token_address,
            spender_address_or_tag=utility_address,
            amount_wei=bond_amount_wei,
            owner_address_or_tag=self.service.service_owner_address,
            chain_name=self.chain_name,
        )
        if not approve_success:
            logger.error("[REGISTER] Failed to approve token for agent registration")
            return False

        logger.info(f"[REGISTER] Approved {bond_amount_wei} wei to Token Utility")
        return True

    def _send_register_agent_transaction(self, agent_account_address: str) -> bool:
        """Send the register agent transaction.

        For token-bonded services (e.g., OLAS), we pass MIN_AGENT_BOND (1 wei) as native value.
        The Token Utility handles OLAS transfers internally via transferFrom.
        For native currency services, we pass the full security_deposit * num_agents.
        """
        service_id = self.service.service_id
        token_address = self._get_service_token(service_id)
        is_native = str(token_address).lower() == str(ZERO_ADDRESS).lower()

        # For token services, use MIN_AGENT_BOND (1 wei) per agent
        # For native services, use security_deposit * num_agents
        if is_native:
            service_info = self.registry.get_service(service_id)
            security_deposit = service_info["security_deposit"]
            total_value = security_deposit * len(self.service.agent_ids)
        else:
            # MIN_AGENT_BOND = 1 wei per agent
            total_value = 1 * len(self.service.agent_ids)

        logger.info(
            f"[REGISTER] Token={self._get_label(token_address)}, is_native={is_native}, "
            f"total_value={total_value} wei"
        )

        # Use service owner which holds the NFT (not necessarily master)
        owner_address = self.service.service_owner_address or self.wallet.master_account.address

        logger.debug(
            f"[REGISTER] Preparing tx from {self._get_label(owner_address)}: agent={self._get_label(agent_account_address)}, "
            f"agent_ids={self.service.agent_ids}, value={total_value}"
        )

        register_tx = self.manager.prepare_register_agents_tx(
            from_address=owner_address,
            service_id=service_id,
            agent_instances=[agent_account_address],
            agent_ids=self.service.agent_ids,
            value=total_value,
        )
        logger.debug(f"[REGISTER] TX prepared: to={register_tx.get('to')}")

        success, receipt = self.wallet.sign_and_send_transaction(
            transaction=register_tx,
            signer_address_or_tag=owner_address,
            chain_name=self.chain_name,
            tags=["olas_register_agent"],
        )

        if not success:
            logger.error("[REGISTER] Transaction failed")
            return False

        tx_hash = get_tx_hash(receipt)
        logger.info(f"[REGISTER] TX sent: {tx_hash}")

        events = self.registry.extract_events(receipt)
        event_names = [e["name"] for e in events]
        logger.debug(f"[REGISTER] Events: {event_names}")

        if "RegisterInstance" not in event_names:
            logger.error("[REGISTER] RegisterInstance event not found")
            return False

        self.service.agent_address = EthereumAddress(agent_account_address)
        self._update_and_save_service_state()
        logger.info("[REGISTER] Success - service is now FINISHED_REGISTRATION")
        return True

    def deploy(self, fund_multisig: bool = False) -> Optional[str]:  # noqa: C901
        """Deploy the service."""
        logger.info(f"[DEPLOY] Starting deployment for service {self.service.service_id}")

        service_state = self.registry.get_service(self.service.service_id)["state"]
        logger.debug(f"[DEPLOY] Current state: {service_state.name}")

        if service_state != ServiceState.FINISHED_REGISTRATION:
            logger.error(
                f"[DEPLOY] Service is in {service_state.name}, expected FINISHED_REGISTRATION"
            )
            return False

        logger.debug(
            f"[DEPLOY] Preparing deploy tx for owner {self._get_label(self.service.service_owner_address)}"
        )
        deploy_tx = self.manager.prepare_deploy_tx(
            from_address=self.service.service_owner_address,
            service_id=self.service.service_id,
        )

        if not deploy_tx:
            logger.error("[DEPLOY] Failed to prepare deploy transaction")
            return None

        logger.debug(f"[DEPLOY] TX prepared: to={deploy_tx.get('to')}")

        success, receipt = self.wallet.sign_and_send_transaction(
            transaction=deploy_tx,
            signer_address_or_tag=self.service.service_owner_address,
            chain_name=self.chain_name,
            tags=["olas_deploy_service"],
        )

        if not success:
            logger.error("[DEPLOY] Transaction failed")
            return None

        tx_hash = get_tx_hash(receipt)
        logger.info(f"[DEPLOY] TX sent: {tx_hash}")

        events = self.registry.extract_events(receipt)
        event_names = [e["name"] for e in events]
        logger.debug(f"[DEPLOY] Events: {event_names}")

        if "DeployService" not in event_names:
            logger.error("[DEPLOY] DeployService event not found")
            return None

        multisig_address = None
        for event in events:
            if event["name"] == "CreateMultisigWithAgents":
                multisig_address = event["args"]["multisig"]
                break

        if multisig_address is None:
            logger.error("[DEPLOY] Multisig address not found in events")
            return None

        logger.info(f"[DEPLOY] Multisig created: {multisig_address}")
        self.service.multisig_address = EthereumAddress(multisig_address)
        self._update_and_save_service_state()

        # Register multisig in wallet KeyStorage
        try:
            from iwa.core.models import StoredSafeAccount

            _, agent_instances = self.registry.call("getAgentInstances", self.service.service_id)
            service_info = self.registry.get_service(self.service.service_id)
            threshold = service_info["threshold"]
            # Store the multisig in the wallet with tag
            multisig_tag = f"{self.service.service_name}_multisig"

            # ARCHIVING LOGIC: If tag is already taken by a different address, rename the old one
            existing = self.wallet.key_storage.find_stored_account(multisig_tag)
            if existing and existing.address != multisig_address:
                archive_tag = f"{multisig_tag}_old_{existing.address[:6]}"
                logger.info(f"[DEPLOY] Archiving old multisig: {multisig_tag} -> {archive_tag}")
                try:
                    self.wallet.key_storage.rename_account(existing.address, archive_tag)
                except Exception as ex:
                    logger.warning(f"[DEPLOY] Failed to rename old multisig (collision?): {ex}")

            safe_account = StoredSafeAccount(
                tag=multisig_tag,
                address=multisig_address,
                chains=[self.chain_name],
                threshold=threshold,
                signers=agent_instances,
            )
            self.wallet.key_storage.register_account(safe_account)
            logger.debug("[DEPLOY] Registered multisig in wallet")
        except Exception as e:
            logger.warning(f"[DEPLOY] Failed to register multisig in wallet: {e}")

        # Fund the multisig with 1 xDAI from master if requested (for staking)
        if fund_multisig:
            try:
                funding_amount = Web3.to_wei(1, "ether")
                logger.info(f"[DEPLOY] Funding multisig {multisig_address} with 1 xDAI from master")
                tx_hash = self.wallet.send(
                    from_address_or_tag=self.wallet.master_account.address,
                    to_address_or_tag=multisig_address,
                    token_address_or_name="native",
                    amount_wei=funding_amount,
                    chain_name=self.chain_name,
                )
                if tx_hash:
                    logger.info(f"[DEPLOY] Funded multisig: {tx_hash}")
                else:
                    logger.error("[DEPLOY] Failed to fund multisig")
            except Exception as e:
                logger.error(f"[DEPLOY] Failed to fund multisig: {e}")

        logger.info("[DEPLOY] Success - service is now DEPLOYED")
        return multisig_address

    def terminate(self) -> bool:
        """Terminate the service."""
        # Check that the service is deployed
        service_state = self.registry.get_service(self.service.service_id)["state"]
        if service_state not in [
            ServiceState.DEPLOYED,
            ServiceState.ACTIVE_REGISTRATION,
            ServiceState.FINISHED_REGISTRATION,
        ]:
            logger.error(
                f"Service is in {service_state.name}, cannot terminate (must be active or deployed)"
            )
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
                logger.error("[SPIN-UP] No active service and no service_id provided")
                return False
            service_id = self.service.service_id

        logger.info("=" * 50)
        logger.info(f"[SPIN-UP] Starting spin_up for service {service_id}")
        logger.info(f"[SPIN-UP] Parameters: agent_address={agent_address}, bond={bond_amount_wei}")
        logger.info(
            f"[SPIN-UP] Staking contract: {staking_contract.address if staking_contract else 'None'}"
        )
        logger.info("=" * 50)

        current_state = self._get_service_state_safe(service_id)
        if not current_state:
            return False

        logger.info(f"[SPIN-UP] Initial state: {current_state.name}")

        step = 1
        while current_state != ServiceState.DEPLOYED:
            previous_state = current_state
            logger.info(f"[SPIN-UP] Step {step}: Processing {current_state.name}...")

            should_fund = staking_contract is not None
            if not self._process_spin_up_state(
                current_state, agent_address, bond_amount_wei, fund_multisig=should_fund
            ):
                logger.error(f"[SPIN-UP] Step {step} FAILED at state {current_state.name}")
                return False

            # Refresh state
            current_state = self._get_service_state_safe(service_id)
            if not current_state:
                return False

            if current_state == previous_state:
                logger.error(f"[SPIN-UP] State stuck at {current_state.name} after action")
                return False

            logger.info(f"[SPIN-UP] Step {step} OK: {previous_state.name} -> {current_state.name}")
            step += 1

        logger.info(f"[SPIN-UP] Service {service_id} is now DEPLOYED")

        # Stake if requested
        if staking_contract:
            logger.info(f"[SPIN-UP] Step {step}: Staking service...")
            if not self.stake(staking_contract):
                logger.error("[SPIN-UP] Staking FAILED")
                return False
            logger.info(f"[SPIN-UP] Step {step} OK: Service staked successfully")

        logger.info("=" * 50)
        logger.info(f"[SPIN-UP] COMPLETE - Service {service_id} is deployed and ready")
        logger.info("=" * 50)
        return True

    def _process_spin_up_state(
        self,
        current_state: ServiceState,
        agent_address: Optional[str],
        bond_amount_wei: Optional[Wei],
        fund_multisig: bool = False,
    ) -> bool:
        """Process a single state transition for spin up."""
        if current_state == ServiceState.PRE_REGISTRATION:
            logger.info("[SPIN-UP] Action: activate_registration()")
            if not self.activate_registration():
                return False
        elif current_state == ServiceState.ACTIVE_REGISTRATION:
            logger.info("[SPIN-UP] Action: register_agent()")
            if not self.register_agent(
                agent_address=agent_address, bond_amount_wei=bond_amount_wei
            ):
                return False
        elif current_state == ServiceState.FINISHED_REGISTRATION:
            logger.info(f"[SPIN-UP] Action: deploy(fund_multisig={fund_multisig})")
            if not self.deploy(fund_multisig=fund_multisig):
                return False
        else:
            logger.error(f"[SPIN-UP] Invalid state: {current_state.name}")
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
        # Allow termination from any active state > PRE_REGISTRATION
        if current_state in [
            ServiceState.DEPLOYED,
            ServiceState.ACTIVE_REGISTRATION,
            ServiceState.FINISHED_REGISTRATION,
        ]:
            logger.info(f"Terminating service from state {current_state.name}...")
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
                f"State {current_state.name} is not a valid start for wind_down (expected active state or TERMINATED_BONDED)"
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
