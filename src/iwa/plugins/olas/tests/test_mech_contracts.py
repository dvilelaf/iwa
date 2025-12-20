"""Tests for Mech contracts."""

from unittest.mock import MagicMock, patch

import pytest

from iwa.plugins.olas.constants import PAYMENT_TYPE_NATIVE
from iwa.plugins.olas.contracts.mech import MechContract
from iwa.plugins.olas.contracts.mech_marketplace import MechMarketplaceContract

# Valid Ethereum addresses for testing
VALID_FROM_ADDRESS = "0x0000000000000000000000000000000000000001"
VALID_MECH_ADDRESS = "0x0000000000000000000000000000000000000002"
VALID_MARKETPLACE_ADDRESS = "0x0000000000000000000000000000000000000003"
VALID_PRIORITY_MECH = "0x0000000000000000000000000000000000000004"


class TestMechContracts:
    """Test suite for Mech contract classes."""

    @pytest.fixture
    def mock_chain_interface(self):
        """Mock chain interface."""
        mock = MagicMock()
        mock.chain_name = "gnosis"
        return mock

    def test_mech_contract_prepare_request_tx(self, mock_chain_interface):
        """Test prepare_request_tx for MechContract."""
        with patch("iwa.core.contracts.contract.ChainInterfaces") as mock_interfaces_class:
            mock_interfaces_class.return_value.get.return_value = mock_chain_interface
            contract = MechContract(VALID_MECH_ADDRESS, "gnosis")
            data = b"some data"

            # Mocking prepare_transaction since it involves web3 objects
            contract.prepare_transaction = MagicMock(
                return_value={"data": "0xTxData", "value": 10**16}
            )
            # Mock get_price to avoid web3 call
            contract.get_price = MagicMock(return_value=10**16)

            tx = contract.prepare_request_tx(VALID_FROM_ADDRESS, data)

            assert tx["data"] == "0xTxData"
            contract.prepare_transaction.assert_called_once_with(
                method_name="request",
                method_kwargs={"data": data},
                tx_params={"from": VALID_FROM_ADDRESS, "value": 10**16},
            )

    def test_mech_marketplace_contract_prepare_request_tx(self, mock_chain_interface):
        """Test prepare_request_tx for MechMarketplaceContract."""
        with patch("iwa.core.contracts.contract.ChainInterfaces") as mock_interfaces_class:
            mock_interfaces_class.return_value.get.return_value = mock_chain_interface
            contract = MechMarketplaceContract(VALID_MARKETPLACE_ADDRESS, "gnosis")
            request_data = b"some data"
            payment_type_bytes = bytes.fromhex(PAYMENT_TYPE_NATIVE)

            contract.prepare_transaction = MagicMock(
                return_value={"data": "0xMarketplaceTxData", "value": 10**16}
            )

            tx = contract.prepare_request_tx(
                from_address=VALID_FROM_ADDRESS,
                request_data=request_data,
                priority_mech=VALID_PRIORITY_MECH,
                response_timeout=300,
                max_delivery_rate=10_000,
                payment_type=payment_type_bytes,
                payment_data=b"",
            )

            assert tx["data"] == "0xMarketplaceTxData"
            contract.prepare_transaction.assert_called_once_with(
                method_name="request",
                method_kwargs={
                    "requestData": request_data,
                    "maxDeliveryRate": 10_000,
                    "paymentType": payment_type_bytes,
                    "priorityMech": VALID_PRIORITY_MECH,
                    "responseTimeout": 300,
                    "paymentData": b"",
                },
                tx_params={"from": VALID_FROM_ADDRESS, "value": 10**16},
            )
