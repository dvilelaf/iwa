"""Tests for staking.py router coverage."""

import sys
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def mock_dependencies():
    """Mock wallet dependency before importing router modules.

    The iwa.web.dependencies module instantiates Wallet() at module level,
    which fails in test environment. We pre-populate sys.modules to prevent
    the actual import.
    """
    # Create mock module
    mock_dep_module = MagicMock()
    mock_dep_module.wallet = MagicMock()

    # Pre-populate sys.modules to prevent real import
    with patch.dict(sys.modules, {"iwa.web.dependencies": mock_dep_module}):
        yield


def test_check_availability_exception():
    """Test _check_availability handles contract call failures."""
    from iwa.web.routers.olas.staking import _check_availability

    mock_interface = MagicMock()
    mock_interface.chain.name = "gnosis"

    with patch("iwa.plugins.olas.contracts.staking.StakingContract") as mock_contract_cls:
        mock_contract_cls.side_effect = Exception("Contract error")
        result = _check_availability("Test", "0xAddr", mock_interface)

    assert result["name"] == "Test"
    assert result["usage"] is None


def test_filter_contracts_no_availability():
    """Test _filter_contracts excludes unavailable contracts."""
    from iwa.web.routers.olas.staking import _filter_contracts

    results = [
        {"name": "A", "usage": {"available": False}, "min_staking_deposit": 100},
        {"name": "B", "usage": {"available": True}, "min_staking_deposit": 100},
    ]
    filtered = _filter_contracts(results, None, None)
    assert len(filtered) == 1
    assert filtered[0]["name"] == "B"


def test_filter_contracts_bond_too_low():
    """Test _filter_contracts excludes contracts where bond is too low."""
    from iwa.web.routers.olas.staking import _filter_contracts

    results = [
        {"name": "A", "usage": {"available": True}, "min_staking_deposit": 1000},
    ]
    filtered = _filter_contracts(results, service_bond=500, service_token=None)
    assert len(filtered) == 0


def test_filter_contracts_token_mismatch():
    """Test _filter_contracts excludes contracts with wrong token."""
    from iwa.web.routers.olas.staking import _filter_contracts

    results = [
        {
            "name": "A",
            "usage": {"available": True},
            "min_staking_deposit": 100,
            "staking_token": "0xOtherToken",
        },
    ]
    filtered = _filter_contracts(results, service_bond=500, service_token="0xmytoken")
    assert len(filtered) == 0


def test_filter_contracts_compatible():
    """Test _filter_contracts includes compatible contracts."""
    from iwa.web.routers.olas.staking import _filter_contracts

    results = [
        {
            "name": "A",
            "usage": {"available": True},
            "min_staking_deposit": 100,
            "staking_token": "0xMyToken",
        },
    ]
    filtered = _filter_contracts(results, service_bond=500, service_token="0xmytoken")
    assert len(filtered) == 1
