from unittest.mock import MagicMock, patch

import pytest
from textual.widgets import DataTable, Input, Select

from iwa.tui.app import IwaApp
from iwa.tui.views import CreateAddressModal, WalletsView


@pytest.fixture
def mock_wallet():
    with patch("iwa.tui.app.Wallet") as mock_wallet_cls:
        wallet = mock_wallet_cls.return_value
        wallet.key_storage.accounts = {}
        yield wallet


@pytest.fixture(autouse=True)
def mock_deps():
    with (
        patch("iwa.tui.views.EventMonitor"),
        patch("iwa.tui.views.PriceService") as mock_price,
        patch("iwa.tui.views.run_monitor_thread"),
        patch("iwa.core.db.SentTransaction") as mock_sent_tx,
        patch("iwa.core.db.log_transaction"),
        patch("iwa.tui.views.ChainInterfaces") as mock_chains,
    ):
        # Setup Price Service
        mock_price.return_value.get_token_price.return_value = 10.0

        # Setup Chain Interface Mock
        mock_interface = MagicMock()
        mock_interface.tokens = {"TOKEN": "0xToken", "DAI": "0xDAI"}
        mock_interface.chain.rpc = "http://mock"
        mock_interface.chain.native_currency = "ETH"
        mock_chains.return_value.get.return_value = mock_interface

        # Make yield return a dict or object to access specific mocks
        yield {"chains": mock_chains, "pricing": mock_price, "sent_tx": mock_sent_tx}


@pytest.fixture
def mock_plugins():
    with patch("iwa.tui.app.PluginLoader") as mock_loader:
        loader = mock_loader.return_value
        loader.load_plugins.return_value = {}
        yield loader


@pytest.mark.asyncio
async def test_app_startup(mock_wallet, mock_deps, mock_plugins):
    app = IwaApp()
    async with app.run_test(size=(120, 60)):
        assert app.title == "Iwa"
        assert app.query_one(WalletsView)


@pytest.mark.asyncio
async def test_create_address_modal(mock_wallet, mock_deps, mock_plugins):
    app = IwaApp()
    async with app.run_test(size=(120, 60)) as pilot:
        _ = app.query_one(WalletsView)
        await pilot.click("#create_address_btn")
        assert isinstance(app.screen, CreateAddressModal)

        # Type name
        await pilot.click("#tag_input")
        await pilot.press(*list("TestWallet"))

        # Click Create
        await pilot.click("#create")
        await pilot.pause(0.5)

        mock_wallet.key_storage.create_account.assert_called_with("TestWallet")
        assert not isinstance(app.screen, CreateAddressModal)


@pytest.mark.asyncio
async def test_send_transaction_ui(mock_wallet, mock_deps, mock_plugins):
    app = IwaApp()
    async with app.run_test(size=(160, 80)) as pilot:
        view = app.query_one(WalletsView)
        mock_wallet.key_storage.accounts = {
            "addr1": MagicMock(address="0x1", tag="Acc1"),
            "addr2": MagicMock(address="0x2", tag="Acc2"),
        }
        await view.refresh_ui_for_chain()
        await pilot.pause()

        app.query_one("#from_addr", Select).value = "0x1"
        app.query_one("#to_addr", Select).value = "0x2"
        app.query_one("#amount", Input).value = "1.0"
        mock_wallet.send.return_value = "0xTxHash"
        await pilot.click("#send_btn")
        await pilot.pause()


@pytest.mark.asyncio
async def test_view_methods_direct(mock_wallet, mock_deps, mock_plugins):
    """Test methods directly for coverage."""
    # Ensure local patching works or use mock_deps
    app = IwaApp()
    async with app.run_test(size=(160, 80)) as pilot:
        view = app.query_one(WalletsView)

        mock_wallet.key_storage.accounts = {"a1": MagicMock(address="0xABC", tag="Tag1")}
        assert view.resolve_tag("0xABC") == "Tag1"
        assert view.resolve_tag("0xXYZ") == "0xXYZ...xXYZ"

        view.refresh_accounts(force=True)

        txs = [
            {
                "hash": "0xH",
                "from": "0xF",
                "to": "0xT",
                "value": 10**18,
                "token": "NATIVE",
                "timestamp": 1234567890,
            }
        ]

        # Enrich txs needs web3 mock
        # Configured in mock_deps, but get_receipt needs specific return
        chains_mock = mock_deps["chains"]
        mock_interface = chains_mock.return_value.get.return_value
        mock_interface.web3.eth.get_transaction_receipt.return_value = {
            "gasUsed": 21000,
            "effectiveGasPrice": 10**9,
        }

        # Mock from_wei to return float compatible
        mock_interface.web3.from_wei.return_value = 1.0

        # Execute
        view.enrich_and_log_txs(txs)
        await pilot.pause()

        view.on_checkbox_changed(MagicMock(checkbox=MagicMock(id="cb_TOKEN"), value=True))
        if view.active_chain in view.chain_token_states:
            assert "TOKEN" in view.chain_token_states[view.active_chain]
        view.on_checkbox_changed(MagicMock(checkbox=MagicMock(id="cb_TOKEN"), value=False))
        assert "TOKEN" not in view.chain_token_states[view.active_chain]


@pytest.mark.asyncio
async def test_load_recent_txs(mock_wallet, mock_deps, mock_plugins):
    # Setup Mock SentTransaction from fixture
    mock_sent_tx_cls = mock_deps["sent_tx"]

    mock_tx = MagicMock()
    mock_tx.timestamp.strftime.return_value = "2025-01-01 12:00:00"
    mock_tx.from_address = "0x1"
    mock_tx.to_address = "0x2"
    mock_tx.value_eur = 10.5
    mock_tx.amount_wei = 10**18
    mock_tx.token_symbol = "ETH"
    mock_tx.tx_hash = "0xHash"

    # Configure mock chain
    # Allow timestamp > datetime comparison
    mock_ts_field = MagicMock()
    mock_ts_field.__gt__ = MagicMock(return_value=True)
    # Also need desc() for order_by
    mock_ts_field.desc.return_value = "DESC_ORDER"
    mock_sent_tx_cls.timestamp = mock_ts_field

    mock_sent_tx_cls.select.return_value.where.return_value.order_by.return_value = [mock_tx]

    app = IwaApp()
    async with app.run_test(size=(160, 80)) as pilot:
        _ = app.query_one(WalletsView)
        # Give time for on_mount -> load_recent_txs to run
        await pilot.pause(0.5)

        # Verify load_recent_txs was called
        table = app.query_one("#tx_table", DataTable)
        assert table.row_count > 0

        # Check first row presence
        assert "0xHash" in table.rows

        # Verify content of the row
        row = table.get_row("0xHash")
        # row is a list of cell values.
        # Check date format
        assert "2025-01-01 12:00:00" in str(row[0])
        # Check value in EUR
        assert "€10.50" in str(row[4])
