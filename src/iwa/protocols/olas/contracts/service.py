"""Service contract interaction."""

import time
from enum import Enum
from typing import Dict, Optional

from iwa.protocols.olas.contracts.base import ContractInstance
from web3 import Web3

from iwa.core.constants import MULTISIG_IMPLEMENTATION_ADDRESS
from iwa.protocols.olas.constants import (
    DEFAULT_DEPLOY_PAYLOAD,
    DEFAULT_FALLBACK_HANDLER,
)


def get_deployment_payload(fallback_handler: Optional[str] = None) -> str:
    """Calculates deployment payload."""
    return (
        DEFAULT_DEPLOY_PAYLOAD.format(
            fallback_handler=(fallback_handler or DEFAULT_FALLBACK_HANDLER)[2:]
        )
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

    def prepare_approve_tx(
        self,
        from_address: str,
        spender: str,
        id: int,
    ) -> Dict:
        """Approve."""
        tx = self.prepare_transaction(
            "approve",
            from_address=from_address,
            spender=spender,
            id=id,
        )
        return tx


class ServiceManagerContract(ContractInstance):
    """Class to interact with the service manager contract."""

    name = "service_manager"

    def prepare_create_tx(
        self,
        from_address: str,
        service_owner: str,
        token_address: str,
        config_hash: str,
        agent_ids: list,
        agent_params: list,
        threshold: int,
    ) -> Dict:
        """Create a new service."""
        tx = self.prepare_transaction(
            "create",
            from_address=from_address,
            serviceOwner=service_owner,
            tokenAddress=token_address,
            configHash=config_hash,
            agentIds=agent_ids,
            agentParams=agent_params,
            threshold=threshold,
        )
        return tx

    def prepare_activate_registration_tx(
        self,
        from_address: str,
        service_id: int,
    ) -> Dict:
        """Activate registration for a service."""
        tx = self.prepare_transaction(
            "activateRegistration",
            from_address=from_address,
            serviceId=service_id,
            value=Web3.to_wei(1, "wei"),
        )
        return tx

    def prepare_register_agents_tx(
        self,
        from_address: str,
        service_id: int,
        agent_instances: list,
        agent_ids: list,
    ) -> Dict:
        """Register agents for a service."""
        tx = self.prepare_transaction(
            "registerAgents",
            from_address=from_address,
            serviceId=service_id,
            agentInstances=agent_instances,
            agentIds=agent_ids,
            value=Web3.to_wei(1, "wei"),
        )
        return tx

    def prepare_deploy_tx(
        self,
        from_address: str,
        service_id: int,
        multisig_implementation_address: str = MULTISIG_IMPLEMENTATION_ADDRESS,
        data: Optional[str] = None,
    ) -> Dict:
        """Deploy a service."""
        tx = self.prepare_transaction(
            "deploy",
            from_address=from_address,
            serviceId=service_id,
            multisigImplementationAddress=multisig_implementation_address,
            data=data or get_deployment_payload(),
        )
        return tx

    def prepare_terminate_tx(
        self,
        from_address: str,
        service_id: int,
    ) -> Dict:
        """Terminate a service."""
        tx = self.prepare_transaction(
            "terminate",
            from_address=from_address,
            serviceId=service_id,
        )
        return tx

    def prepare_unbond_tx(
        self,
        from_address: str,
        service_id: int,
    ) -> Dict:
        """Terminate a service."""
        tx = self.prepare_transaction(
            "unbond",
            from_address=from_address,
            serviceId=service_id,
        )
        return tx
