"""Tests for Mech integration in ServiceManager."""

from unittest.mock import MagicMock, patch

import pytest

from iwa.plugins.olas.constants import PAYMENT_TYPE_NATIVE
from iwa.plugins.olas.models import OlasConfig, Service
from iwa.plugins.olas.service_manager import ServiceManager

# Valid Ethereum address for testing
VALID_PRIORITY_MECH = "0x0000000000000000000000000000000000000001"
VALID_MULTISIG = "0x0000000000000000000000000000000000000002"
VALID_MARKETPLACE = "0x0000000000000000000000000000000000000003"


@pytest.fixture
def mock_wallet():
    """Mock wallet fixture."""
    wallet = MagicMock()
    wallet.safe_service = MagicMock()
    wallet.safe_service.execute_safe_transaction.return_value = "0xMockTxHash"
    wallet.account_service = MagicMock()
    return wallet


@pytest.fixture
def mock_service():
    """Mock Service model."""
    service = MagicMock(spec=Service)
    service.service_id = 1
    service.chain_name = "gnosis"
    service.multisig_address = VALID_MULTISIG
    service.staking_contract_address = "0xStakingAddress"
    return service


@pytest.fixture
def mock_olas_config(mock_service):
    """Mock OlasConfig."""
    config = MagicMock(spec=OlasConfig)
    config.get_service.return_value = mock_service
    return config


@pytest.fixture
def service_manager(mock_wallet, mock_olas_config, mock_service):
    """Create ServiceManager with mocks."""
    with patch("iwa.plugins.olas.service_manager.Config") as mock_config_class:
        mock_config = mock_config_class.return_value
        mock_config.plugins = {"olas": mock_olas_config}

        sm = ServiceManager(mock_wallet, service_key="gnosis:1")
        sm.olas_config = mock_olas_config
        sm.service = mock_service
        # Mocking registry to avoid initialization calls
        sm.registry = MagicMock()
        sm.registry.chain_interface = MagicMock()
        sm.registry.chain_interface.web3 = MagicMock()
        sm.chain_interface = MagicMock()
        sm.chain_interface.chain.name = "gnosis"
        sm.chain_name = "gnosis"
        return sm


class TestServiceManagerMech:
    """Tests for Mech request functionality in ServiceManager."""

    def test_send_mech_request_marketplace_requires_priority_mech(self, service_manager):
        """Test that marketplace request requires priority_mech."""
        data = b"marketplace data"

        with patch(
            "iwa.plugins.olas.service_manager.mech.MechMarketplaceContract"
        ) as mock_market_class:
            mock_market = mock_market_class.return_value
            mock_market.prepare_request_tx.return_value = {
                "data": "0xMarketplaceEncoded",
                "value": 2 * 10**16,
            }

            # Should return None because priority_mech is not provided
            tx_hash = service_manager.send_mech_request(
                data=data,
                use_marketplace=True,
            )

            assert tx_hash is None

    def test_send_mech_request_marketplace(self, service_manager, mock_wallet):
        """Test sending a marketplace Mech request."""
        data = b"marketplace data"
        payment_type_bytes = bytes.fromhex(PAYMENT_TYPE_NATIVE)
        value = 2 * 10**16

        # Mock the account resolution to return a Safe account
        from iwa.core.models import StoredSafeAccount

        mock_safe_account = MagicMock(spec=StoredSafeAccount)
        mock_wallet.account_service.resolve_account.return_value = mock_safe_account

        with patch(
            "iwa.plugins.olas.service_manager.mech.MechMarketplaceContract"
        ) as mock_market_class:
            mock_market = mock_market_class.return_value
            mock_market.prepare_request_tx.return_value = {
                "data": "0xMarketplaceEncoded",
                "value": value,
            }
            # Mock event extraction to simulate successful event
            mock_market.extract_events.return_value = [{"name": "MarketplaceRequest"}]

            # Mock wait_for_transaction_receipt
            service_manager.registry.chain_interface.web3.eth.wait_for_transaction_receipt.return_value = {}

            tx_hash = service_manager.send_mech_request(
                data=data,
                use_marketplace=True,
                priority_mech=VALID_PRIORITY_MECH,
                response_timeout=300,  # Within bounds [60, 300]
                value=value,
            )

            assert tx_hash == "0xMockTxHash"
            # Note: max_delivery_rate now defaults to value
            mock_market.prepare_request_tx.assert_called_once_with(
                from_address=VALID_MULTISIG,
                request_data=data,
                priority_mech=VALID_PRIORITY_MECH,
                response_timeout=300,
                max_delivery_rate=value,  # Defaults to value
                payment_type=payment_type_bytes,
                payment_data=b"",
                value=value,
            )
