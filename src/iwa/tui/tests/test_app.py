"""Tests for TUI App."""

import importlib
import sys
from unittest.mock import MagicMock, patch

import pytest


# Fixture to mock dependencies
@pytest.fixture
def mock_dependencies():
    """Mock app dependencies."""
    # Start patches for Textual widgets at source to persist through reload
    patch_header = patch("textual.widgets.Header")
    patch_footer = patch("textual.widgets.Footer")
    patch_tabbed = patch("textual.widgets.TabbedContent")
    patch_pane = patch("textual.widgets.TabPane")

    mock_header = patch_header.start()
    mock_footer = patch_footer.start()
    mock_tabbed = patch_tabbed.start()
    mock_pane = patch_pane.start()

    # Setup TabbedContent and TabPane as context managers
    mock_tabbed.return_value.__enter__.return_value = MagicMock()
    mock_pane.return_value.__enter__.return_value = MagicMock()

    with (
        patch("iwa.core.wallet.Wallet") as mock_wallet,
        patch("iwa.tui.rpc.RPCView") as mock_rpc_view,
        patch("iwa.tui.screens.wallets.WalletsScreen") as mock_wallets_screen,
        patch("loguru.logger") as mock_global_logger,
    ):
        mock_wallet_instance = mock_wallet.return_value
        mock_plugin = MagicMock()
        mock_plugin.name = "Olas"
        mock_plugin.get_tui_view.return_value = MagicMock()

        mock_wallet_instance.plugin_service.get_all_plugins.return_value = {"olas": mock_plugin}

        yield {
            "wallet": mock_wallet,
            "rpc_view": mock_rpc_view,
            "wallets_screen": mock_wallets_screen,
            "logger": mock_global_logger,
            "widgets": [mock_header, mock_footer, mock_tabbed, mock_pane],
        }

    # Stop global patches after the test yields
    patch_header.stop()
    patch_footer.stop()
    patch_tabbed.stop()
    patch_pane.stop()


@pytest.fixture
def iwa_app_cls(mock_dependencies):
    """Fixture to reload and return IwaApp class."""
    if "iwa.tui.app" in sys.modules:
        importlib.reload(sys.modules["iwa.tui.app"])
    else:
        importlib.import_module("iwa.tui.app")
    return sys.modules["iwa.tui.app"].IwaApp


def test_init(iwa_app_cls, mock_dependencies):
    """Test app initialization."""
    app = iwa_app_cls()
    assert app.wallet is not None
    assert "olas" in app.plugins
    mock_dependencies["logger"].add.assert_called()


def test_compose_runs(iwa_app_cls, mock_dependencies):
    """Test compose method runs."""
    app = iwa_app_cls()

    # Run compose
    widgets = list(app.compose())

    assert len(widgets) > 0
    mock_dependencies["wallets_screen"].assert_called()
    mock_dependencies["rpc_view"].assert_called()


def test_action_refresh(iwa_app_cls, mock_dependencies):
    """Test refresh action."""
    app = iwa_app_cls()

    mock_screen = MagicMock()
    app.query_one = MagicMock(return_value=mock_screen)

    app.action_refresh()

    app.query_one.assert_called()
    mock_screen.refresh_accounts.assert_called_once()


def test_action_refresh_error(iwa_app_cls, mock_dependencies):
    """Test refresh action error handling."""
    app = iwa_app_cls()
    app.query_one = MagicMock(side_effect=Exception("No screen"))
    app.action_refresh()


def test_copy_to_clipboard(iwa_app_cls, mock_dependencies):
    """Test copy to clipboard."""
    app = iwa_app_cls()

    with patch.dict(sys.modules, {"pyperclip": MagicMock()}):
        app.copy_to_clipboard("test")
        sys.modules["pyperclip"].copy.assert_called_with("test")  # type: ignore


def test_copy_to_clipboard_error(iwa_app_cls, mock_dependencies):
    """Test copy to clipboard error."""
    app = iwa_app_cls()

    mock_pyperclip = MagicMock()
    mock_pyperclip.copy.side_effect = Exception("Copy fail")

    with patch.dict(sys.modules, {"pyperclip": mock_pyperclip}):
        app.copy_to_clipboard("test")
        mock_dependencies["logger"].error.assert_called()
