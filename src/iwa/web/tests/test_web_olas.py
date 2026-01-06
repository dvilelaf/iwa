"""Tests for Olas Web API endpoints."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# We need to mock Wallet and ChainInterfaces BEFORE importing app from server
# Also mock _get_webui_password to bypass authentication in tests
with (
    patch("iwa.core.wallet.Wallet"),
    patch("iwa.core.chain.ChainInterfaces"),
    patch("iwa.core.wallet.init_db"),
    patch("iwa.web.dependencies._get_webui_password", return_value=None),
):
    from iwa.web.dependencies import verify_auth
    from iwa.web.server import app

from iwa.plugins.olas.models import OlasConfig, Service, StakingStatus


# Override auth for all tests
async def override_verify_auth():
    """Override auth for testing."""
    return True


app.dependency_overrides[verify_auth] = override_verify_auth


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
        staking_contract_address="0x78731D3Ca6b7E34aC0F824c42a7cC18A495cabaB",
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
    with patch("iwa.web.routers.olas.services.Config") as mock_config_cls:
        mock_config = mock_config_cls.return_value
        mock_config.plugins = {"olas": mock_olas_config.model_dump()}

        # Mock wallet.key_storage.find_stored_account
        from iwa.web.dependencies import wallet

        wallet.key_storage.find_stored_account.return_value = MagicMock(tag="test_tag")

        response = client.get("/api/olas/services/basic?chain=gnosis")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["name"] == "Test Service"
        assert data[0]["accounts"]["agent"]["tag"] == "test_tag"


def test_get_olas_service_details(client, mock_olas_config):
    """Test /api/olas/services/{service_key}/details endpoint."""
    with (
        patch("iwa.web.routers.olas.services.Config") as mock_config_cls,
        patch("iwa.plugins.olas.service_manager.ServiceManager") as mock_sm_cls,
    ):
        mock_config = mock_config_cls.return_value
        mock_config.plugins = {"olas": mock_olas_config.model_dump()}

        mock_sm = mock_sm_cls.return_value
        mock_sm.get_staking_status.return_value = StakingStatus(
            is_staked=True,
            staking_state="STAKED",
            accrued_reward_olas=10.5,
            remaining_epoch_seconds=3600,
        )

        from iwa.web.dependencies import wallet

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
    with (
        patch("iwa.web.routers.olas.services.Config") as mock_config_cls,
        patch("iwa.plugins.olas.service_manager.ServiceManager") as mock_sm_cls,
    ):
        mock_config = mock_config_cls.return_value
        mock_config.plugins = {"olas": mock_olas_config.model_dump()}

        mock_sm = mock_sm_cls.return_value
        mock_sm.get_staking_status.return_value = StakingStatus(
            is_staked=True, staking_state="STAKED"
        )

        from iwa.web.dependencies import wallet

        wallet.get_native_balance_eth.return_value = 1.0
        wallet.balance_service.get_erc20_balance_wei.return_value = 10**18

        response = client.get("/api/olas/services?chain=gnosis")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["staking"]["is_staked"] is True


def test_olas_actions(client, mock_olas_config):
    """Test Olas action endpoints (claim, unstake, checkpoint)."""
    with (
        patch("iwa.web.routers.olas.staking.Config") as mock_config_cls,
        patch("iwa.plugins.olas.service_manager.ServiceManager") as mock_sm_cls,
    ):
        mock_config = mock_config_cls.return_value
        mock_config.plugins = {"olas": mock_olas_config.model_dump()}

        mock_sm = mock_sm_cls.return_value
        mock_sm.claim_rewards.return_value = (True, 10**18)
        mock_sm.unstake.return_value = True
        mock_sm.call_checkpoint.return_value = True

        # Mock StakingContract.from_address and ChainInterfaces
        with patch("iwa.plugins.olas.contracts.staking.StakingContract"):
            from iwa.core.chain import ChainInterfaces

            # Properly access the return value of the mocked class singleton-like usage
            if hasattr(ChainInterfaces, "return_value"):
                ChainInterfaces.return_value.get.return_value.chain = MagicMock()

            # mock_sc = mock_sc_cls.from_address.return_value

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


# --- Additional tests for uncovered endpoints ---


def test_get_staking_contracts(client):
    """Test /api/olas/staking-contracts endpoint - returns response with contracts and filter_info."""
    response = client.get("/api/olas/staking-contracts?chain=gnosis")
    assert response.status_code == 200
    data = response.json()
    # New format: {contracts: [...], filter_info: {...}}
    assert isinstance(data, dict)
    assert "contracts" in data
    assert "filter_info" in data
    assert isinstance(data["contracts"], list)
    assert isinstance(data["filter_info"], dict)


def test_create_service(client, mock_olas_config):
    """Test /api/olas/create endpoint."""
    with (
        patch(
            "iwa.web.routers.olas.services.Config"
        ) as mock_config_cls,  # Not strictly used but kept for consistency if needed
        patch("iwa.plugins.olas.service_manager.ServiceManager") as mock_sm_cls,
    ):
        mock_config = mock_config_cls.return_value
        mock_config.plugins = {"olas": mock_olas_config.model_dump()}

        mock_sm = mock_sm_cls.return_value
        mock_sm.create.return_value = 123
        mock_sm.spin_up.return_value = True
        mock_sm.service = MagicMock()
        mock_sm.service.service_id = 123

        response = client.post(
            "/api/olas/create",
            json={
                "service_name": "Test Service",
                "chain": "gnosis",
                "bond_amount_olas": 100,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"


def test_create_service_failure(client, mock_olas_config):
    """Test /api/olas/create when creation fails."""
    with (
        patch("iwa.web.routers.olas.services.Config") as mock_config_cls,
        patch("iwa.plugins.olas.service_manager.ServiceManager") as mock_sm_cls,
    ):
        mock_config = mock_config_cls.return_value
        mock_config.plugins = {"olas": mock_olas_config.model_dump()}

        mock_sm = mock_sm_cls.return_value
        mock_sm.create.return_value = None  # Creation fails

        response = client.post(
            "/api/olas/create",
            json={
                "service_name": "Test Service",
                "chain": "gnosis",
            },
        )
        # API returns 400 on creation failure
        assert response.status_code == 400


def test_deploy_service(client, mock_olas_config):
    """Test /api/olas/deploy/{service_key} endpoint."""
    with (
        patch("iwa.web.routers.olas.services.Config") as mock_config_cls,
        patch("iwa.plugins.olas.service_manager.ServiceManager") as mock_sm_cls,
    ):
        mock_config = mock_config_cls.return_value
        mock_config.plugins = {"olas": mock_olas_config.model_dump()}

        mock_sm = mock_sm_cls.return_value
        mock_sm.spin_up.return_value = True
        mock_sm.service = mock_olas_config.services["gnosis:1"]
        mock_sm.get_service_state.return_value = "PRE_REGISTRATION"

        response = client.post("/api/olas/deploy/gnosis:1")
        assert response.status_code == 200
        assert response.json()["status"] == "success"


def test_deploy_service_failure(client, mock_olas_config):
    """Test /api/olas/deploy/{service_key} when deployment fails."""
    with (
        patch("iwa.web.routers.olas.services.Config") as mock_config_cls,
        patch("iwa.plugins.olas.service_manager.ServiceManager") as mock_sm_cls,
    ):
        mock_config = mock_config_cls.return_value
        mock_config.plugins = {"olas": mock_olas_config.model_dump()}

        mock_sm = mock_sm_cls.return_value
        mock_sm.spin_up.return_value = False
        mock_sm.get_service_state.return_value = "PRE_REGISTRATION"

        response = client.post("/api/olas/deploy/gnosis:1")
        # API returns 400 on spin_up failure
        assert response.status_code == 400


def test_activate_registration(client, mock_olas_config):
    """Test /api/olas/activate/{service_key} endpoint."""
    with (
        patch("iwa.web.routers.olas.admin.Config") as mock_config_cls,
        patch("iwa.plugins.olas.service_manager.ServiceManager") as mock_sm_cls,
    ):
        mock_config = mock_config_cls.return_value
        mock_config.plugins = {"olas": mock_olas_config.model_dump()}

        mock_sm = mock_sm_cls.return_value
        mock_sm.activate_registration.return_value = True

        response = client.post("/api/olas/activate/gnosis:1")
        assert response.status_code == 200
        assert response.json()["status"] == "success"


def test_register_agent(client, mock_olas_config):
    """Test /api/olas/register/{service_key} endpoint."""
    with (
        patch("iwa.web.routers.olas.admin.Config") as mock_config_cls,
        patch("iwa.plugins.olas.service_manager.ServiceManager") as mock_sm_cls,
    ):
        mock_config = mock_config_cls.return_value
        mock_config.plugins = {"olas": mock_olas_config.model_dump()}

        mock_sm = mock_sm_cls.return_value
        mock_sm.register_agent.return_value = True

        # Correct URL is /register/ not /register-agent/
        response = client.post("/api/olas/register/gnosis:1")
        assert response.status_code == 200
        assert response.json()["status"] == "success"


def test_deploy_step(client, mock_olas_config):
    """Test /api/olas/deploy-step/{service_key} endpoint."""
    with (
        patch("iwa.web.routers.olas.admin.Config") as mock_config_cls,
        patch("iwa.plugins.olas.service_manager.ServiceManager") as mock_sm_cls,
    ):
        mock_config = mock_config_cls.return_value
        mock_config.plugins = {"olas": mock_olas_config.model_dump()}

        mock_sm = mock_sm_cls.return_value
        mock_sm.deploy.return_value = "0xMultisig123"  # Returns multisig address

        response = client.post("/api/olas/deploy-step/gnosis:1")
        assert response.status_code == 200
        data = response.json()
        # API only returns {"status": "success"}, not multisig
        assert data["status"] == "success"


def test_stake_service(client, mock_olas_config):
    """Test /api/olas/stake/{service_key} endpoint."""
    with (
        patch("iwa.web.routers.olas.staking.Config") as mock_config_cls,
        patch("iwa.plugins.olas.service_manager.ServiceManager") as mock_sm_cls,
        patch("iwa.plugins.olas.contracts.staking.StakingContract"),
    ):
        mock_config = mock_config_cls.return_value
        mock_config.plugins = {"olas": mock_olas_config.model_dump()}

        mock_sm = mock_sm_cls.return_value
        mock_sm.stake.return_value = True

        response = client.post(
            "/api/olas/stake/gnosis:1?staking_contract=0x1234567890123456789012345678901234567890"
        )
        assert response.status_code == 200
        assert response.json()["status"] == "success"


def test_terminate_service(client, mock_olas_config):
    """Test /api/olas/terminate/{service_key} endpoint."""
    with (
        patch("iwa.web.routers.olas.admin.Config") as mock_config_cls,
        patch("iwa.plugins.olas.service_manager.ServiceManager") as mock_sm_cls,
        patch("iwa.plugins.olas.contracts.staking.StakingContract"),
    ):
        mock_config = mock_config_cls.return_value
        mock_config.plugins = {"olas": mock_olas_config.model_dump()}

        mock_sm = mock_sm_cls.return_value
        mock_sm.wind_down.return_value = True

        response = client.post("/api/olas/terminate/gnosis:1")
        assert response.status_code == 200
        assert response.json()["status"] == "success"


def test_fund_service(client, mock_olas_config):
    """Test /api/olas/fund/{service_key} endpoint."""
    with (
        patch("iwa.web.routers.olas.funding.Config") as mock_config_cls,
        patch("iwa.web.routers.olas.funding.wallet") as mock_wallet,
    ):
        mock_config = mock_config_cls.return_value
        mock_config.plugins = {"olas": mock_olas_config.model_dump()}

        mock_wallet.send.return_value = "0xTxHash"

        response = client.post(
            "/api/olas/fund/gnosis:1",
            json={"agent_amount_eth": 1.0, "safe_amount_eth": 2.0},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"


def test_drain_service(client, mock_olas_config):
    """Test /api/olas/drain/{service_key} endpoint."""
    with (
        patch("iwa.web.routers.olas.funding.Config") as mock_config_cls,
        patch("iwa.plugins.olas.service_manager.ServiceManager") as mock_sm_cls,
    ):
        mock_config = mock_config_cls.return_value
        mock_config.plugins = {"olas": mock_olas_config.model_dump()}

        mock_sm = mock_sm_cls.return_value
        mock_sm.drain_service.return_value = {
            "safe": {"native": 1.5, "olas": 100.0},
            "agent": {"native": 0.5},
        }

        response = client.post("/api/olas/drain/gnosis:1")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert "safe" in data["drained"]


def test_service_not_found(client):
    """Test endpoints return 404 when service not found."""
    with patch("iwa.web.routers.olas.admin.Config") as mock_config_cls:
        mock_config = mock_config_cls.return_value
        mock_config.plugins = {"olas": OlasConfig().model_dump()}

        response = client.post("/api/olas/activate/gnosis:999")
        assert response.status_code == 404

        response = client.post("/api/olas/register/gnosis:999")
        assert response.status_code == 404

        response = client.post("/api/olas/deploy-step/gnosis:999")
        assert response.status_code == 404
