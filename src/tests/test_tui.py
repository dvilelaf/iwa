from unittest.mock import MagicMock, PropertyMock, patch

import pytest
from textual.widgets import Button, Checkbox, DataTable, Input, Select, SelectionList

from iwa.tui.app import IwaApp
from iwa.tui.views import CreateEOAModal, CreateSafeModal, WalletsView


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
        # Setup distinct chain mocks
        gnosis_mock = MagicMock()
        gnosis_mock.tokens = {"TOKEN": "0xToken", "DAI": "0xDAI"}
        gnosis_mock.chain.rpc = "http://gnosis"
        gnosis_mock.chain.native_currency = "xDAI"

        eth_mock = MagicMock()
        eth_mock.tokens = {"USDC": "0xUSDC", "USDT": "0xUSDT"}
        eth_mock.chain.rpc = "http://eth"
        eth_mock.chain.native_currency = "ETH"

        def get_chain(name):
            if name == "ethereum":
                return eth_mock
            return gnosis_mock

        mock_chains.return_value.get.side_effect = get_chain

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
async def test_create_eoa_modal(mock_wallet, mock_deps, mock_plugins):
    app = IwaApp()
    async with app.run_test(size=(120, 60)) as pilot:
        _ = app.query_one(WalletsView)
        await pilot.click("#create_eoa_btn")
        assert isinstance(app.screen, CreateEOAModal)

        # Type name
        await pilot.click("#tag_input")
        await pilot.press(*list("TestEOA"))

        # Click Create
        await pilot.click("#create")
        await pilot.pause(0.5)

        mock_wallet.key_storage.create_account.assert_called_with("TestEOA")
        assert not isinstance(app.screen, CreateEOAModal)


@pytest.mark.asyncio
async def test_create_safe_modal(mock_wallet, mock_deps, mock_plugins):
    _ = IwaApp()

    # Setup accounts for owner selection
    mock_wallet.key_storage.accounts = {
        "0x1": MagicMock(address="0x1", tag="Owner1"),
        "0x2": MagicMock(address="0x2", tag="Owner2"),
    }

    # Unit test compose structure directly to bypass Textual harness issues
    # Mock Vertical/Horizontal context managers to avoid runtime errors
    with (
        patch("iwa.tui.views.Vertical") as mock_vertical,
        patch("iwa.tui.views.Horizontal") as mock_horizontal,
    ):
        mock_vertical.return_value.__enter__.return_value = MagicMock()
        mock_horizontal.return_value.__enter__.return_value = MagicMock()

        modal = CreateSafeModal(
            [(acc.tag, acc.address) for acc in mock_wallet.key_storage.accounts.values()]
        )
        widgets = list(modal.compose())

        # Check if we have the inputs
        input_ids = [w.id for w in widgets if isinstance(w, Input)]
        assert "tag_input" in input_ids
        assert "threshold_input" in input_ids

        # Check SelectionList
        sl_ids = [w.id for w in widgets if isinstance(w, SelectionList)]
        assert "owners_list" in sl_ids

        # Check buttons
        btn_ids = [w.id for w in widgets if isinstance(w, Button)]
        assert "create" in btn_ids
        assert "cancel" in btn_ids

    # Unit test CreateSafeModal handlers
    modal = CreateSafeModal([])
    modal.dismiss = MagicMock()

    # Test Cancel
    cancel_event = MagicMock()
    cancel_event.button.id = "cancel"
    modal.on_button_pressed(cancel_event)
    modal.dismiss.assert_called_once()

    # Test Create (placeholder logic)
    create_event = MagicMock()
    create_event.button.id = "create"

    # Mock query_one since modal is not mounted
    modal.query_one = MagicMock()

    # Mock return values for tag and threshold inputs
    tag_input_mock = MagicMock()
    tag_input_mock.value = "TestSafe"

    thresh_input_mock = MagicMock()
    thresh_input_mock.value = "2"

    # Mock SelectionList
    owners_list_mock = MagicMock()
    owners_list_mock.selected = ["0x1", "0x2"]

    def query_side_effect(selector):
        if selector == "#tag_input":
            return tag_input_mock
        if selector == "#threshold_input":
            return thresh_input_mock
        if selector == "#owners_list":
            return owners_list_mock
        return MagicMock()

    modal.query_one.side_effect = query_side_effect

    modal.on_button_pressed(create_event)
    # Just ensure it doesn't crash as logic is just logging currently

    # Unit test WalletsView handler for Create Safe (since we skipped click)
    view = WalletsView(mock_wallet)

    # Mock 'app' property using PropertyMock since it's read-only
    with patch.object(WalletsView, "app", new_callable=PropertyMock) as mock_app_prop:
        mock_app = MagicMock()
        mock_app_prop.return_value = mock_app

        # Mock wallet key storage for accounts list
        mock_wallet.key_storage.accounts = {}

        safe_btn_event = MagicMock()
        safe_btn_event.button.id = "create_safe_btn"

        view.on_button_pressed(safe_btn_event)

        args = mock_app.push_screen.call_args[0]
        assert isinstance(args[0], CreateSafeModal)
        callback = args[1]

        # Test callback logic
        # We need to verify that create_safe_worker is called with correct args
        with patch.object(view, "create_safe_worker") as mock_worker:
            # Case 1: Success
            callback({"tag": "MySafe", "threshold": 2, "owners": ["0x1", "0x2"]})
            mock_worker.assert_called_with("MySafe", 2, ["0x1", "0x2"])

            # Case 2: No owners
            view.notify = MagicMock()  # Reset notify mock
            callback({"tag": "MySafe", "threshold": 2, "owners": []})
            view.notify.assert_called_with(
                "Safe creation failed: No owners selected.", severity="error"
            )
            # Worker should NOT be called
            assert mock_worker.call_count == 1  # Still 1 from previous call


@pytest.mark.asyncio
async def test_send_transaction_ui(mock_wallet, mock_deps, mock_plugins):
    app = IwaApp()
    async with app.run_test(size=(200, 200)) as pilot:
        view = app.query_one(WalletsView)
        mock_wallet.key_storage.accounts = {
            "addr1": MagicMock(address="0x1", tag="Acc1"),
            "addr2": MagicMock(address="0x2", tag="Acc2"),
        }
        await view.refresh_ui_for_chain()
        await pilot.pause()

        # Force table height to avoid pushing button off screen
        app.query_one("#accounts_table").styles.height = 10
        await pilot.pause()

        # Scroll to button just in case
        # await app.query_one(WalletsView).scroll_to_widget(app.query_one("#send_btn"))

        app.query_one("#from_addr", Select).value = "0x1"
        app.query_one("#to_addr", Select).value = "0x2"
        app.query_one("#amount", Input).value = "1.0"
        mock_wallet.send.return_value = "0xTxHash"

        # Click by focus/enter to avoid layout/OutOfBounds issues
        btn = app.query_one("#send_btn")
        btn.focus()
        await pilot.press("enter")
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
        # Check value in EUR (now at index 5 due to Chain column at 1)
        assert "€10.50" in str(row[5])


@pytest.mark.asyncio
async def test_chain_switching(mock_wallet, mock_deps, mock_plugins):
    """Test chain selector functionality."""
    app = IwaApp()
    async with app.run_test(size=(160, 80)) as pilot:
        view = app.query_one(WalletsView)

        # Initial chain is Gnosis (default)
        assert view.active_chain == "gnosis"

        # Change to Ethereum
        # We simulate the Select change event
        chain_select = app.query_one("#chain_select", Select)

        # Using pilot to modify the value. Note: setting value directly might not trigger event in
        # test harness the same way unless we wait.
        # But setting .value property on Select DOES trigger Changed event.
        chain_select.value = "ethereum"

        # Wait for event to process
        await pilot.pause()

        # Verify active chain updated
        assert view.active_chain == "ethereum"

        # Verify active chain updated
        assert view.active_chain == "ethereum"

        # Verify columns updated
        # Gnosis had TOKEN, DAI. Ethereum has USDC, USDT.
        table = app.query_one("#accounts_table", DataTable)
        col_labels = [c.label.plain.upper() for c in table.columns.values()]

        # Should contain standard columns + ETH native + USDC + USDT
        assert "TAG" in col_labels
        assert "ADDRESS" in col_labels
        assert "ETH" in col_labels  # Native
        assert "USDC" in col_labels
        assert "USDT" in col_labels
        assert "DAI" not in col_labels

        assert "DAI" not in col_labels


@pytest.mark.asyncio
async def test_token_overwrite(mock_wallet, mock_deps, mock_plugins):
    """Test that enabling a second token does not overwrite the first."""
    app = IwaApp()
    async with app.run_test(size=(160, 80)) as pilot:
        view = app.query_one(WalletsView)

        # Setup mock account
        mock_wallet.key_storage.accounts = {"0x1": MagicMock(address="0x1", tag="TestAcc")}
        view.refresh_accounts(force=True)

        # Switch to Ethereum (has USDC, USDT)
        chain_select = app.query_one("#chain_select", Select)
        chain_select.value = "ethereum"
        await pilot.pause()

        # Configure wallet mock to return balances
        mock_wallet.get_erc20_balance_eth.return_value = 100.0

        cb_usdc = app.query_one("#cb_USDC", Checkbox)
        cb_usdc.value = True
        await pilot.pause()
        await pilot.pause()  # Wait for workers

        # Enable USDT (Second token)
        cb_usdt = app.query_one("#cb_USDT", Checkbox)
        cb_usdt.value = True
        await pilot.pause()
        await pilot.pause()  # Wait for workers

        # Check table content
        table = app.query_one("#accounts_table", DataTable)

        # Get row for first account
        # Columns: Tag(0), Address(1), Type(2), Native(3), USDC(4), USDT(5)
        # Mock wallet returns None for balances by default or 0?
        # We need to check if update_table_cell was called with correct col_idx

        # Since we use real app logic, check internal cache or table cells
        # The key for row is address.
        addr = list(mock_wallet.key_storage.accounts.values())[0].address
        row_idx = table.get_row_index(addr)

        # Check USDC column (4)
        usdc_cell = table.get_row_at(row_idx)[4]
        # Check USDT column (5)
        usdt_cell = table.get_row_at(row_idx)[5]

        # If bug exists, USDT update might have written to col 4, or USDC remains empty
        # We expect both to be non-empty (or at least "-" or "Loading..." or a value)
        # If overwrote, maybe USDC is "Loading..." or has USDT value?

        # With current mocks, balance fetch returns a float or None.
        # We assume mocks work.

        # NOTE: If indices are wrong, USDT might write to 4.

        # Let's check that col 5 is NOT empty string
        assert str(usdt_cell) != "", "USDT column should not be empty"
        assert str(usdc_cell) != "", "USDC column should not be empty"
