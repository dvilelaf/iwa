"""Tests for staking contract config vs on-chain mismatch detection."""

from unittest.mock import MagicMock, patch

import pytest

from iwa.plugins.olas.contracts.staking import StakingState
from iwa.plugins.olas.models import Service
from iwa.plugins.olas.service_manager import ServiceManager

ADDR_CONFIG = "0x78731D3Ca6b7E34aC0F824c42a7cC18A495cabaB"
ADDR_ACTUAL = "0x1111111111111111111111111111111111111111"
ADDR_OTHER = "0x2222222222222222222222222222222222222222"

KNOWN_CONTRACTS = {
    "gnosis": {
        "Contract A": ADDR_CONFIG,
        "Contract B": ADDR_ACTUAL,
        "Contract C": ADDR_OTHER,
    }
}


@pytest.fixture
def mock_wallet():
    """Mock wallet for ServiceManager."""
    w = MagicMock()
    w.master_account.address = ADDR_CONFIG
    w.key_storage = MagicMock()
    w.key_storage._password = "pass"
    w.account_service = MagicMock()
    return w


def _make_sm(mock_wallet, **service_kwargs):
    """Helper to create a ServiceManager with a mocked service."""
    defaults = {
        "service_name": "test_trader",
        "chain_name": "gnosis",
        "service_id": 42,
        "staking_contract_address": ADDR_CONFIG,
    }
    defaults.update(service_kwargs)
    with (
        patch("iwa.core.models.Config"),
        patch("iwa.plugins.olas.service_manager.base.ContractCache") as mock_cache,
        patch("iwa.plugins.olas.service_manager.staking.ContractCache", mock_cache),
    ):
        mock_cache.return_value.get_contract.side_effect = lambda cls, *a, **k: cls(*a, **k)
        sm = ServiceManager(mock_wallet)
        sm.service = Service(**defaults)
        return sm


class TestDetectStakingMismatch:
    """Tests for _detect_staking_mismatch method."""

    @patch(
        "iwa.plugins.olas.service_manager.staking.ContractCache",
    )
    @patch(
        "iwa.plugins.olas.constants.OLAS_TRADER_STAKING_CONTRACTS",
        KNOWN_CONTRACTS,
    )
    def test_mismatch_detected_staked_elsewhere(self, mock_cache_cls, mock_wallet):
        """Service is STAKED in a different contract than configured."""
        sm = _make_sm(mock_wallet)

        mock_contract = MagicMock()
        mock_contract.get_staking_state.return_value = StakingState.STAKED
        mock_cache_cls.return_value.get_contract.return_value = mock_contract

        result = sm._detect_staking_mismatch(42, ADDR_CONFIG)

        assert result["config_mismatch"] is True
        assert str(result["actual_staking_contract_address"]).lower() == ADDR_ACTUAL.lower()
        assert "42" in result["config_mismatch_detail"]
        assert "STAKED" in result["config_mismatch_detail"]

    @patch(
        "iwa.plugins.olas.service_manager.staking.ContractCache",
    )
    @patch(
        "iwa.plugins.olas.constants.OLAS_TRADER_STAKING_CONTRACTS",
        KNOWN_CONTRACTS,
    )
    def test_mismatch_detected_evicted_elsewhere(self, mock_cache_cls, mock_wallet):
        """Service is EVICTED in a different contract than configured."""
        sm = _make_sm(mock_wallet)

        mock_contract = MagicMock()
        mock_contract.get_staking_state.return_value = StakingState.EVICTED
        mock_cache_cls.return_value.get_contract.return_value = mock_contract

        result = sm._detect_staking_mismatch(42, ADDR_CONFIG)

        assert result["config_mismatch"] is True
        assert "EVICTED" in result["config_mismatch_detail"]

    @patch(
        "iwa.plugins.olas.service_manager.staking.ContractCache",
    )
    @patch(
        "iwa.plugins.olas.constants.OLAS_TRADER_STAKING_CONTRACTS",
        KNOWN_CONTRACTS,
    )
    def test_no_mismatch_not_found_anywhere(self, mock_cache_cls, mock_wallet):
        """Service is NOT_STAKED in all known contracts — no mismatch."""
        sm = _make_sm(mock_wallet)

        mock_contract = MagicMock()
        mock_contract.get_staking_state.return_value = StakingState.NOT_STAKED
        mock_cache_cls.return_value.get_contract.return_value = mock_contract

        result = sm._detect_staking_mismatch(42, ADDR_CONFIG)

        assert result == {}

    @patch(
        "iwa.plugins.olas.service_manager.staking.ContractCache",
    )
    @patch(
        "iwa.plugins.olas.constants.OLAS_TRADER_STAKING_CONTRACTS",
        KNOWN_CONTRACTS,
    )
    def test_rpc_error_skips_contract(self, mock_cache_cls, mock_wallet):
        """RPC error when checking a contract should not crash, just skip."""
        sm = _make_sm(mock_wallet)

        mock_cache_cls.return_value.get_contract.side_effect = Exception("RPC timeout")

        result = sm._detect_staking_mismatch(42, ADDR_CONFIG)

        assert result == {}

    @patch(
        "iwa.plugins.olas.constants.OLAS_TRADER_STAKING_CONTRACTS",
        {},
    )
    def test_no_known_contracts_for_chain(self, mock_wallet):
        """No known contracts for the chain — returns empty dict."""
        sm = _make_sm(mock_wallet)

        result = sm._detect_staking_mismatch(42, ADDR_CONFIG)

        assert result == {}

    @patch(
        "iwa.plugins.olas.constants.OLAS_TRADER_STAKING_CONTRACTS",
        {"gnosis": {}},
    )
    def test_empty_contracts_for_chain(self, mock_wallet):
        """Empty contracts dict for the chain — returns empty dict."""
        sm = _make_sm(mock_wallet)

        result = sm._detect_staking_mismatch(42, ADDR_CONFIG)

        assert result == {}

    @patch(
        "iwa.plugins.olas.service_manager.staking.ContractCache",
    )
    @patch(
        "iwa.plugins.olas.constants.OLAS_TRADER_STAKING_CONTRACTS",
        KNOWN_CONTRACTS,
    )
    def test_skips_configured_contract(self, mock_cache_cls, mock_wallet):
        """Should skip the configured contract address (already checked by caller)."""
        sm = _make_sm(mock_wallet)

        call_count = 0

        def mock_get_contract(cls, addr, **kw):
            nonlocal call_count
            call_count += 1
            # Should never be called for ADDR_CONFIG
            assert str(addr).lower() != ADDR_CONFIG.lower()
            mock = MagicMock()
            mock.get_staking_state.return_value = StakingState.NOT_STAKED
            return mock

        mock_cache_cls.return_value.get_contract.side_effect = mock_get_contract

        sm._detect_staking_mismatch(42, ADDR_CONFIG)

        # Should have checked Contract B and Contract C, but not Contract A
        assert call_count == 2


class TestFetchStakingStatusMismatch:
    """Test that _fetch_staking_status_impl includes mismatch data."""

    @patch(
        "iwa.plugins.olas.service_manager.staking.ContractCache",
    )
    @patch(
        "iwa.plugins.olas.constants.OLAS_TRADER_STAKING_CONTRACTS",
        KNOWN_CONTRACTS,
    )
    def test_status_includes_mismatch_when_not_staked(self, mock_cache_cls, mock_wallet):
        """When service is NOT_STAKED in config contract but STAKED elsewhere."""
        sm = _make_sm(mock_wallet)

        # Mock the configured contract returning NOT_STAKED
        mock_config_contract = MagicMock()
        mock_config_contract.get_staking_state.return_value = StakingState.NOT_STAKED
        mock_config_contract.activity_checker_address = ADDR_OTHER
        mock_config_contract.activity_checker.liveness_ratio = 1000

        # Mock the actual contract returning STAKED
        mock_actual_contract = MagicMock()
        mock_actual_contract.get_staking_state.return_value = StakingState.STAKED

        def get_contract(cls, addr, **kw):
            if str(addr).lower() == ADDR_CONFIG.lower():
                return mock_config_contract
            return mock_actual_contract

        mock_cache_cls.return_value.get_contract.side_effect = get_contract

        status = sm._fetch_staking_status_impl()

        assert status is not None
        assert status.is_staked is False
        assert status.config_mismatch is True
        assert status.actual_staking_contract_address is not None
        assert status.config_mismatch_detail is not None
