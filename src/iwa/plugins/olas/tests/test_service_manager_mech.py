"""Tests for Mech integration in ServiceManager."""

import pytest
from unittest.mock import MagicMock, patch
from iwa.plugins.olas.service_manager import ServiceManager
from iwa.plugins.olas.contracts.service import ServiceState
from iwa.plugins.olas.models import Service, OlasConfig


@pytest.fixture
def mock_wallet():
    """Mock wallet fixture."""
    wallet = MagicMock()
    wallet.send.return_value = "0xMockTxHash"
    return wallet


@pytest.fixture
def mock_service():
    """Mock Service model."""
    service = MagicMock(spec=Service)
    service.service_id = 1
    service.chain_name = "gnosis"
    service.multisig_address = "0xMultisigAddress"
    service.staking_contract_address = "0xStakingAddress"
    return service


@pytest.fixture
def mock_olas_config(mock_service):
    """Mock OlasConfig."""
    config = MagicMock(spec=OlasConfig)
    config.get_active_service.return_value = mock_service
    return config


@pytest.fixture
def service_manager(mock_wallet, mock_olas_config):
    """Create ServiceManager with mocks."""
    with patch("iwa.plugins.olas.service_manager.Config") as mock_config_class:
        mock_config = mock_config_class.return_value
        mock_config.plugins = {"olas": mock_olas_config}

        sm = ServiceManager(mock_wallet)
        # Mocking registry to avoid initialization calls
        sm.registry = MagicMock()
        sm.chain_interface = MagicMock()
        sm.chain_interface.get_contract_address.side_effect = lambda k: {
            "OLAS_MECH": "0xMechAddress",
            "OLAS_MECH_MARKETPLACE": "0xMarketplaceAddress",
        }.get(k)
        return sm


class TestServiceManagerMech:
    """Tests for Mech request functionality in ServiceManager."""

    def test_send_mech_request_legacy(self, service_manager, mock_wallet):
        """Test sending a legacy Mech request."""
        data = b"some request data"

        with patch("iwa.plugins.olas.service_manager.MechContract") as mock_mech_class:
            mock_mech = mock_mech_class.return_value
            mock_mech.prepare_request_tx.return_value = {
                "data": "0xEncodedData",
                "value": 10**16
            }

            tx_hash = service_manager.send_mech_request(data=data, use_marketplace=False)

            assert tx_hash == "0xMockTxHash"
            mock_mech.prepare_request_tx.assert_called_once()
            mock_wallet.send.assert_called_once_with(
                to="0xMechAddress",
                value=10**16,
                data="0xEncodedData",
                safe_address="0xMultisigAddress"
            )

    def test_send_mech_request_marketplace(self, service_manager, mock_wallet):
        """Test sending a marketplace Mech request."""
        data = b"marketplace data"

        with patch("iwa.plugins.olas.service_manager.MechMarketplaceContract") as mock_market_class:
            mock_market = mock_market_class.return_value
            mock_market.prepare_request_tx.return_value = {
                "data": "0xMarketplaceEncoded",
                "value": 2 * 10**16
            }

            tx_hash = service_manager.send_mech_request(
                data=data,
                use_marketplace=True,
                priority_mech="0xPriorityMech",
                response_timeout=600,
                value=2 * 10**16
            )

            assert tx_hash == "0xMockTxHash"
            mock_market.prepare_request_tx.assert_called_once_with(
                from_address="0xMultisigAddress",
                data=data,
                priority_mech="0xPriorityMech",
                priority_mech_staking_instance="",
                priority_mech_service_id=0,
                requester_staking_instance="0xStakingAddress",
                requester_service_id=1,
                response_timeout=600,
                value=2 * 10**16
            )
            mock_wallet.send.assert_called_once_with(
                to="0xMarketplaceAddress",
                value=2 * 10**16,
                data="0xMarketplaceEncoded",
                safe_address="0xMultisigAddress"
            )
