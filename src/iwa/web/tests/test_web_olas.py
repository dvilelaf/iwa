"""Tests for Olas Web API endpoints."""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch

# We need to mock Wallet and ChainInterfaces BEFORE importing app from server
with patch("iwa.core.wallet.Wallet"), \
     patch("iwa.core.chain.ChainInterfaces"), \
     patch("iwa.core.wallet.init_db"):
    from iwa.web.server import app

from iwa.plugins.olas.models import Service, OlasConfig, StakingStatus

@pytest.fixture
def client():
    """TestClient for FastAPI app."""
    return TestClient(app)

@pytest.fixture
def mock_olas_config():
    """Mock Olas configuration."""
    service = Service(
        service_id=1,
        service_name="Test Service",
        chain_name="gnosis",
        agent_address="0x78731D3Ca6b7E34aC0F824c42a7cC18A495cabaB",
        multisig_address="0x40A2aCCbd92BCA938b02010E17A5b8929b49130D",
        service_owner_address="0x1111111111111111111111111111111111111111",
        staking_contract_address="0x78731D3Ca6b7E34aC0F824c42a7cC18A495cabaB"
    )
    return OlasConfig(services={"gnosis:1": service})

def test_get_olas_price(client):
    """Test /api/olas/price endpoint."""
    with patch("iwa.core.pricing.PriceService") as mock_price_cls:
        mock_price_cls.return_value.get_token_price.return_value = 5.0
        response = client.get("/api/olas/price")
        assert response.status_code == 200
        assert response.json() == {"price_eur": 5.0, "symbol": "OLAS"}

def test_get_olas_services_basic(client, mock_olas_config):
    """Test /api/olas/services/basic endpoint."""
    with patch("iwa.core.models.Config") as mock_config_cls:
        mock_config = mock_config_cls.return_value
        mock_config.plugins = {"olas": mock_olas_config.model_dump()}

        # Mock wallet.key_storage.find_stored_account
        from iwa.web.server import wallet
        wallet.key_storage.find_stored_account.return_value = MagicMock(tag="test_tag")

        response = client.get("/api/olas/services/basic?chain=gnosis")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["name"] == "Test Service"
        assert data[0]["accounts"]["agent"]["tag"] == "test_tag"

def test_get_olas_service_details(client, mock_olas_config):
    """Test /api/olas/services/{service_key}/details endpoint."""
    with patch("iwa.core.models.Config") as mock_config_cls, \
         patch("iwa.plugins.olas.service_manager.ServiceManager") as mock_sm_cls:

        mock_config = mock_config_cls.return_value
        mock_config.plugins = {"olas": mock_olas_config.model_dump()}

        mock_sm = mock_sm_cls.return_value
        mock_sm.get_staking_status.return_value = StakingStatus(
            is_staked=True,
            staking_state="STAKED",
            accrued_reward_olas=10.5,
            remaining_epoch_seconds=3600
        )

        from iwa.web.server import wallet
        wallet.get_native_balance_eth.return_value = 1.0
        wallet.balance_service.get_erc20_balance_wei.return_value = 10**18
        wallet.key_storage.find_stored_account.return_value = MagicMock(tag="test_tag")

        response = client.get("/api/olas/services/gnosis:1/details")
        assert response.status_code == 200
        data = response.json()
        assert data["staking"]["is_staked"] is True
        assert data["staking"]["accrued_reward_olas"] == 10.5
        assert data["accounts"]["agent"]["native"] == "1.00"

def test_get_olas_services_full(client, mock_olas_config):
    """Test /api/olas/services (full) endpoint."""
    with patch("iwa.core.models.Config") as mock_config_cls, \
         patch("iwa.plugins.olas.service_manager.ServiceManager") as mock_sm_cls:

        mock_config = mock_config_cls.return_value
        mock_config.plugins = {"olas": mock_olas_config.model_dump()}

        mock_sm = mock_sm_cls.return_value
        mock_sm.get_staking_status.return_value = StakingStatus(
            is_staked=True,
            staking_state="STAKED"
        )

        from iwa.web.server import wallet
        wallet.get_native_balance_eth.return_value = 1.0
        wallet.balance_service.get_erc20_balance_wei.return_value = 10**18

        response = client.get("/api/olas/services?chain=gnosis")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["staking"]["is_staked"] is True

def test_olas_actions(client, mock_olas_config):
    """Test Olas action endpoints (claim, unstake, checkpoint)."""
    with patch("iwa.core.models.Config") as mock_config_cls, \
         patch("iwa.plugins.olas.service_manager.ServiceManager") as mock_sm_cls:

        mock_config = mock_config_cls.return_value
        mock_config.plugins = {"olas": mock_olas_config.model_dump()}

        mock_sm = mock_sm_cls.return_value
        mock_sm.claim_rewards.return_value = (True, 10**18)
        mock_sm.unstake.return_value = True
        mock_sm.call_checkpoint.return_value = True

        # Mock StakingContract.from_address and ChainInterfaces
        with patch("iwa.plugins.olas.contracts.staking.StakingContract") as mock_sc_cls:
            from iwa.core.chain import ChainInterfaces
            # Properly access the return value of the mocked class singleton-like usage
            if hasattr(ChainInterfaces, "return_value"):
                ChainInterfaces.return_value.get.return_value.chain = MagicMock()

            mock_sc = mock_sc_cls.from_address.return_value

            # Claim
            response = client.post("/api/olas/claim/gnosis:1")
            assert response.status_code == 200
            assert response.json()["status"] == "success"

            # Unstake
            response = client.post("/api/olas/unstake/gnosis:1")
            assert response.status_code == 200
            assert response.json()["status"] == "success"

            # Checkpoint
            response = client.post("/api/olas/checkpoint/gnosis:1")
            assert response.status_code == 200
            assert response.json()["status"] == "success"
