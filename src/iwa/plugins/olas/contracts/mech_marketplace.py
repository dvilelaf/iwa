"""Mech Marketplace contract interaction."""

from typing import Dict, Optional

from iwa.core.contracts.contract import ContractInstance
from iwa.core.types import EthereumAddress
from iwa.plugins.olas.contracts.base import OLAS_ABI_PATH


class MechMarketplaceContract(ContractInstance):
    """Class to interact with the Mech Marketplace contract."""

    name = "mech_marketplace"
    abi_path = OLAS_ABI_PATH / "mech_marketplace.json"

    def prepare_request_tx(
        self,
        from_address: EthereumAddress,
        request_data: bytes,
        priority_mech: EthereumAddress,
        response_timeout: int = 300,
        max_delivery_rate: int = 10_000,
        payment_type: bytes = b"\x00" * 32,
        payment_data: bytes = b"",
        value: int = 10_000_000_000_000_000,  # Default 0.01 xDAI
    ) -> Optional[Dict]:
        """Prepare a marketplace request transaction.

        Matches ABI:
        request(bytes requestData, uint256 maxDeliveryRate, bytes32 paymentType, address priorityMech, uint256 responseTimeout, bytes paymentData)
        """
        return self.prepare_transaction(
            method_name="request",
            method_kwargs={
                "requestData": request_data,
                "maxDeliveryRate": max_delivery_rate,
                "paymentType": payment_type,
                "priorityMech": priority_mech,
                "responseTimeout": response_timeout,
                "paymentData": payment_data,
            },
            tx_params={"from": from_address, "value": value},
        )
