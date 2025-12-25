"""Tests for RPC view."""

import importlib
import sys
from unittest.mock import MagicMock, PropertyMock, patch

import pytest


# Mock textual's work decorator to run synchronously or just return the function
@pytest.fixture(autouse=True)
def mock_work_decorator():
    """Mock textual work decorator."""

    # Patch textual.work before import/reload
    def decorator(*args, **kwargs):
        if args and callable(args[0]):
            return args[0]

        def real_decorator(func):
            return func

        return real_decorator

    with patch("textual.work", side_effect=decorator):
        yield


@pytest.fixture
def rpc_view_cls(mock_chain_interfaces):
    """Fixture to reload and return RPCView class."""
    if "iwa.tui.rpc" in sys.modules:
        importlib.reload(sys.modules["iwa.tui.rpc"])
    else:
        importlib.import_module("iwa.tui.rpc")
    return sys.modules["iwa.tui.rpc"].RPCView


@pytest.fixture
def mock_chain_interfaces():
    """Mock ChainInterfaces."""
    # Patch the source class so it works even after reload
    with patch("iwa.core.chain.ChainInterfaces") as mock_ci:
        mock_instance = mock_ci.return_value
        yield mock_instance


@pytest.fixture
def rpc_view(rpc_view_cls):
    """Fixture to create an RPCView instance."""
    view = rpc_view_cls()
    # Mock app property
    mock_app = MagicMock()
    with patch.object(view.__class__, "app", new_callable=PropertyMock) as mock_app_prop:
        mock_app_prop.return_value = mock_app
        view.query_one = MagicMock()
        yield view


def test_compose(rpc_view):
    """Test compose method."""
    # Just check it yields valid widgets
    widgets = list(rpc_view.compose())
    assert len(widgets) == 2
    # Check first widget is a Label with correct text
    # Check first widget is a Label
    assert "Label" in str(widgets[0]) or widgets[0].__class__.__name__ == "Label"


def test_check_rpcs_success(rpc_view, mock_chain_interfaces):
    """Test check_rpcs with successful connections."""
    # Setup mock chain interfaces
    mock_gnosis = MagicMock()
    mock_gnosis.chain.rpc = "http://gnosis"
    mock_gnosis.web3.is_connected.return_value = True

    mock_chain_interfaces.get.side_effect = lambda name: mock_gnosis if name == "gnosis" else None

    # We need to ensure check_rpcs calls update_table via call_from_thread
    # Since we mocked @work to simply return the function, calling check_rpcs runs logic in main thread
    # But check_rpcs calls self.app.call_from_thread(self.update_table, results)

    # Run
    rpc_view.check_rpcs()

    # Verify results
    assert rpc_view.app.call_from_thread.called
    args = rpc_view.app.call_from_thread.call_args[0]
    assert args[0] == rpc_view.update_table
    results = args[1]

    # We mocked gnosis to return interface, others None
    # expected results: (chain, url, status, latency)
    gnosis_result = next(r for r in results if r[0] == "gnosis")
    assert gnosis_result[1] == "http://gnosis"
    assert gnosis_result[2] == "Online"


def test_check_rpcs_error(rpc_view, mock_chain_interfaces):
    """Test check_rpcs with connection error."""
    mock_eth = MagicMock()
    mock_eth.chain.rpc = "http://eth"
    mock_eth.web3.is_connected.side_effect = Exception("Connection fail")

    mock_chain_interfaces.get.side_effect = lambda name: mock_eth if name == "ethereum" else None

    rpc_view.check_rpcs()

    args = rpc_view.app.call_from_thread.call_args[0]
    results = args[1]

    eth_result = next(r for r in results if r[0] == "ethereum")
    assert "Error" in eth_result[2]


def test_check_rpcs_missing_interface(rpc_view, mock_chain_interfaces):
    """Test check_rpcs with missing configuration."""
    mock_chain_interfaces.get.return_value = None

    rpc_view.check_rpcs()

    args = rpc_view.app.call_from_thread.call_args[0]
    results = args[1]

    # All Should be Not Configured
    for res in results:
        assert res[2] == "Not Configured"


def test_update_table(rpc_view):
    """Test update_table method."""
    mock_table = MagicMock()
    rpc_view.query_one.return_value = mock_table

    results = [("gnosis", "url", "Online", "10ms")]
    rpc_view.update_table(results)

    mock_table.clear.assert_called_once()
    mock_table.add_row.assert_called_with("gnosis", "url", "Online", "10ms")
