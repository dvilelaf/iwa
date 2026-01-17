"""Mech Marketplace V1 contract interaction (VERSION 1.0.0).

This contract version is used by older staking programs like Expert 17 MM.
It has a different request signature than v2, requiring staking instance
and service ID parameters for both the mech and the requester.

Key differences from v2:
- request() takes staking instance + service ID for both mech and requester
- No payment types or balance trackers
- No checkMech or mapPaymentTypeBalanceTrackers functions
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

from iwa.core.contracts.contract import ContractInstance
from iwa.core.types import EthereumAddress


@dataclass
class V1RequestParams:
    """Parameters for v1 marketplace request."""

    data: bytes
    priority_mech: str
    priority_mech_staking_instance: str
    priority_mech_service_id: int
    requester_staking_instance: str
    requester_service_id: int
    response_timeout: int = 300
    value: int = 10_000_000_000_000_000  # 0.01 xDAI


class MechMarketplaceV1Contract(ContractInstance):
    """Class to interact with the Mech Marketplace v1 contract (VERSION 1.0.0).

    This is the older marketplace used by staking contracts like Expert 17 MM.
    """

    name = "mech_marketplace_v1"
    abi_path = Path(__file__).parent / "abis" / "mech_marketplace_v1.json"

    def prepare_request_tx(
        self,
        from_address: EthereumAddress,
        params: V1RequestParams,
    ) -> Optional[Dict]:
        """Prepare a v1 marketplace request transaction.

        v1 ABI: request(bytes data, address priorityMech,
                        address priorityMechStakingInstance, uint256 priorityMechServiceId,
                        address requesterStakingInstance, uint256 requesterServiceId,
                        uint256 responseTimeout)
        """
        return self.prepare_transaction(
            method_name="request",
            method_kwargs={
                "data": params.data,
                "priorityMech": params.priority_mech,
                "priorityMechStakingInstance": params.priority_mech_staking_instance,
                "priorityMechServiceId": params.priority_mech_service_id,
                "requesterStakingInstance": params.requester_staking_instance,
                "requesterServiceId": params.requester_service_id,
                "responseTimeout": params.response_timeout,
            },
            tx_params={"from": from_address, "value": params.value},
        )
