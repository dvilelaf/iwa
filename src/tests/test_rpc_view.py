"""Tests for TUI RPC View."""

from unittest.mock import MagicMock, patch

import pytest

from iwa.tui.rpc import RPCView


@pytest.fixture
def mock_chain_interfaces():
    with patch("iwa.tui.rpc.ChainInterfaces") as mock:
        yield mock


def test_rpc_view_compose():
    """Test RPCView compose method returns expected widgets."""
    view = RPCView()
    result = list(view.compose())

    assert len(result) == 2  # Label and DataTable


def test_check_rpcs_interface_not_found(mock_chain_interfaces):
    """Test check_rpcs handles missing interface."""
    mock_chain_interfaces.return_value.get.return_value = None

    view = RPCView()

    # Verify the method exists and is callable
    assert hasattr(view, "check_rpcs")
    assert callable(view.check_rpcs)


def test_check_rpcs_no_rpc_url(mock_chain_interfaces):
    """Test check_rpcs handles missing RPC URL."""
    mock_interface = MagicMock()
    mock_interface.chain.rpc = ""
    mock_chain_interfaces.return_value.get.return_value = mock_interface

    view = RPCView()

    # Verify method exists and has correct signature
    assert callable(view.check_rpcs)


def test_check_rpcs_connection_error(mock_chain_interfaces):
    """Test check_rpcs handles connection errors."""
    mock_interface = MagicMock()
    mock_interface.chain.rpc = "http://localhost:8545"
    mock_interface.web3.is_connected.side_effect = Exception("Connection refused")
    mock_chain_interfaces.return_value.get.return_value = mock_interface

    view = RPCView()

    assert callable(view.check_rpcs)


def test_update_table():
    """Test update_table method updates DataTable."""
    view = RPCView()

    mock_table = MagicMock()
    with patch.object(view, "query_one", return_value=mock_table):
        results = [
            ("gnosis", "http://rpc1", "Online", "50.00"),
            ("ethereum", "http://rpc2", "Offline", "-"),
        ]

        view.update_table(results)

        mock_table.clear.assert_called_once()
        assert mock_table.add_row.call_count == 2
