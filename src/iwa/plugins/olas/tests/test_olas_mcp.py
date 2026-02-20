"""Tests for Olas MCP tools."""

import asyncio
from unittest.mock import MagicMock, patch

import pytest
from fastmcp import FastMCP

from iwa.plugins.olas.models import OlasConfig, Service

# --- Constants ---

ADDR_AGENT = "0x1111111111111111111111111111111111111111"
ADDR_SAFE = "0x2222222222222222222222222222222222222222"
ADDR_OWNER = "0x3333333333333333333333333333333333333333"
ADDR_STAKING = "0x78731D3Ca6b7E34aC0F824c42a7cC18A495cabaB"
SERVICE_KEY = "gnosis:1"

# Patch paths (source modules, since mcp.py uses lazy imports)
_SM = "iwa.plugins.olas.service_manager.ServiceManager"
_SC = "iwa.plugins.olas.contracts.staking.StakingContract"
_STAKING_CONTRACTS = "iwa.plugins.olas.constants.OLAS_TRADER_STAKING_CONTRACTS"
_PRICE_SVC = "iwa.core.pricing.PriceService"


def _make_service(**overrides) -> Service:
    defaults = {
        "service_name": "Test Service",
        "chain_name": "gnosis",
        "service_id": 1,
        "agent_ids": [],
        "agent_address": ADDR_AGENT,
        "multisig_address": ADDR_SAFE,
        "staking_contract_address": ADDR_STAKING,
    }
    defaults.update(overrides)
    return Service(**defaults)


def _make_olas_config(service=None) -> OlasConfig:
    if service is None:
        service = _make_service()
    return OlasConfig(services={SERVICE_KEY: service})


# --- Helpers ---


def _get_tool_fn(mcp: FastMCP, name: str):
    """Extract a tool function from the MCP server by name."""
    tool = asyncio.run(mcp.get_tool(name))
    if tool is None:
        raise ValueError(f"Tool '{name}' not found")
    return tool.fn


def _make_mcp() -> FastMCP:
    """Create a test MCP server with olas tools registered."""
    from iwa.plugins.olas.mcp import register_olas_tools

    mcp = FastMCP("test-olas")
    register_olas_tools(mcp)
    return mcp


# --- Fixtures ---


@pytest.fixture
def mcp():
    return _make_mcp()


@pytest.fixture
def mock_config():
    """Patch Config to return our test olas config."""
    olas_config = _make_olas_config()
    config = MagicMock()
    config.plugins = {"olas": olas_config.model_dump()}
    with patch("iwa.core.models.Config", return_value=config):
        yield config


@pytest.fixture
def mock_wallet():
    with patch("iwa.core.wallet.Wallet") as mock_cls:
        wallet = MagicMock()
        mock_cls.return_value = wallet
        yield wallet


# ---------------------------------------------------------------------------
# Service tools
# ---------------------------------------------------------------------------


class TestOlasListServices:
    def test_list_services(self, mcp, mock_config):
        fn = _get_tool_fn(mcp, "olas_list_services")
        result = fn(chain="gnosis")

        assert result["chain"] == "gnosis"
        assert len(result["services"]) == 1
        assert result["services"][0]["service_key"] == SERVICE_KEY
        assert result["services"][0]["name"] == "Test Service"

    def test_list_services_empty_chain(self, mcp, mock_config):
        fn = _get_tool_fn(mcp, "olas_list_services")
        result = fn(chain="ethereum")

        assert result["services"] == []

    def test_list_services_no_olas_config(self, mcp):
        config = MagicMock()
        config.plugins = {}
        with patch("iwa.core.models.Config", return_value=config):
            fn = _get_tool_fn(mcp, "olas_list_services")
            result = fn(chain="gnosis")

        assert result["services"] == []


class TestOlasServiceDetails:
    def test_service_details(self, mcp, mock_wallet, mock_config):
        with patch(_SM) as sm_cls:
            sm = MagicMock()
            sm_cls.return_value = sm
            sm.get_service_state.return_value = "DEPLOYED"

            staking = MagicMock()
            staking.is_staked = True
            staking.staking_state = "STAKED"
            staking.staking_contract_name = "pearl_beta"
            staking.accrued_reward_olas = 1.5
            staking.epoch_end_utc = "2026-02-20T00:00:00"
            staking.mech_requests_this_epoch = 3
            staking.required_mech_requests = 1
            staking.has_enough_requests = True
            sm.get_staking_status.return_value = staking

            fn = _get_tool_fn(mcp, "olas_service_details")
            result = fn(service_key=SERVICE_KEY)

        assert result["state"] == "DEPLOYED"
        assert result["staking"]["is_staked"] is True
        assert result["staking"]["accrued_reward_olas"] == 1.5

    def test_service_details_error(self, mcp, mock_wallet, mock_config):
        with patch(_SM, side_effect=ValueError("boom")):
            fn = _get_tool_fn(mcp, "olas_service_details")
            result = fn(service_key=SERVICE_KEY)

        assert "error" in result

    def test_service_details_no_staking(self, mcp, mock_wallet, mock_config):
        with patch(_SM) as sm_cls:
            sm = MagicMock()
            sm_cls.return_value = sm
            sm.get_service_state.return_value = "PRE_REGISTRATION"
            sm.get_staking_status.return_value = None

            fn = _get_tool_fn(mcp, "olas_service_details")
            result = fn(service_key=SERVICE_KEY)

        assert result["staking"] is None


class TestOlasCreateService:
    def test_create_service(self, mcp, mock_wallet):
        with patch(_SM) as sm_cls:
            sm = MagicMock()
            sm_cls.return_value = sm
            sm.create.return_value = 42
            sm.spin_up.return_value = True
            sm.service = MagicMock()
            sm.service.key = "gnosis:42"

            fn = _get_tool_fn(mcp, "olas_create_service")
            result = fn(service_name="My Service")

        assert result["status"] == "success"
        assert result["service_id"] == 42
        assert result["service_key"] == "gnosis:42"

    def test_create_service_failed(self, mcp, mock_wallet):
        with patch(_SM) as sm_cls:
            sm = MagicMock()
            sm_cls.return_value = sm
            sm.create.return_value = None

            fn = _get_tool_fn(mcp, "olas_create_service")
            result = fn(service_name="Fail")

        assert result["error"] == "Failed to create service"

    def test_create_service_with_staking(self, mcp, mock_wallet):
        with patch(_SM) as sm_cls, patch(_SC) as sc_cls:
            sm = MagicMock()
            sm_cls.return_value = sm
            sm.create.return_value = 42
            sm.spin_up.return_value = True
            sm.service = MagicMock()
            sm.service.key = "gnosis:42"

            sc = MagicMock()
            sc_cls.return_value = sc
            sc.get_requirements.return_value = {"required_agent_bond": 10**18}

            fn = _get_tool_fn(mcp, "olas_create_service")
            result = fn(
                service_name="Staked",
                stake_on_create=True,
                staking_contract=ADDR_STAKING,
            )

        assert result["staked"] is True


class TestOlasDeployService:
    def test_deploy_service(self, mcp, mock_wallet, mock_config):
        with patch(_SM) as sm_cls:
            sm = MagicMock()
            sm_cls.return_value = sm
            sm.spin_up.return_value = True
            sm.get_service_state.return_value = "DEPLOYED"

            fn = _get_tool_fn(mcp, "olas_deploy_service")
            result = fn(service_key=SERVICE_KEY)

        assert result["status"] == "success"
        assert result["final_state"] == "DEPLOYED"

    def test_deploy_service_failed(self, mcp, mock_wallet, mock_config):
        with patch(_SM) as sm_cls:
            sm = MagicMock()
            sm_cls.return_value = sm
            sm.spin_up.return_value = False

            fn = _get_tool_fn(mcp, "olas_deploy_service")
            result = fn(service_key=SERVICE_KEY)

        assert result["status"] == "failed"

    def test_deploy_not_found(self, mcp):
        config = MagicMock()
        config.plugins = {"olas": OlasConfig().model_dump()}
        with patch("iwa.core.models.Config", return_value=config):
            fn = _get_tool_fn(mcp, "olas_deploy_service")
            with pytest.raises(ValueError, match="not found"):
                fn(service_key="gnosis:999")


# ---------------------------------------------------------------------------
# Admin / Lifecycle tools
# ---------------------------------------------------------------------------


class TestOlasActivateService:
    def test_activate(self, mcp, mock_wallet, mock_config):
        with patch(_SM) as sm_cls:
            sm = MagicMock()
            sm_cls.return_value = sm
            sm.activate_registration.return_value = True

            fn = _get_tool_fn(mcp, "olas_activate_service")
            result = fn(service_key=SERVICE_KEY)

        assert result["status"] == "success"

    def test_activate_failed(self, mcp, mock_wallet, mock_config):
        with patch(_SM) as sm_cls:
            sm = MagicMock()
            sm_cls.return_value = sm
            sm.activate_registration.return_value = False

            fn = _get_tool_fn(mcp, "olas_activate_service")
            result = fn(service_key=SERVICE_KEY)

        assert result["status"] == "failed"


class TestOlasRegisterAgent:
    def test_register(self, mcp, mock_wallet, mock_config):
        with patch(_SM) as sm_cls:
            sm = MagicMock()
            sm_cls.return_value = sm
            sm.register_agent.return_value = True

            fn = _get_tool_fn(mcp, "olas_register_agent")
            result = fn(service_key=SERVICE_KEY)

        assert result["status"] == "success"


class TestOlasDeployStep:
    def test_deploy_step(self, mcp, mock_wallet, mock_config):
        with patch(_SM) as sm_cls:
            sm = MagicMock()
            sm_cls.return_value = sm
            sm.deploy.return_value = True

            fn = _get_tool_fn(mcp, "olas_deploy_step")
            result = fn(service_key=SERVICE_KEY)

        assert result["status"] == "success"


class TestOlasTerminateService:
    def test_terminate(self, mcp, mock_wallet, mock_config):
        with patch(_SM) as sm_cls:
            sm = MagicMock()
            sm_cls.return_value = sm
            sm.get_service_state.return_value = "DEPLOYED"
            sm.wind_down.return_value = True

            fn = _get_tool_fn(mcp, "olas_terminate_service")
            result = fn(service_key=SERVICE_KEY)

        assert result["status"] == "success"
        assert "Wound down" in result["message"]

    def test_terminate_already_pre_registration(self, mcp, mock_wallet, mock_config):
        with patch(_SM) as sm_cls:
            sm = MagicMock()
            sm_cls.return_value = sm
            sm.get_service_state.return_value = "PRE_REGISTRATION"

            fn = _get_tool_fn(mcp, "olas_terminate_service")
            result = fn(service_key=SERVICE_KEY)

        assert result["status"] == "success"
        assert "Already" in result["message"]

    def test_terminate_non_existent(self, mcp, mock_wallet, mock_config):
        with patch(_SM) as sm_cls:
            sm = MagicMock()
            sm_cls.return_value = sm
            sm.get_service_state.return_value = "NON_EXISTENT"

            fn = _get_tool_fn(mcp, "olas_terminate_service")
            result = fn(service_key=SERVICE_KEY)

        assert "error" in result

    def test_terminate_with_staking(self, mcp, mock_wallet, mock_config):
        with patch(_SM) as sm_cls, patch(_SC):
            sm = MagicMock()
            sm_cls.return_value = sm
            sm.get_service_state.return_value = "DEPLOYED"
            sm.wind_down.return_value = True

            fn = _get_tool_fn(mcp, "olas_terminate_service")
            result = fn(service_key=SERVICE_KEY)

        assert result["status"] == "success"


# ---------------------------------------------------------------------------
# Staking tools
# ---------------------------------------------------------------------------


class TestOlasListStakingContracts:
    def test_list_contracts(self, mcp):
        contracts = {"pearl_beta": "0xaaa", "pearl_alpha": "0xbbb"}
        with patch(_STAKING_CONTRACTS, {"gnosis": contracts}):
            fn = _get_tool_fn(mcp, "olas_list_staking_contracts")
            result = fn(chain="gnosis")

        assert len(result["contracts"]) == 2
        assert result["chain"] == "gnosis"

    def test_list_contracts_empty_chain(self, mcp):
        with patch(_STAKING_CONTRACTS, {}):
            fn = _get_tool_fn(mcp, "olas_list_staking_contracts")
            result = fn(chain="ethereum")

        assert result["contracts"] == []


class TestOlasStakeService:
    def test_stake(self, mcp, mock_wallet, mock_config):
        with patch(_SM) as sm_cls, patch(_SC):
            sm = MagicMock()
            sm_cls.return_value = sm
            sm.stake.return_value = True

            fn = _get_tool_fn(mcp, "olas_stake_service")
            result = fn(service_key=SERVICE_KEY, staking_contract=ADDR_STAKING)

        assert result["status"] == "success"

    def test_stake_failed(self, mcp, mock_wallet, mock_config):
        with patch(_SM) as sm_cls, patch(_SC):
            sm = MagicMock()
            sm_cls.return_value = sm
            sm.stake.return_value = False

            fn = _get_tool_fn(mcp, "olas_stake_service")
            result = fn(service_key=SERVICE_KEY, staking_contract=ADDR_STAKING)

        assert result["status"] == "failed"


class TestOlasUnstakeService:
    def test_unstake(self, mcp, mock_wallet, mock_config):
        with patch(_SM) as sm_cls, patch(_SC):
            sm = MagicMock()
            sm_cls.return_value = sm
            sm.unstake.return_value = True

            fn = _get_tool_fn(mcp, "olas_unstake_service")
            result = fn(service_key=SERVICE_KEY)

        assert result["status"] == "success"

    def test_unstake_not_staked(self, mcp, mock_wallet):
        service = _make_service(staking_contract_address=None)
        olas_config = _make_olas_config(service)
        config = MagicMock()
        config.plugins = {"olas": olas_config.model_dump()}
        with patch("iwa.core.models.Config", return_value=config):
            fn = _get_tool_fn(mcp, "olas_unstake_service")
            result = fn(service_key=SERVICE_KEY)

        assert "error" in result
        assert "not staked" in result["error"]


class TestOlasRestakeService:
    def test_restake(self, mcp, mock_wallet, mock_config):
        from iwa.plugins.olas.contracts.staking import StakingState

        with patch(_SM) as sm_cls, patch(_SC) as sc_cls:
            sm = MagicMock()
            sm_cls.return_value = sm
            sm.unstake.return_value = True
            sm.stake.return_value = True

            sc = MagicMock()
            sc_cls.return_value = sc
            sc.get_staking_state.return_value = StakingState.EVICTED

            fn = _get_tool_fn(mcp, "olas_restake_service")
            result = fn(service_key=SERVICE_KEY)

        assert result["status"] == "success"

    def test_restake_not_evicted(self, mcp, mock_wallet, mock_config):
        from iwa.plugins.olas.contracts.staking import StakingState

        with patch(_SM) as sm_cls, patch(_SC) as sc_cls:
            sm = MagicMock()
            sm_cls.return_value = sm

            sc = MagicMock()
            sc_cls.return_value = sc
            sc.get_staking_state.return_value = StakingState.STAKED

            fn = _get_tool_fn(mcp, "olas_restake_service")
            result = fn(service_key=SERVICE_KEY)

        assert "error" in result
        assert "STAKED" in result["error"]

    def test_restake_no_contract(self, mcp, mock_wallet):
        service = _make_service(staking_contract_address=None)
        olas_config = _make_olas_config(service)
        config = MagicMock()
        config.plugins = {"olas": olas_config.model_dump()}
        with patch("iwa.core.models.Config", return_value=config):
            fn = _get_tool_fn(mcp, "olas_restake_service")
            result = fn(service_key=SERVICE_KEY)

        assert "error" in result


class TestOlasClaimRewards:
    def test_claim(self, mcp, mock_wallet, mock_config):
        with patch(_SM) as sm_cls:
            sm = MagicMock()
            sm_cls.return_value = sm
            sm.claim_rewards.return_value = (True, 1.5)

            fn = _get_tool_fn(mcp, "olas_claim_rewards")
            result = fn(service_key=SERVICE_KEY)

        assert result["status"] == "claimed"
        assert result["amount_olas"] == 1.5

    def test_claim_failed(self, mcp, mock_wallet, mock_config):
        with patch(_SM) as sm_cls:
            sm = MagicMock()
            sm_cls.return_value = sm
            sm.claim_rewards.return_value = (False, 0)

            fn = _get_tool_fn(mcp, "olas_claim_rewards")
            result = fn(service_key=SERVICE_KEY)

        # (False, 0) means no rewards available — not an error, just nothing to claim
        assert result["status"] == "nothing_to_claim"
        assert result["amount_olas"] == 0


class TestOlasCheckpoint:
    def test_checkpoint(self, mcp, mock_wallet, mock_config):
        with patch(_SM) as sm_cls, patch(_SC):
            sm = MagicMock()
            sm_cls.return_value = sm
            sm.call_checkpoint.return_value = True

            fn = _get_tool_fn(mcp, "olas_checkpoint")
            result = fn(service_key=SERVICE_KEY)

        assert result["status"] == "success"

    def test_checkpoint_not_needed(self, mcp, mock_wallet, mock_config):
        with patch(_SM) as sm_cls, patch(_SC) as sc_cls:
            sm = MagicMock()
            sm_cls.return_value = sm
            sm.call_checkpoint.return_value = False

            sc = MagicMock()
            sc_cls.return_value = sc
            sc.is_checkpoint_needed.return_value = False

            fn = _get_tool_fn(mcp, "olas_checkpoint")
            result = fn(service_key=SERVICE_KEY)

        assert result["status"] == "skipped"

    def test_checkpoint_not_staked(self, mcp, mock_wallet):
        service = _make_service(staking_contract_address=None)
        olas_config = _make_olas_config(service)
        config = MagicMock()
        config.plugins = {"olas": olas_config.model_dump()}
        with patch("iwa.core.models.Config", return_value=config):
            fn = _get_tool_fn(mcp, "olas_checkpoint")
            result = fn(service_key=SERVICE_KEY)

        assert "error" in result


# ---------------------------------------------------------------------------
# Funding tools
# ---------------------------------------------------------------------------


class TestOlasFundService:
    def test_fund_agent(self, mcp, mock_wallet, mock_config):
        mock_wallet.send.return_value = "0xabc"

        fn = _get_tool_fn(mcp, "olas_fund_service")
        result = fn(service_key=SERVICE_KEY, agent_amount_eth=1.0)

        assert result["status"] == "success"
        assert "agent" in result["funded"]
        assert result["funded"]["agent"]["tx_hash"] == "0xabc"

    def test_fund_safe(self, mcp, mock_wallet, mock_config):
        mock_wallet.send.return_value = "0xdef"

        fn = _get_tool_fn(mcp, "olas_fund_service")
        result = fn(service_key=SERVICE_KEY, safe_amount_eth=2.0)

        assert "safe" in result["funded"]

    def test_fund_both(self, mcp, mock_wallet, mock_config):
        mock_wallet.send.return_value = "0x123"

        fn = _get_tool_fn(mcp, "olas_fund_service")
        result = fn(service_key=SERVICE_KEY, agent_amount_eth=1.0, safe_amount_eth=2.0)

        assert "agent" in result["funded"]
        assert "safe" in result["funded"]

    def test_fund_zero_amounts(self, mcp, mock_wallet, mock_config):
        fn = _get_tool_fn(mcp, "olas_fund_service")
        result = fn(service_key=SERVICE_KEY)

        assert "error" in result


class TestOlasDrainService:
    def test_drain(self, mcp, mock_wallet, mock_config):
        with patch(_SM) as sm_cls:
            sm = MagicMock()
            sm_cls.return_value = sm
            sm.drain_service.return_value = {"agent": "0.5 xDAI", "safe": "1.2 xDAI"}

            fn = _get_tool_fn(mcp, "olas_drain_service")
            result = fn(service_key=SERVICE_KEY)

        assert result["status"] == "success"
        assert "agent" in result["drained"]

    def test_drain_empty(self, mcp, mock_wallet, mock_config):
        with patch(_SM) as sm_cls:
            sm = MagicMock()
            sm_cls.return_value = sm
            sm.drain_service.return_value = None

            fn = _get_tool_fn(mcp, "olas_drain_service")
            result = fn(service_key=SERVICE_KEY)

        assert "error" in result


# ---------------------------------------------------------------------------
# Info tools
# ---------------------------------------------------------------------------


class TestOlasGetPrice:
    def test_get_price(self, mcp):
        with patch(_PRICE_SVC) as ps_cls:
            ps = MagicMock()
            ps_cls.return_value = ps
            ps.get_token_price.return_value = 1.42

            fn = _get_tool_fn(mcp, "olas_get_price")
            result = fn()

        assert result["price_eur"] == 1.42
        assert result["symbol"] == "OLAS"

    def test_get_price_error(self, mcp):
        with patch(_PRICE_SVC, side_effect=Exception("API down")):
            fn = _get_tool_fn(mcp, "olas_get_price")
            result = fn()

        assert result["price_eur"] is None
        assert "error" in result


# ---------------------------------------------------------------------------
# Integration: plugin registration
# ---------------------------------------------------------------------------


class TestOlasPluginMcpRegistration:
    def test_plugin_registers_tools(self):
        from iwa.plugins.olas.plugin import OlasPlugin

        mcp = FastMCP("test-plugin")
        plugin = OlasPlugin()
        plugin.register_mcp_tools(mcp)

        tools = asyncio.run(mcp.list_tools())
        tool_names = {t.name for t in tools}

        assert "olas_list_services" in tool_names
        assert "olas_create_service" in tool_names
        assert "olas_stake_service" in tool_names
        assert "olas_fund_service" in tool_names
        assert "olas_get_price" in tool_names
        assert len(tool_names) == 17


class TestServerPluginDiscovery:
    def test_server_includes_olas_tools(self, mock_wallet):
        from iwa.mcp.server import create_mcp_server

        server = create_mcp_server()
        tools = asyncio.run(server.list_tools())
        tool_names = {t.name for t in tools}

        # Core tools
        assert "list_accounts" in tool_names
        assert "send" in tool_names
        # Olas tools
        assert "olas_list_services" in tool_names
        assert "olas_claim_rewards" in tool_names
