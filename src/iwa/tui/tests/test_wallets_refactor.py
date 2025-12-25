"""Tests for Wallets Refactor."""

from unittest.mock import MagicMock, patch

import pytest

from iwa.tui.screens.wallets import WalletsScreen


@pytest.fixture
def mock_wallet():
    """Mock wallet."""
    return MagicMock()


def test_wallets_screen_initialization(mock_wallet):
    """Test that WalletsScreen can be initialized with the new import structure."""
    with patch("iwa.core.chain.ChainInterfaces"):
        # Mock MonitorWorker import if needed, but it should be imported from workers.py now
        screen = WalletsScreen(wallet=mock_wallet)
        assert screen is not None
        assert hasattr(screen, "monitor_worker") or hasattr(screen, "start_monitor")


def test_monitor_worker_integration():
    """Test that MonitorWorker is imported from the correct location."""
    from iwa.tui.screens.wallets import MonitorWorker as WalletsMonitorWorker
    from iwa.tui.workers import MonitorWorker as DefinedMonitorWorker

    assert WalletsMonitorWorker is DefinedMonitorWorker
