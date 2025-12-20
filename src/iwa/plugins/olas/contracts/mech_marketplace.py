"""Mech Marketplace contract interaction."""

from typing import Dict, Optional
from iwa.core.contracts.contract import ContractInstance
from iwa.plugins.olas.contracts.base import OLAS_ABI_PATH


class MechMarketplaceContract(ContractInstance):
    """Class to interact with the Mech Marketplace contract."""

    name = "mech_marketplace"
    abi_path = OLAS_ABI_PATH / "mech_marketplace.json"

    def prepare_request_tx(
        self,
        from_address: str,
        data: bytes,
        priority_mech: str,
        priority_mech_staking_instance: str,
        priority_mech_service_id: int,
        requester_staking_instance: str,
        requester_service_id: int,
        response_timeout: int,
        value: int = 10**16,  # Default 0.01 xDAI
    ) -> Optional[Dict]:
        """Prepare a marketplace request transaction."""
        return self.prepare_transaction(
            method_name="request",
            method_kwargs={
                "data": data,
                "priorityMech": priority_mech,
                "priorityMechStakingInstance": priority_mech_staking_instance,
                "priorityMechServiceId": priority_mech_service_id,
                "requesterStakingInstance": requester_staking_instance,
                "requesterServiceId": requester_service_id,
                "response_timeout": response_timeout,
            },
            tx_params={"from": from_address, "value": value},
        )
