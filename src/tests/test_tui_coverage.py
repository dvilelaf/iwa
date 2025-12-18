from unittest.mock import MagicMock, patch

import pytest
from textual.widgets import Input, Select

from iwa.tui.app import IwaApp
from iwa.tui.screens.wallets import WalletsScreen


@pytest.fixture
def mock_wallet():
    with patch("iwa.tui.app.Wallet") as mock_wallet_cls:
        wallet = mock_wallet_cls.return_value
        wallet.key_storage.accounts = {
            "0x1": MagicMock(address="0x1", tag="Acc1"),
            "0x2": MagicMock(address="0x2", tag="Acc2"),
        }
        wallet.account_service = MagicMock()
        wallet.account_service.accounts = wallet.key_storage.accounts
        wallet.account_service.get_account_data.side_effect = lambda: wallet.account_service.accounts
        wallet.balance_service = MagicMock()

        # Helper to make resolve_account work with key_storage for consistency
        wallet.account_service.resolve_account.side_effect = lambda tag: wallet.key_storage.get_account(tag)

        wallet.get_native_balance_eth.return_value = 0.0
        wallet.get_erc20_balance_eth.return_value = 0.0
        wallet.send.return_value = "0xHash"

        # Mock PluginService
        wallet.plugin_service = MagicMock()
        wallet.plugin_service.get_all_plugins.return_value = {}
        yield wallet


@pytest.fixture(autouse=True)
def mock_deps():
    with (
        patch("iwa.tui.screens.wallets.EventMonitor"),
        patch("iwa.tui.screens.wallets.PriceService") as mock_price,
        patch("iwa.core.db.SentTransaction"),
        patch("iwa.core.db.log_transaction"),
        patch("iwa.tui.screens.wallets.ChainInterfaces") as mock_chains,
    ):
        mock_price.return_value.get_token_price.return_value = 10.0

        # Setup Chain Interface Mock
        mock_interface = MagicMock()
        mock_interface.tokens = {"TOKEN": "0xToken"}
        mock_interface.chain.native_currency = "ETH"
        mock_chains.return_value.get.return_value = mock_interface
        mock_chains.return_value.items.return_value = [("gnosis", mock_interface)]

        yield {"chains": mock_chains}




@pytest.mark.asyncio
async def test_fetch_balances_flow(mock_wallet, mock_deps):
    app = IwaApp()
    # Patch call_from_thread
    app.call_from_thread = lambda cb, *args, **kwargs: cb(*args, **kwargs)

    async with app.run_test(size=(160, 80)):
        view = app.query_one(WalletsScreen)

        # Configure returns on both legacy and service
        mock_wallet.get_native_balance_eth.return_value = 1.2345
        mock_wallet.balance_service.get_native_balance_eth.return_value = 1.2345
        mock_wallet.balance_service.get_erc20_balance_with_retry.return_value = 500.0

        # Trigger fetch directly
        view.balance_cache = {}

        # Trigger (call impl directly to avoid threading issues)
        view.chain_token_states["gnosis"].add("TOKEN")
        # In the refactored view, we call fetch_all_balances
        # We'll wait for the worker to finish
        worker = view.fetch_all_balances(view.active_chain, ["TOKEN"])
        await worker.wait()

        # Verify calls made (can check either legacy or service depending on how it's implemented)
        mock_wallet.balance_service.get_native_balance_eth.assert_called()
        mock_wallet.balance_service.get_erc20_balance_with_retry.assert_called()

        # Verify cache state
        assert view.balance_cache["gnosis"]["0x1"]["NATIVE"] == "1.2345"
        assert view.balance_cache["gnosis"]["0x1"]["TOKEN"] == "500.0000"


@pytest.mark.asyncio
async def test_chain_changed(mock_wallet, mock_deps):
    app = IwaApp()
    # Patch call_from_thread
    app.call_from_thread = lambda cb, *args, **kwargs: cb(*args, **kwargs)

    async with app.run_test(size=(160, 80)) as pilot:
        view = app.query_one(WalletsScreen)

        # Select different chain
        select = app.query_one("#chain_select")
        select.value = "ethereum"
        await pilot.pause(1.0)

        assert view.active_chain == "ethereum"

        # Test Invalid chain (no RPC)
        chains = mock_deps["chains"]
        chains.return_value.get.return_value.chain.rpc = ""
        select.value = "base"
        await pilot.pause()


@pytest.mark.asyncio
async def test_send_transaction_coverage(mock_wallet, mock_deps):
    app = IwaApp()
    # Patch call_from_thread
    app.call_from_thread = lambda cb, *args, **kwargs: cb(*args, **kwargs)

    async with app.run_test(size=(200, 200)) as pilot:
        view = app.query_one(WalletsScreen)
        # Force table height
        app.query_one("#accounts_table").styles.height = 10
        # Wait for workers to populate
        # In the new design, monitor_workers are created in start_monitor
        if not view.monitor_workers:
             view.start_monitor()
        assert len(view.monitor_workers) > 0
        await pilot.pause()

        # Test validation failures
        # 1. No from
        app.query_one("#from_addr", Select).value = Select.BLANK
        mock_wallet.send.reset_mock()
        btn = app.query_one("#send_btn")
        btn.focus()
        await pilot.press("enter")
        # Assert not sent
        mock_wallet.send.assert_not_called()

        # 2. No to
        app.query_one("#from_addr", Select).value = "0x1"
        app.query_one("#to_addr", Select).value = Select.BLANK
        btn = app.query_one("#send_btn")
        btn.focus()
        await pilot.press("enter")
        mock_wallet.send.assert_not_called()

        # 3. No amount
        app.query_one("#to_addr", Select).value = "0x2"
        app.query_one("#amount", Input).value = ""
        btn = app.query_one("#send_btn")
        btn.focus()
        await pilot.press("enter")
        mock_wallet.send.assert_not_called()

        # 4. Valid Send NATIVE
        app.query_one("#amount", Input).value = "1.0"
        app.query_one("#token", Select).value = "native"
        mock_wallet.send.return_value = "0xTxHash"

        # Call worker directly
        view.send_tx_worker("0x1", "0x2", "native", 1.0)
        await pilot.pause()

        # Verify wallet.send called
        mock_wallet.send.assert_called()

        # 5. Valid Send ERC20
        mock_wallet.send.reset_mock()
        view.send_tx_worker("0x1", "0x2", "TOKEN", 1.0)
        await pilot.pause()
        mock_wallet.send.assert_called()


@pytest.mark.asyncio
async def test_watchdog_logic(mock_wallet, mock_deps):
    app = IwaApp()
    app.call_from_thread = lambda cb, *args, **kwargs: cb(*args, **kwargs)

    async with app.run_test(size=(160, 80)):
        view = app.query_one(WalletsScreen)

        # 1. Test "Everything Loaded" -> No Retry
        view.balance_cache = {
            "gnosis": {
                "0x1": {"NATIVE": "1.0", "TOKEN": "10.0"},
                "0x2": {"NATIVE": "2.0", "TOKEN": "20.0"},
            }
        }
        view.chain_token_states["gnosis"] = {"TOKEN"}

        # Should NOT trigger fetch
        with patch.object(view, "fetch_all_balances") as mock_fetch:
            view.check_balance_loading_status("gnosis")
            mock_fetch.assert_not_called()

        # 2. Test "Missing Native" -> Retry
        view.balance_cache["gnosis"]["0x1"]["NATIVE"] = "Loading..."
        with patch.object(view, "fetch_all_balances") as mock_fetch:
            view.check_balance_loading_status("gnosis")
            mock_fetch.assert_called_with("gnosis", ["TOKEN"])

        # 3. Test "Missing Chain in Cache" -> Retry
        del view.balance_cache["gnosis"]
        with patch.object(view, "fetch_all_balances") as mock_fetch:
            view.check_balance_loading_status("gnosis")
            mock_fetch.assert_called_with("gnosis", ["TOKEN"])

        # Restore for next
        view.balance_cache = {"gnosis": {}}

        # 4. Test "Missing Address in Cache" -> Retry
        view.balance_cache["gnosis"] = {}  # Empty
        with patch.object(view, "fetch_all_balances") as mock_fetch:
            view.check_balance_loading_status("gnosis")
            mock_fetch.assert_called_with("gnosis", ["TOKEN"])


@pytest.mark.asyncio
async def test_monitor_handler(mock_wallet, mock_deps):
    app = IwaApp()
    app.call_from_thread = lambda cb, *args, **kwargs: cb(*args, **kwargs)

    async with app.run_test(size=(160, 80)):
        view = app.query_one(WalletsScreen)

        # Simulate txs
        txs = [
            {
                "hash": "0xHash1",
                "timestamp": 1700000000,
                "from": "0x1",
                "to": "0x2",
                "token": "NATIVE",
                "value": 10**18,
            },
            {
                "hash": "0xHash2",
                "timestamp": None,
                "from": "0x3",
                "to": "0x4",
                "token": "DAI",
                "value": 500,
            },
        ]

        view.handle_new_txs(txs)

        # Verify table rows added
        table = app.query_one("#tx_table")
        assert table.row_count >= 2
        # Verify first row details
        assert "Detected" in str(table.get_row("0xHash1"))


@pytest.mark.asyncio
async def test_token_fetch_retry_and_failure(mock_wallet, mock_deps):
    app = IwaApp()
    app.call_from_thread = lambda cb, *args, **kwargs: cb(*args, **kwargs)

    async with app.run_test(size=(160, 80)):
        view = app.query_one(WalletsScreen)
        view.balance_cache = {}
        view.chain_token_states["gnosis"] = {"TOKEN"}

        # Check worker logic
        worker = view.monitor_workers[0]
        # We can't easily check internal state of the worker loop without complex mocking
        # assert worker.monitor.chain_name in ["gnosis", "ethereum", "base"]

        # Limit to 1 account to control call count
        mock_wallet.key_storage.accounts = {"0x1": MagicMock(address="0x1", tag="Acc1")}

        # Patch time.sleep to avoid wait
        with patch("time.sleep"):
            # Case 1: Success
            mock_wallet.balance_service.get_erc20_balance_with_retry.return_value = 100.0

            worker = view.fetch_all_balances("gnosis", ["TOKEN"])
            await worker.wait()
            # verify call made
            mock_wallet.balance_service.get_erc20_balance_with_retry.assert_called()
            # Should have updated cache (4 decimals)
            assert view.balance_cache["gnosis"]["0x1"]["TOKEN"] == "100.0000"


@pytest.mark.asyncio
async def test_send_transaction_failure(mock_wallet, mock_deps):
    app = IwaApp()
    app.call_from_thread = lambda cb, *args, **kwargs: cb(*args, **kwargs)

    async with app.run_test(size=(160, 80)):
        view = app.query_one(WalletsScreen)
        mock_wallet.send.side_effect = Exception("Tx Failed")

        # Just ensure it doesn't crash
        view.send_tx_worker("0x1", "0x2", "native", 1.0)
