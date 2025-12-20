"""Tests for Mech contracts."""

import pytest
from unittest.mock import MagicMock, patch
from iwa.plugins.olas.contracts.mech import MechContract
from iwa.plugins.olas.contracts.mech_marketplace import MechMarketplaceContract


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
            contract = MechContract("0xMechAddress", "gnosis")
            data = b"some data"
            from_address = "0xFromAddress"

            # Mocking prepare_transaction since it involves web3 objects
            contract.prepare_transaction = MagicMock(return_value={"data": "0xTxData", "value": 10**16})

            tx = contract.prepare_request_tx(from_address, data)

            assert tx["data"] == "0xTxData"
            contract.prepare_transaction.assert_called_once_with(
                method_name="request",
                method_kwargs={"data": data},
                tx_params={"from": from_address, "value": 10**16}
            )

    def test_mech_marketplace_contract_prepare_request_tx(self, mock_chain_interface):
        """Test prepare_request_tx for MechMarketplaceContract."""
        with patch("iwa.core.contracts.contract.ChainInterfaces") as mock_interfaces_class:
            mock_interfaces_class.return_value.get.return_value = mock_chain_interface
            contract = MechMarketplaceContract("0xMarketplaceAddress", "gnosis")
            data = b"some data"
            from_address = "0xFromAddress"
            priority_mech = "0xPriorityMech"
            staking_instance = "0xStakingInstance"
            service_id = 975

            contract.prepare_transaction = MagicMock(return_value={"data": "0xMarketplaceTxData", "value": 10**16})

            tx = contract.prepare_request_tx(
                from_address=from_address,
                data=data,
                priority_mech=priority_mech,
                priority_mech_staking_instance=staking_instance,
                priority_mech_service_id=service_id,
                requester_staking_instance=staking_instance,
                requester_service_id=123,
                response_timeout=300
            )

            assert tx["data"] == "0xMarketplaceTxData"
            contract.prepare_transaction.assert_called_once_with(
                method_name="request",
                method_kwargs={
                    "data": data,
                    "priorityMech": priority_mech,
                    "priorityMechStakingInstance": staking_instance,
                    "priorityMechServiceId": service_id,
                    "requesterStakingInstance": staking_instance,
                    "requesterServiceId": 123,
                    "response_timeout": 300
                },
                tx_params={"from": from_address, "value": 10**16}
            )
