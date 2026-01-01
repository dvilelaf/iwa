"""Service contract interaction."""

import time
from enum import Enum
from typing import Dict, Optional

from iwa.core.contracts.contract import ContractInstance
from iwa.core.types import EthereumAddress
from iwa.plugins.olas.constants import (
    DEFAULT_DEPLOY_PAYLOAD,
)
from iwa.plugins.olas.contracts.base import OLAS_ABI_PATH


def get_deployment_payload(fallback_handler: str) -> str:
    """Calculates deployment payload."""
    return (
        DEFAULT_DEPLOY_PAYLOAD.format(fallback_handler=fallback_handler[2:])
        + int(time.time()).to_bytes(32, "big").hex()
    )


class ServiceState(Enum):
    """Enumeration of possible service states."""

    NON_EXISTENT = 0
    PRE_REGISTRATION = 1
    ACTIVE_REGISTRATION = 2
    FINISHED_REGISTRATION = 3
    DEPLOYED = 4
    TERMINATED_BONDED = 5


class ServiceRegistryContract(ContractInstance):
    """Class to interact with the service registry contract."""

    name = "service_registry"
    abi_path = OLAS_ABI_PATH / "service_registry.json"

    def get_service(self, service_id: int) -> Dict:
        """Get the IDs of all registered services."""
        (
            security_deposit,
            multisig,
            config_hash,
            threshold,
            max_num_agent_instances,
            num_agent_instances,
            state,
            agent_ids,
        ) = self.call("getService", service_id)
        return {
            "security_deposit": security_deposit,
            "multisig": multisig,
            "config_hash": config_hash.hex(),
            "threshold": threshold,
            "max_num_agent_instances": max_num_agent_instances,
            "num_agent_instances": num_agent_instances,
            "state": ServiceState(state),
            "agent_ids": agent_ids,
        }

    def get_token(self, service_id: int) -> str:
        """Get the token address for a service."""
        return self.call("token", service_id)

    def get_agent_params(self, service_id: int, agent_id: int) -> Dict:
        """Get agent params (slots, bond) for a service."""
        (slots, bond) = self.call("getAgentParams", service_id, agent_id)
        return {"slots": slots, "bond": bond}

    def prepare_approve_tx(
        self,
        from_address: EthereumAddress,
        spender: EthereumAddress,
        id_: int,
    ) -> Optional[Dict]:
        """Approve."""
        return self.prepare_transaction(
            method_name="approve",
            method_kwargs={"spender": spender, "id": id_},
            tx_params={"from": from_address},
        )


class ServiceManagerContract(ContractInstance):
    """Class to interact with the service manager contract."""

    name = "service_manager"
    abi_path = OLAS_ABI_PATH / "service_manager.json"

    def prepare_create_tx(
        self,
        from_address: EthereumAddress,
        service_owner: EthereumAddress,
        token_address: EthereumAddress,
        config_hash: str,
        agent_ids: list,
        agent_params: list,
        threshold: int,
    ) -> Optional[Dict]:
        """Create a new service."""
        return self.prepare_transaction(
            method_name="create",
            method_kwargs={
                "serviceOwner": service_owner,
                "tokenAddress": token_address,
                "configHash": config_hash,
                "agentIds": agent_ids,
                "agentParams": agent_params,
                "threshold": threshold,
            },
            tx_params={"from": from_address},
        )

    def prepare_activate_registration_tx(
        self,
        from_address: EthereumAddress,
        service_id: int,
        value: int = 1,
    ) -> Optional[Dict]:
        """Activate registration for a service."""
        tx = self.prepare_transaction(
            method_name="activateRegistration",
            method_kwargs={
                "serviceId": service_id,
            },
            tx_params={"from": from_address, "value": value},
        )
        return tx

    def prepare_register_agents_tx(
        self,
        from_address: EthereumAddress,
        service_id: int,
        agent_instances: list,
        agent_ids: list,
        value: int = 1,
    ) -> Optional[Dict]:
        """Register agents for a service."""
        tx = self.prepare_transaction(
            method_name="registerAgents",
            method_kwargs={
                "serviceId": service_id,
                "agentInstances": agent_instances,
                "agentIds": agent_ids,
            },
            tx_params={"from": from_address, "value": value},
        )
        return tx

    def prepare_deploy_tx(
        self,
        from_address: EthereumAddress,
        service_id: int,
        multisig_implementation_address: Optional[str] = None,
        fallback_handler: Optional[str] = None,
        data: Optional[str] = None,
    ) -> Optional[Dict]:
        """Deploy a service."""
        # Get addresses from chain if not provided
        if not multisig_implementation_address:
            multisig_implementation_address = self.chain_interface.get_contract_address(
                "GNOSIS_SAFE_MULTISIG_IMPLEMENTATION"
            )
        if not fallback_handler:
            fallback_handler = self.chain_interface.get_contract_address(
                "GNOSIS_SAFE_FALLBACK_HANDLER"
            )

        if not multisig_implementation_address or not fallback_handler:
            raise ValueError(
                "Multisig implementation or fallback handler address not found for chain"
            )

        tx = self.prepare_transaction(
            method_name="deploy",
            method_kwargs={
                "serviceId": service_id,
                "multisigImplementationAddress": multisig_implementation_address,
                "data": data or get_deployment_payload(fallback_handler),
            },
            tx_params={"from": from_address},
        )
        return tx

    def prepare_terminate_tx(
        self,
        from_address: EthereumAddress,
        service_id: int,
    ) -> Optional[Dict]:
        """Terminate a service."""
        tx = self.prepare_transaction(
            method_name="terminate",
            method_kwargs={
                "serviceId": service_id,
            },
            tx_params={"from": from_address},
        )
        return tx

    def prepare_unbond_tx(
        self,
        from_address: EthereumAddress,
        service_id: int,
    ) -> Optional[Dict]:
        """Terminate a service."""
        tx = self.prepare_transaction(
            method_name="unbond",
            method_kwargs={
                "serviceId": service_id,
            },
            tx_params={"from": from_address},
        )
        return tx
