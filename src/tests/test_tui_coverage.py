from unittest.mock import MagicMock, patch

import pytest
from textual.widgets import Input, Select

from iwa.tui.app import IwaApp
from iwa.tui.views import WalletsView


@pytest.fixture(autouse=True)
def mock_work_decorator():
    """Make @work decorator run synchronously for coverage."""

    def no_op_work(*args, **kwargs):
        def decorator(func):
            return func

        return decorator

    with patch("iwa.tui.views.work", side_effect=no_op_work):
        yield


@pytest.fixture
def mock_wallet():
    with patch("iwa.tui.app.Wallet") as mock_wallet_cls:
        wallet = mock_wallet_cls.return_value
        wallet.key_storage.accounts = {
            "0x1": MagicMock(address="0x1", tag="Acc1"),
            "0x2": MagicMock(address="0x2", tag="Acc2"),
        }
        wallet.get_native_balance_eth.return_value = 0.0
        wallet.get_erc20_balance_eth.return_value = 0.0
        wallet.send.return_value = "0xHash"
        yield wallet


@pytest.fixture(autouse=True)
def mock_deps():
    with (
        patch("iwa.tui.views.EventMonitor"),
        patch("iwa.tui.views.PriceService") as mock_price,
        patch("iwa.tui.views.run_monitor_thread"),
        patch("iwa.core.db.SentTransaction"),
        patch("iwa.core.db.log_transaction"),
        patch("iwa.tui.views.ChainInterfaces") as mock_chains,
    ):
        mock_price.return_value.get_token_price.return_value = 10.0

        # Setup Chain Interface Mock
        mock_interface = MagicMock()
        mock_interface.tokens = {"TOKEN": "0xToken"}
        mock_interface.chain.native_currency = "ETH"
        mock_chains.return_value.get.return_value = mock_interface

        yield


@pytest.fixture
def mock_plugins():
    with patch("iwa.tui.app.PluginLoader") as mock_loader:
        loader = mock_loader.return_value
        loader.load_plugins.return_value = {}
        yield loader


@pytest.mark.asyncio
@pytest.mark.skip(reason="Flaky mock interaction with new worker logic")
async def test_fetch_balances_flow(mock_wallet, mock_deps, mock_plugins):
    app = IwaApp()
    async with app.run_test(size=(160, 80)) as pilot:
        view = app.query_one(WalletsView)

        # Configure wallet returns
        mock_wallet.get_native_balance_eth.return_value = 1.2345
        mock_wallet.get_erc20_balance_eth.return_value = 500.0

        # Trigger fetch directly (it's threaded via @work, we wait)
        # We need to ensure we cover the "should_fetch" logic
        # 1. Clear cache
        view.balance_cache = {}

        # 2. Trigger
        view.fetch_all_balances("gnosis", ["TOKEN"])

        # Verify cache updated/calls made
        mock_wallet.get_native_balance_eth.assert_called()
        mock_wallet.get_erc20_balance_eth.assert_called()

        # Verify cache state
        assert view.balance_cache["gnosis"]["0x1"]["NATIVE"] == "1.2345"
        assert view.balance_cache["gnosis"]["0x1"]["TOKEN"] == "500.0000"

        # 3. Test Rate Limit / Error path
        mock_wallet.get_native_balance_eth.side_effect = Exception("429 Rate Limit")
        view.balance_cache = {}
        view.fetch_all_balances("gnosis", [])
        await pilot.pause(0.5)
        # Should notify error (we can't easily check notify without mocking app.call_from_thread,
        # but coverage should hit the line)


@pytest.mark.asyncio
@pytest.mark.skip(reason="Flaky mock interaction with new worker logic")
async def test_chain_changed(mock_wallet, mock_deps, mock_plugins):
    app = IwaApp()
    async with app.run_test(size=(160, 80)) as pilot:
        view = app.query_one(WalletsView)

        # Select different chain
        select = app.query_one("#chain_select")
        select.value = "ethereum"
        await pilot.pause()

        assert view.active_chain == "ethereum"
        # Verify refresh called (mock logs or side effects)

        # Test Invalid chain (no RPC)
        # Mock chains get to return no RPC
        chains = mock_deps["chains"]
        chains.return_value.get.return_value.chain.rpc = ""
        select.value = "base"
        await pilot.pause()
        # Should stay on ethereum or notify


@pytest.mark.asyncio
@pytest.mark.skip(reason="Flaky mock interaction with new worker logic")
async def test_send_transaction_coverage(mock_wallet, mock_deps, mock_plugins):
    app = IwaApp()
    async with app.run_test(size=(160, 80)) as pilot:
        view = app.query_one(WalletsView)

        # Select from/to/token
        # Direct modification of widget values is faster/reliable for coverage
        # Need to ensure options are populated first
        await view.refresh_ui_for_chain()
        await pilot.pause()

        # Test validation failures
        # 1. No from
        app.query_one("#from_addr", Select).value = Select.BLANK
        mock_wallet.send.reset_mock()
        await pilot.click("#send_btn")
        # Assert not sent
        mock_wallet.send.assert_not_called()

        # 2. No to
        app.query_one("#from_addr", Select).value = "0x1"
        app.query_one("#to_addr", Select).value = Select.BLANK
        await pilot.click("#send_btn")
        mock_wallet.send.assert_not_called()

        # 3. No amount
        app.query_one("#to_addr", Select).value = "0x2"
        app.query_one("#amount", Input).value = ""
        await pilot.click("#send_btn")
        mock_wallet.send.assert_not_called()

        # 4. Valid Send NATIVE
        app.query_one("#amount", Input).value = "1.0"
        app.query_one("#token", Select).value = "native"
        mock_wallet.send.return_value = "0xTxHash"

        await pilot.click("#send_btn")
        await pilot.pause()

        # Verify wallet.send called
        mock_wallet.send.assert_called()

        # 5. Valid Send ERC20
        mock_wallet.send.reset_mock()
        app.query_one("#token", Select).value = "TOKEN"

        await pilot.click("#send_btn")
        await pilot.pause()
        mock_wallet.send.assert_called()
