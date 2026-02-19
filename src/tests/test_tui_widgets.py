"""Tests for TUI widgets."""

import importlib
import sys
from unittest.mock import MagicMock, patch

import pytest


# Fixture to reload module to pick up mocks
@pytest.fixture
def widgets_module():
    """Fixture to reload module and mock dependencies."""
    # Patch dependencies at source textual.widgets before import/reload
    with (
        patch("textual.widgets.Label"),
        patch("textual.widgets.Select"),
    ):
        # Do NOT patch DataTable, let it be real so inheritance works
        # But we will verify logic by mocking methods on instance or via patch.object

        if "iwa.tui.widgets.base" in sys.modules:
            importlib.reload(sys.modules["iwa.tui.widgets.base"])
        else:
            pass

        yield sys.modules["iwa.tui.widgets.base"]


@pytest.fixture
def mock_chain_interfaces():
    """Mock ChainInterfaces."""
    # Patch at source or where imported. Code imports ChainInterfaces from iwa.core.chain
    # But it calls ChainInterfaces().get()
    # Let's patch iwa.core.chain.ChainInterfaces
    with patch("iwa.core.chain.ChainInterfaces") as mock_ci:
        yield mock_ci.return_value


def test_chain_selector_compose(widgets_module, mock_chain_interfaces):
    """Test ChainSelector composition."""
    chain_selector_cls = widgets_module.ChainSelector
    label_cls = widgets_module.Label  # This is the mock now
    select_cls = widgets_module.Select  # This is the mock now

    # Setup mock interfaces
    mock_gnosis = MagicMock()
    mock_gnosis.chain.rpc = "http://rpc"

    mock_eth = MagicMock()
    mock_eth.chain.rpc = ""  # No RPC

    def get_interface(name):
        if name == "gnosis":
            return mock_gnosis
        if name == "ethereum":
            return mock_eth
        return MagicMock()  # base

    mock_chain_interfaces.get.side_effect = get_interface

    selector = chain_selector_cls(active_chain="gnosis")
    widgets = list(selector.compose())

    assert len(widgets) == 2
    assert widgets[0] == label_cls.return_value
    assert widgets[1] == select_cls.return_value

    # Verify Label called with correct text
    label_cls.assert_called_with("Chain:", classes="label")

    # Verify Select options
    select_cls.assert_called()
    call_kwargs = select_cls.call_args.kwargs
    assert call_kwargs["value"] == "gnosis"
    assert len(call_kwargs["options"]) == 3  # gnosis, ethereum, base


def test_chain_selector_message(widgets_module):
    """Test ChainSelector message posting."""
    chain_selector_cls = widgets_module.ChainSelector

    selector = chain_selector_cls()
    selector.post_message = MagicMock()


def test_account_table_setup_columns(widgets_module):
    """Test AccountTable columns setup."""
    account_table_cls = widgets_module.AccountTable

    # We must patch DataTable.__init__ so it doesn't fail due to missing app context
    with (
        patch("textual.widgets.DataTable.__init__", return_value=None),
        patch("textual.widgets.DataTable.clear") as mock_clear,
        patch("textual.widgets.DataTable.add_column") as mock_add_column,
    ):
        table = account_table_cls()
        table.setup_columns("gnosis", "xDAI", ["GNO", "COW"])

        mock_clear.assert_called_with(columns=True)
        assert mock_add_column.call_count == 4 + 2


def test_transaction_table_setup_columns(widgets_module):
    """Test TransactionTable columns setup."""
    transaction_table_cls = widgets_module.TransactionTable

    with (
        patch("textual.widgets.DataTable.__init__", return_value=None),
        patch("textual.widgets.DataTable.add_column") as mock_add_column,
    ):
        table = transaction_table_cls()
        # Mock columns property which exists on DataTable
        table.columns = []

        table.setup_columns()
        assert mock_add_column.call_count > 5

        # Test idempotency
        table.columns = ["Time"]
        mock_add_column.reset_mock()
        table.setup_columns()
        mock_add_column.assert_not_called()
