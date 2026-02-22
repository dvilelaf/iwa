"""Tests for the subgraph router — covers chain switching, graceful error handling,
and verifying that response data changes when querying different chains."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from iwa.plugins.olas.subgraph.models import (
    SubgraphCheckpoint,
    SubgraphDailyStakingTrend,
    SubgraphStakingContract,
    SubgraphStakingEvent,
    SubgraphTokenHolder,
    SubgraphTokenInfo,
    SubgraphTransfer,
)

# Mock Wallet and ChainInterfaces BEFORE importing app
with (
    patch("iwa.core.wallet.Wallet"),
    patch("iwa.core.chain.ChainInterfaces"),
    patch("iwa.core.wallet.init_db"),
    patch("iwa.web.dependencies._get_webui_password", return_value=None),
):
    from iwa.web.dependencies import verify_auth
    from iwa.web.server import app


async def override_verify_auth():
    return True


app.dependency_overrides[verify_auth] = override_verify_auth


@pytest.fixture(scope="module")
def client():
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def clear_subgraph_cache():
    """Clear the response cache and SubgraphClient singleton before each test."""
    from iwa.web.cache import response_cache
    from iwa.web.routers import subgraph as subgraph_module

    response_cache.invalidate()
    subgraph_module._client = None
    yield
    response_cache.invalidate()
    subgraph_module._client = None


# ── Helpers ──────────────────────────────────────────────────────


def _make_token_info(balance_wei: int, holder_count: int) -> SubgraphTokenInfo:
    return SubgraphTokenInfo(
        token_id="olas", balance=balance_wei, holder_count=holder_count
    )


def _make_holder(address: str, balance_wei: int) -> SubgraphTokenHolder:
    return SubgraphTokenHolder(address=address, balance=balance_wei)


def _make_transfer(
    from_addr: str, to_addr: str, value_wei: int
) -> SubgraphTransfer:
    return SubgraphTransfer(
        from_address=from_addr,
        to_address=to_addr,
        value=value_wei,
        block_number=100,
        block_timestamp="1735689600",  # 2025-01-01 as Unix timestamp string
        transaction_hash="0xabc",
    )


def _make_staking_contract(address: str) -> SubgraphStakingContract:
    return SubgraphStakingContract(
        address=address,
        max_num_services=50,
        rewards_per_second=1_000_000_000,
        min_staking_deposit=10_000 * 10**18,
        min_staking_duration=86400,
        liveness_period=3600,
        num_agent_instances=1,
        agent_ids=[25],
        threshold=1,
        activity_checker="0xchecker",
        max_num_inactivity_periods=3,
        time_for_emissions=2592000,
        chain="gnosis",
    )


def _make_checkpoint(epoch: int, contract: str) -> SubgraphCheckpoint:
    return SubgraphCheckpoint(
        epoch=epoch,
        available_rewards=5 * 10**18,
        service_ids=[42],
        rewards=[1 * 10**18],
        epoch_length=86400,
        block_number=1000,
        block_timestamp="1735689600",
        transaction_hash="0xtx",
        contract_address=contract,
    )


def _make_event(event_type: str, service_id: int) -> SubgraphStakingEvent:
    return SubgraphStakingEvent(
        event_type=event_type,
        epoch=1,
        service_id=service_id,
        block_timestamp="1735689600",
        transaction_hash="0xtx",
    )


def _make_trend(num_services: int) -> SubgraphDailyStakingTrend:
    return SubgraphDailyStakingTrend(
        timestamp="1735689600",
        num_services=num_services,
        total_rewards=100 * 10**18,
        median_cumulative_rewards=50 * 10**18,
    )


# ── Tokenomics endpoint tests ───────────────────────────────────


class TestTokenomicsEndpoint:
    """Test /api/subgraph/tokenomics returns correct data per chain."""

    def test_tokenomics_gnosis(self, client):
        """Tokenomics for gnosis returns gnosis-specific data."""
        gnosis_data = {
            "token_info": _make_token_info(347_501 * 10**18, 500),
            "top_holders": [_make_holder("0xAAA", 100_000 * 10**18)],
            "recent_transfers": [
                _make_transfer("0xBBB", "0xCCC", 50 * 10**18)
            ],
        }
        mock_tokenomics = MagicMock()
        mock_tokenomics.get_all_data.return_value = gnosis_data
        mock_client = MagicMock()
        mock_client.tokenomics = mock_tokenomics

        with patch(
            "iwa.web.routers.subgraph._get_client", return_value=mock_client
        ):
            resp = client.get("/api/subgraph/tokenomics?chain=gnosis")

        assert resp.status_code == 200
        data = resp.json()
        assert data["chain"] == "gnosis"
        assert data["token_info"]["balance"] == 347_501.0
        assert data["token_info"]["holder_count"] == 500
        assert len(data["top_holders"]) == 1
        assert data["top_holders"][0]["address"] == "0xAAA"
        assert data["top_holders"][0]["balance"] == 100_000.0
        assert len(data["recent_transfers"]) == 1
        assert data["recent_transfers"][0]["from"] == "0xBBB"
        assert data["recent_transfers"][0]["to"] == "0xCCC"
        assert data["recent_transfers"][0]["value"] == 50.0
        assert data["recent_transfers"][0]["transaction_hash"] == "0xabc"

    def test_tokenomics_ethereum(self, client):
        """Tokenomics for ethereum returns different data from gnosis."""
        eth_data = {
            "token_info": _make_token_info(527_849_155 * 10**18, 20_000),
            "top_holders": [
                _make_holder("0xETH1", 200_000_000 * 10**18),
                _make_holder("0xETH2", 100_000_000 * 10**18),
            ],
            "recent_transfers": [],  # ethereum may have no transfers field
        }
        mock_tokenomics = MagicMock()
        mock_tokenomics.get_all_data.return_value = eth_data
        mock_client = MagicMock()
        mock_client.tokenomics = mock_tokenomics

        with patch(
            "iwa.web.routers.subgraph._get_client", return_value=mock_client
        ):
            resp = client.get("/api/subgraph/tokenomics?chain=ethereum")

        assert resp.status_code == 200
        data = resp.json()
        assert data["chain"] == "ethereum"
        assert data["token_info"]["balance"] == 527_849_155.0
        assert data["token_info"]["holder_count"] == 20_000
        assert len(data["top_holders"]) == 2
        assert data["recent_transfers"] == []

    def test_tokenomics_chain_switching_returns_different_data(self, client):
        """Switching chain must return different data — not cached stale data."""
        gnosis_data = {
            "token_info": _make_token_info(347_501 * 10**18, 500),
            "top_holders": [_make_holder("0xGNO", 100 * 10**18)],
            "recent_transfers": [],
        }
        eth_data = {
            "token_info": _make_token_info(527_849_155 * 10**18, 20_000),
            "top_holders": [_make_holder("0xETH", 999 * 10**18)],
            "recent_transfers": [],
        }
        mock_tokenomics = MagicMock()
        mock_tokenomics.get_all_data.side_effect = (
            lambda chain: gnosis_data if chain == "gnosis" else eth_data
        )
        mock_client = MagicMock()
        mock_client.tokenomics = mock_tokenomics

        with patch(
            "iwa.web.routers.subgraph._get_client", return_value=mock_client
        ):
            resp_gno = client.get("/api/subgraph/tokenomics?chain=gnosis")
            resp_eth = client.get("/api/subgraph/tokenomics?chain=ethereum")

        gno = resp_gno.json()
        eth = resp_eth.json()
        assert gno["chain"] == "gnosis"
        assert eth["chain"] == "ethereum"
        assert gno["token_info"]["balance"] != eth["token_info"]["balance"]
        assert gno["top_holders"][0]["address"] == "0xGNO"
        assert eth["top_holders"][0]["address"] == "0xETH"

    def test_tokenomics_unsupported_chain_returns_empty(self, client):
        """Unsupported chain returns empty data, not 500."""
        mock_tokenomics = MagicMock()
        mock_tokenomics.get_all_data.side_effect = ValueError(
            "No Tokenomics endpoint for chain 'solana'"
        )
        mock_client = MagicMock()
        mock_client.tokenomics = mock_tokenomics

        with patch(
            "iwa.web.routers.subgraph._get_client", return_value=mock_client
        ):
            resp = client.get("/api/subgraph/tokenomics?chain=solana")

        assert resp.status_code == 200
        data = resp.json()
        assert data["chain"] == "solana"
        assert data["token_info"] is None
        assert data["top_holders"] == []
        assert data["recent_transfers"] == []

    def test_tokenomics_no_token_info(self, client):
        """Chain with no token data returns null token_info but valid structure."""
        data = {
            "token_info": None,
            "top_holders": [],
            "recent_transfers": [],
        }
        mock_tokenomics = MagicMock()
        mock_tokenomics.get_all_data.return_value = data
        mock_client = MagicMock()
        mock_client.tokenomics = mock_tokenomics

        with patch(
            "iwa.web.routers.subgraph._get_client", return_value=mock_client
        ):
            resp = client.get("/api/subgraph/tokenomics?chain=base")

        assert resp.status_code == 200
        result = resp.json()
        assert result["token_info"] is None
        assert result["top_holders"] == []


# ── Staking endpoints — unsupported chain handling ───────────────


class TestStakingUnsupportedChains:
    """Staking endpoints must return 200 with empty data for unsupported chains."""

    def _mock_client_with_valueerror(self, method_name):
        mock_staking = MagicMock()
        getattr(mock_staking, method_name).side_effect = ValueError(
            "No Staking endpoint for chain 'ethereum'"
        )
        mock_client = MagicMock()
        mock_client.staking = mock_staking
        return mock_client

    def test_staking_unsupported_chain(self, client):
        mock_client = self._mock_client_with_valueerror("get_all_contracts")
        with patch(
            "iwa.web.routers.subgraph._get_client", return_value=mock_client
        ):
            resp = client.get("/api/subgraph/staking?chain=ethereum")
        assert resp.status_code == 200
        data = resp.json()
        assert data["chain"] == "ethereum"
        assert data["count"] == 0
        assert data["contracts"] == []

    def test_checkpoints_unsupported_chain(self, client):
        mock_client = self._mock_client_with_valueerror("get_checkpoints")
        with patch(
            "iwa.web.routers.subgraph._get_client", return_value=mock_client
        ):
            resp = client.get(
                "/api/subgraph/staking/checkpoints?chain=ethereum"
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["chain"] == "ethereum"
        assert data["count"] == 0
        assert data["checkpoints"] == []

    def test_events_unsupported_chain(self, client):
        mock_client = self._mock_client_with_valueerror("get_recent_events")
        with patch(
            "iwa.web.routers.subgraph._get_client", return_value=mock_client
        ):
            resp = client.get("/api/subgraph/staking/events?chain=ethereum")
        assert resp.status_code == 200
        data = resp.json()
        assert data["chain"] == "ethereum"
        assert data["count"] == 0
        assert data["events"] == []

    def test_daily_unsupported_chain(self, client):
        mock_client = self._mock_client_with_valueerror("get_daily_trends")
        with patch(
            "iwa.web.routers.subgraph._get_client", return_value=mock_client
        ):
            resp = client.get("/api/subgraph/staking/daily?chain=ethereum")
        assert resp.status_code == 200
        data = resp.json()
        assert data["chain"] == "ethereum"
        assert data["count"] == 0
        assert data["trends"] == []


# ── Staking endpoints — supported chain with data ────────────────


class TestStakingWithData:
    """Staking endpoints return proper data for supported chains."""

    def test_staking_contracts(self, client):
        mock_staking = MagicMock()
        mock_staking.get_all_contracts.return_value = [
            _make_staking_contract("0xContract1")
        ]
        mock_client = MagicMock()
        mock_client.staking = mock_staking

        with patch(
            "iwa.web.routers.subgraph._get_client", return_value=mock_client
        ):
            resp = client.get("/api/subgraph/staking?chain=gnosis")

        assert resp.status_code == 200
        data = resp.json()
        assert data["chain"] == "gnosis"
        assert data["count"] == 1
        assert data["contracts"][0]["address"] == "0xContract1"

    def test_checkpoints(self, client):
        mock_staking = MagicMock()
        mock_staking.get_checkpoints.return_value = [
            _make_checkpoint(10, "0xStaking1"),
            _make_checkpoint(11, "0xStaking2"),
        ]
        mock_client = MagicMock()
        mock_client.staking = mock_staking

        with patch(
            "iwa.web.routers.subgraph._get_client", return_value=mock_client
        ):
            resp = client.get(
                "/api/subgraph/staking/checkpoints?chain=gnosis"
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 2
        assert data["checkpoints"][0]["epoch"] == 10
        assert data["checkpoints"][0]["contract_address"] == "0xStaking1"
        assert data["checkpoints"][1]["contract_address"] == "0xStaking2"

    def test_events(self, client):
        mock_staking = MagicMock()
        mock_staking.get_recent_events.return_value = [
            _make_event("staked", 42),
            _make_event("unstaked", 43),
        ]
        mock_client = MagicMock()
        mock_client.staking = mock_staking

        with patch(
            "iwa.web.routers.subgraph._get_client", return_value=mock_client
        ):
            resp = client.get("/api/subgraph/staking/events?chain=gnosis")

        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 2
        assert data["events"][0]["event_type"] == "staked"
        assert data["events"][0]["service_id"] == 42
        assert data["events"][1]["event_type"] == "unstaked"

    def test_daily_trends(self, client):
        mock_staking = MagicMock()
        mock_staking.get_daily_trends.return_value = [_make_trend(15)]
        mock_client = MagicMock()
        mock_client.staking = mock_staking

        with patch(
            "iwa.web.routers.subgraph._get_client", return_value=mock_client
        ):
            resp = client.get("/api/subgraph/staking/daily?chain=gnosis")

        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert data["trends"][0]["num_services"] == 15
        assert data["trends"][0]["total_rewards"] == 100.0


# ── Chain switching tests — data must differ per chain ───────────


class TestChainSwitchingDataDiffers:
    """Verify that querying different chains returns different data."""

    def test_staking_chain_switch(self, client):
        """Staking data for gnosis vs unsupported ethereum differs."""
        gnosis_contracts = [_make_staking_contract("0xGnoStaking")]
        mock_staking = MagicMock()
        mock_staking.get_all_contracts.side_effect = (
            lambda chain, **kw: gnosis_contracts
            if chain == "gnosis"
            else (_ for _ in ()).throw(ValueError("No endpoint"))
        )
        mock_client = MagicMock()
        mock_client.staking = mock_staking

        with patch(
            "iwa.web.routers.subgraph._get_client", return_value=mock_client
        ):
            resp_gno = client.get("/api/subgraph/staking?chain=gnosis")
            resp_eth = client.get("/api/subgraph/staking?chain=ethereum")

        assert resp_gno.status_code == 200
        assert resp_eth.status_code == 200
        assert resp_gno.json()["count"] == 1
        assert resp_eth.json()["count"] == 0

    def test_checkpoints_chain_switch(self, client):
        """Checkpoints for gnosis vs polygon show different data."""
        gno_cp = [_make_checkpoint(10, "0xGnoContract")]
        pol_cp = [
            _make_checkpoint(20, "0xPolContract1"),
            _make_checkpoint(21, "0xPolContract2"),
        ]
        mock_staking = MagicMock()
        mock_staking.get_checkpoints.side_effect = (
            lambda chain, **kw: gno_cp if chain == "gnosis" else pol_cp
        )
        mock_client = MagicMock()
        mock_client.staking = mock_staking

        with patch(
            "iwa.web.routers.subgraph._get_client", return_value=mock_client
        ):
            resp_gno = client.get(
                "/api/subgraph/staking/checkpoints?chain=gnosis"
            )
            resp_pol = client.get(
                "/api/subgraph/staking/checkpoints?chain=polygon"
            )

        gno = resp_gno.json()
        pol = resp_pol.json()
        assert gno["chain"] == "gnosis"
        assert pol["chain"] == "polygon"
        assert gno["count"] == 1
        assert pol["count"] == 2
        assert (
            gno["checkpoints"][0]["contract_address"]
            != pol["checkpoints"][0]["contract_address"]
        )


# ── Response JSON schema validation ─────────────────────────────


class TestResponseSchema:
    """Verify response JSON has the exact keys the frontend expects."""

    def test_tokenomics_response_keys(self, client):
        """Frontend expects: chain, token_info, top_holders, recent_transfers."""
        data = {
            "token_info": _make_token_info(1000 * 10**18, 10),
            "top_holders": [_make_holder("0xA", 500 * 10**18)],
            "recent_transfers": [_make_transfer("0xB", "0xC", 10 * 10**18)],
        }
        mock_tokenomics = MagicMock()
        mock_tokenomics.get_all_data.return_value = data
        mock_client = MagicMock()
        mock_client.tokenomics = mock_tokenomics

        with patch(
            "iwa.web.routers.subgraph._get_client", return_value=mock_client
        ):
            resp = client.get("/api/subgraph/tokenomics?chain=gnosis")

        result = resp.json()
        # Top-level keys
        assert set(result.keys()) == {
            "chain",
            "token_info",
            "top_holders",
            "recent_transfers",
        }
        # token_info keys
        assert set(result["token_info"].keys()) == {"balance", "holder_count"}
        # holder keys
        assert set(result["top_holders"][0].keys()) == {"address", "balance"}
        # transfer keys
        assert set(result["recent_transfers"][0].keys()) == {
            "from",
            "to",
            "value",
            "block_number",
            "timestamp",
            "transaction_hash",
        }

    def test_staking_events_response_keys(self, client):
        """Frontend expects: chain, count, events with specific fields."""
        mock_staking = MagicMock()
        mock_staking.get_recent_events.return_value = [
            _make_event("staked", 42)
        ]
        mock_client = MagicMock()
        mock_client.staking = mock_staking

        with patch(
            "iwa.web.routers.subgraph._get_client", return_value=mock_client
        ):
            resp = client.get("/api/subgraph/staking/events?chain=gnosis")

        result = resp.json()
        assert set(result.keys()) == {"chain", "count", "events"}
        event = result["events"][0]
        assert "event_type" in event
        assert "timestamp" in event
        assert "transaction_hash" in event

    def test_checkpoints_response_keys(self, client):
        """Frontend expects contract_address in checkpoints."""
        mock_staking = MagicMock()
        mock_staking.get_checkpoints.return_value = [
            _make_checkpoint(5, "0xC1")
        ]
        mock_client = MagicMock()
        mock_client.staking = mock_staking

        with patch(
            "iwa.web.routers.subgraph._get_client", return_value=mock_client
        ):
            resp = client.get(
                "/api/subgraph/staking/checkpoints?chain=gnosis"
            )

        cp = resp.json()["checkpoints"][0]
        assert "contract_address" in cp
        assert "epoch" in cp
        assert "timestamp" in cp
        assert "available_rewards" in cp
