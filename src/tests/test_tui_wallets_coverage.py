"""Tests for TUI WalletsScreen to improve coverage.

Tests methods in isolation by mocking the Textual app context
and external dependencies (Wallet, ChainInterfaces, etc.).
"""

import datetime
import time
from unittest.mock import MagicMock, PropertyMock, patch

import pytest
from rich.text import Text


class _FieldMock:
    """Mock for Peewee model fields that support comparison operators.

    MagicMock.__gt__ returns NotImplemented, which makes
    ``MagicMock() > datetime.datetime(...)`` raise TypeError.
    This plain class returns MagicMock from comparisons (mimicking
    Peewee Expression objects) and delegates attribute access via __getattr__.
    """

    def __gt__(self, other):
        return MagicMock()

    def __lt__(self, other):
        return MagicMock()

    def __eq__(self, other):
        return MagicMock()

    def __ne__(self, other):
        return MagicMock()

    def __hash__(self):
        return id(self)

    def __getattr__(self, name):
        return MagicMock()


# Valid Ethereum addresses for tests
ADDR_MASTER = "0x1111111111111111111111111111111111111111"
ADDR_EOA = "0x2222222222222222222222222222222222222222"
ADDR_SAFE = "0x3333333333333333333333333333333333333333"
ADDR_EXTERNAL = "0x4444444444444444444444444444444444444444"
ADDR_OWNER2 = "0x5555555555555555555555555555555555555555"


# ---------------------------------------------------------------------------
# Helpers to build mock objects
# ---------------------------------------------------------------------------

def _make_stored_account(address, tag):
    """Create a mock StoredAccount (EOA)."""
    acct = MagicMock()
    acct.address = address
    acct.tag = tag
    # Not a StoredSafeAccount
    acct.__class__ = type("StoredAccount", (), {})
    return acct


def _make_safe_account(address, tag, chains):
    """Create a mock StoredSafeAccount."""
    from iwa.core.models import StoredSafeAccount

    acct = MagicMock(spec=StoredSafeAccount)
    acct.address = address
    acct.tag = tag
    acct.chains = chains
    return acct


def _make_chain_interface(native_currency="xDAI", tokens=None, rpc="https://rpc.gnosis.io"):
    """Create a mock chain interface."""
    interface = MagicMock()
    interface.chain.native_currency = native_currency
    interface.chain.rpc = rpc
    interface.current_rpc = rpc
    interface.tokens = tokens or {"OLAS": MagicMock(), "GNO": MagicMock()}
    return interface


def _make_wallet_mock(accounts_dict=None):
    """Create a mock Wallet with account_service, balance_service, etc."""
    wallet = MagicMock()
    if accounts_dict is None:
        eoa = _make_stored_account(ADDR_EOA, "MyEOA")
        accounts_dict = {ADDR_EOA: eoa}
    wallet.account_service.get_account_data.return_value = accounts_dict
    wallet.key_storage.accounts = MagicMock()
    wallet.key_storage.accounts.values.return_value = list(accounts_dict.values())
    return wallet


# ---------------------------------------------------------------------------
# Fixture: a WalletsScreen instance with fully mocked context
# ---------------------------------------------------------------------------

@pytest.fixture
def wallets_screen():
    """Create a WalletsScreen instance with mocked Wallet and app context."""
    with (
        patch("iwa.tui.screens.wallets.PriceService"),
        patch("iwa.tui.screens.wallets.configure_logger"),
    ):
        from iwa.tui.screens.wallets import WalletsScreen

        wallet = _make_wallet_mock()
        screen = WalletsScreen.__new__(WalletsScreen)
        # Manually set up attributes that __init__ would set
        screen.wallet = wallet
        screen.active_chain = "gnosis"
        screen.monitor_workers = []
        screen.chain_token_states = {
            "gnosis": set(),
            "ethereum": set(),
            "base": set(),
        }
        screen.balance_cache = {}
        screen.price_service = MagicMock()

        # Mock the Textual app property (read-only on MessagePump)
        mock_app = MagicMock()
        with patch.object(type(screen), "app", new_callable=PropertyMock, return_value=mock_app):
            screen.query_one = MagicMock()
            screen.notify = MagicMock()
            screen.set_timer = MagicMock()
            screen.run_worker = MagicMock()

            yield screen


# ===========================================================================
# Tests for __init__
# ===========================================================================

class TestWalletsScreenInit:
    """Test WalletsScreen initialization."""

    def test_init_sets_defaults(self):
        """Test that __init__ sets default values."""
        with (
            patch("iwa.tui.screens.wallets.PriceService") as mock_ps,
            patch("iwa.tui.screens.wallets.configure_logger"),
            patch("textual.containers.VerticalScroll.__init__", return_value=None),
        ):
            from iwa.tui.screens.wallets import WalletsScreen

            wallet = MagicMock()
            screen = WalletsScreen(wallet)

            assert screen.wallet is wallet
            assert screen.active_chain == "gnosis"
            assert screen.monitor_workers == []
            assert "gnosis" in screen.chain_token_states
            assert screen.balance_cache == {}
            mock_ps.assert_called_once()


# ===========================================================================
# Tests for compose
# ===========================================================================

class TestCompose:
    """Test compose method."""

    def test_compose_is_generator(self):
        """Test that compose is defined as a generator method."""
        with (
            patch("iwa.tui.screens.wallets.PriceService"),
            patch("iwa.tui.screens.wallets.configure_logger"),
            patch("textual.containers.VerticalScroll.__init__", return_value=None),
        ):
            from iwa.tui.screens.wallets import WalletsScreen

            wallet = MagicMock()
            screen = WalletsScreen(wallet)
            # compose() requires an active app context to yield widgets
            # (HorizontalScroll/Center context managers access self.app)
            # Just verify it's defined as a generator
            import inspect
            assert inspect.isgeneratorfunction(screen.compose)


# ===========================================================================
# Tests for action_refresh
# ===========================================================================

class TestActionRefresh:
    """Test the refresh action."""

    def test_action_refresh_calls_refresh_accounts(self, wallets_screen):
        """Test that action_refresh notifies and refreshes."""
        with patch.object(wallets_screen, "refresh_accounts") as mock_refresh:
            wallets_screen.action_refresh()
            wallets_screen.notify.assert_called_once()
            mock_refresh.assert_called_once_with(force=True)


# ===========================================================================
# Tests for refresh_accounts
# ===========================================================================

class TestRefreshAccounts:
    """Test refresh_accounts."""

    def test_refresh_accounts_no_force(self, wallets_screen):
        """Test refresh_accounts without force flag."""
        with (
            patch.object(wallets_screen, "refresh_table_structure_and_data") as mock_rtsd,
            patch.object(wallets_screen, "load_recent_txs") as mock_txs,
        ):
            wallets_screen.refresh_accounts()
            mock_rtsd.assert_called_once()
            mock_txs.assert_called_once()

    def test_refresh_accounts_force_clears_cache(self, wallets_screen):
        """Test refresh_accounts with force flag clears cache."""
        wallets_screen.balance_cache["gnosis"] = {ADDR_EOA: {"NATIVE": "1.0"}}
        with (
            patch.object(wallets_screen, "refresh_table_structure_and_data"),
            patch.object(wallets_screen, "load_recent_txs"),
        ):
            wallets_screen.refresh_accounts(force=True)
            assert wallets_screen.balance_cache["gnosis"] == {}

    def test_refresh_accounts_force_missing_chain(self, wallets_screen):
        """Test force refresh with chain not in cache."""
        wallets_screen.balance_cache = {}
        with (
            patch.object(wallets_screen, "refresh_table_structure_and_data"),
            patch.object(wallets_screen, "load_recent_txs"),
        ):
            wallets_screen.refresh_accounts(force=True)
            # Should not raise even when chain not in cache


# ===========================================================================
# Tests for _build_account_row
# ===========================================================================

class TestBuildAccountRow:
    """Test _build_account_row logic."""

    def test_eoa_account_cached(self, wallets_screen):
        """Test building row for EOA with cached balance."""
        acct = _make_stored_account(ADDR_EOA, "MyEOA")
        wallets_screen.balance_cache["gnosis"] = {
            ADDR_EOA: {"NATIVE": "1.2345"}
        }
        cells, needs_fetch = wallets_screen._build_account_row(acct, "gnosis", [])
        assert len(cells) == 4
        assert cells[2] == "EOA"
        assert cells[3] == "1.2345"
        assert needs_fetch is False

    def test_eoa_account_no_cache(self, wallets_screen):
        """Test building row for EOA without cached balance."""
        acct = _make_stored_account(ADDR_EOA, "MyEOA")
        wallets_screen.balance_cache["gnosis"] = {}
        cells, needs_fetch = wallets_screen._build_account_row(acct, "gnosis", [])
        assert cells[3] == "Loading..."
        assert needs_fetch is True

    def test_safe_account_on_chain(self, wallets_screen):
        """Test building row for Safe that is on the current chain."""
        acct = _make_safe_account(ADDR_SAFE, "MySafe", ["gnosis", "ethereum"])
        wallets_screen.balance_cache["gnosis"] = {}
        cells, needs_fetch = wallets_screen._build_account_row(acct, "gnosis", [])
        assert len(cells) == 4
        assert cells[2] == "Safe"

    def test_safe_account_not_on_chain(self, wallets_screen):
        """Test building row for Safe that is NOT on the current chain."""
        acct = _make_safe_account(ADDR_SAFE, "MySafe", ["ethereum"])
        wallets_screen.balance_cache["gnosis"] = {}
        cells, needs_fetch = wallets_screen._build_account_row(acct, "gnosis", [])
        assert cells == []
        assert needs_fetch is False

    def test_token_columns_cached(self, wallets_screen):
        """Test token columns with cached data."""
        acct = _make_stored_account(ADDR_EOA, "MyEOA")
        wallets_screen.chain_token_states["gnosis"] = {"OLAS"}
        wallets_screen.balance_cache["gnosis"] = {
            ADDR_EOA: {"NATIVE": "1.0", "OLAS": "99.0"}
        }
        cells, needs_fetch = wallets_screen._build_account_row(acct, "gnosis", ["OLAS", "GNO"])
        # 4 base + 2 tokens
        assert len(cells) == 6
        assert cells[4] == "99.0"  # OLAS (tracked, cached)
        assert cells[5] == ""  # GNO (not tracked)
        assert needs_fetch is False

    def test_token_columns_loading(self, wallets_screen):
        """Test token columns needing fetch."""
        acct = _make_stored_account(ADDR_EOA, "MyEOA")
        wallets_screen.chain_token_states["gnosis"] = {"OLAS"}
        wallets_screen.balance_cache["gnosis"] = {ADDR_EOA: {"NATIVE": "1.0"}}
        cells, needs_fetch = wallets_screen._build_account_row(acct, "gnosis", ["OLAS"])
        assert cells[4] == "Loading..."
        assert needs_fetch is True


# ===========================================================================
# Tests for refresh_table_structure_and_data
# ===========================================================================

class TestRefreshTableStructureAndData:
    """Test refresh_table_structure_and_data."""

    def test_basic_flow(self, wallets_screen):
        """Test the basic refresh flow."""
        mock_table = MagicMock()
        wallets_screen.query_one.return_value = mock_table

        mock_interface = _make_chain_interface()
        with patch("iwa.tui.screens.wallets.ChainInterfaces") as mock_ci:
            mock_ci.return_value.get.return_value = mock_interface
            with patch.object(wallets_screen, "fetch_all_balances"):
                wallets_screen.refresh_table_structure_and_data()

        mock_table.setup_columns.assert_called_once()
        # Should have been called with accounts
        assert mock_table.add_row.called or not wallets_screen.wallet.account_service.get_account_data.return_value

    def test_adds_rows_for_accounts(self, wallets_screen):
        """Test that rows are added for each account."""
        eoa = _make_stored_account(ADDR_EOA, "MyEOA")
        wallets_screen.wallet.account_service.get_account_data.return_value = {
            ADDR_EOA: eoa,
        }

        mock_table = MagicMock()
        wallets_screen.query_one.return_value = mock_table

        mock_interface = _make_chain_interface(tokens={})
        with patch("iwa.tui.screens.wallets.ChainInterfaces") as mock_ci:
            mock_ci.return_value.get.return_value = mock_interface
            with patch.object(wallets_screen, "fetch_all_balances"):
                wallets_screen.refresh_table_structure_and_data()

        mock_table.add_row.assert_called_once()

    def test_handles_account_error(self, wallets_screen):
        """Test that errors from individual accounts don't crash."""
        bad_acct = MagicMock()
        bad_acct.address = ADDR_EOA
        # _build_account_row will fail because bad_acct can't determine type
        wallets_screen.wallet.account_service.get_account_data.return_value = {
            ADDR_EOA: bad_acct,
        }

        mock_table = MagicMock()
        wallets_screen.query_one.return_value = mock_table

        mock_interface = _make_chain_interface(tokens={})
        with patch("iwa.tui.screens.wallets.ChainInterfaces") as mock_ci:
            mock_ci.return_value.get.return_value = mock_interface
            with patch.object(wallets_screen, "_build_account_row", side_effect=Exception("boom")):
                with patch.object(wallets_screen, "fetch_all_balances"):
                    # Should not raise
                    wallets_screen.refresh_table_structure_and_data()

    def test_no_interface(self, wallets_screen):
        """Test when chain interface is None."""
        mock_table = MagicMock()
        wallets_screen.query_one.return_value = mock_table

        with patch("iwa.tui.screens.wallets.ChainInterfaces") as mock_ci:
            mock_ci.return_value.get.return_value = None
            with patch.object(wallets_screen, "fetch_all_balances"):
                wallets_screen.refresh_table_structure_and_data()

        mock_table.setup_columns.assert_called_once_with("gnosis", "Native", [])


# ===========================================================================
# Tests for check_balance_loading_status
# ===========================================================================

class TestCheckBalanceLoadingStatus:
    """Test check_balance_loading_status."""

    def test_skip_if_chain_changed(self, wallets_screen):
        """Test that it skips if active chain changed."""
        wallets_screen.active_chain = "ethereum"
        with patch.object(wallets_screen, "fetch_all_balances") as mock_fetch:
            wallets_screen.check_balance_loading_status("gnosis")
            mock_fetch.assert_not_called()

    def test_needs_retry_missing_chain(self, wallets_screen):
        """Test that it retries when chain not in cache."""
        eoa = _make_stored_account(ADDR_EOA, "MyEOA")
        wallets_screen.wallet.account_service.get_account_data.return_value = {ADDR_EOA: eoa}
        wallets_screen.balance_cache = {}  # empty

        with (
            patch("iwa.tui.screens.wallets.ChainInterfaces") as mock_ci,
            patch.object(wallets_screen, "fetch_all_balances") as mock_fetch,
        ):
            mock_ci.return_value.get.return_value = _make_chain_interface()
            wallets_screen.check_balance_loading_status("gnosis")
            mock_fetch.assert_called_once()

    def test_needs_retry_loading_native(self, wallets_screen):
        """Test that it retries when native balance is still loading."""
        eoa = _make_stored_account(ADDR_EOA, "MyEOA")
        wallets_screen.wallet.account_service.get_account_data.return_value = {ADDR_EOA: eoa}
        wallets_screen.balance_cache = {"gnosis": {ADDR_EOA: {"NATIVE": "Loading..."}}}

        with (
            patch("iwa.tui.screens.wallets.ChainInterfaces") as mock_ci,
            patch.object(wallets_screen, "fetch_all_balances") as mock_fetch,
        ):
            mock_ci.return_value.get.return_value = _make_chain_interface()
            wallets_screen.check_balance_loading_status("gnosis")
            mock_fetch.assert_called_once()

    def test_needs_retry_token_loading(self, wallets_screen):
        """Test that it retries when token balance is still loading."""
        eoa = _make_stored_account(ADDR_EOA, "MyEOA")
        wallets_screen.wallet.account_service.get_account_data.return_value = {ADDR_EOA: eoa}
        wallets_screen.chain_token_states["gnosis"] = {"OLAS"}
        wallets_screen.balance_cache = {
            "gnosis": {ADDR_EOA: {"NATIVE": "1.0", "OLAS": "Loading..."}}
        }

        with (
            patch("iwa.tui.screens.wallets.ChainInterfaces") as mock_ci,
            patch.object(wallets_screen, "fetch_all_balances") as mock_fetch,
        ):
            mock_ci.return_value.get.return_value = _make_chain_interface()
            wallets_screen.check_balance_loading_status("gnosis")
            mock_fetch.assert_called_once()

    def test_no_retry_when_all_loaded(self, wallets_screen):
        """Test that it does not retry when all balances loaded."""
        eoa = _make_stored_account(ADDR_EOA, "MyEOA")
        wallets_screen.wallet.account_service.get_account_data.return_value = {ADDR_EOA: eoa}
        wallets_screen.balance_cache = {"gnosis": {ADDR_EOA: {"NATIVE": "1.0"}}}

        with (
            patch("iwa.tui.screens.wallets.ChainInterfaces") as mock_ci,
            patch.object(wallets_screen, "fetch_all_balances") as mock_fetch,
        ):
            mock_ci.return_value.get.return_value = _make_chain_interface()
            wallets_screen.check_balance_loading_status("gnosis")
            mock_fetch.assert_not_called()

    def test_needs_retry_address_missing_from_cache(self, wallets_screen):
        """Test retry when address not in balance cache."""
        eoa = _make_stored_account(ADDR_EOA, "MyEOA")
        wallets_screen.wallet.account_service.get_account_data.return_value = {ADDR_EOA: eoa}
        wallets_screen.balance_cache = {"gnosis": {}}  # chain present, addr missing

        with (
            patch("iwa.tui.screens.wallets.ChainInterfaces") as mock_ci,
            patch.object(wallets_screen, "fetch_all_balances") as mock_fetch,
        ):
            mock_ci.return_value.get.return_value = _make_chain_interface()
            wallets_screen.check_balance_loading_status("gnosis")
            mock_fetch.assert_called_once()


# ===========================================================================
# Tests for _fetch_account_all_balances
# ===========================================================================

class TestFetchAccountAllBalances:
    """Test _fetch_account_all_balances."""

    def test_calls_native_and_token(self, wallets_screen):
        """Test that it calls both native and token fetchers."""
        with (
            patch.object(wallets_screen, "_fetch_account_native_balance") as mock_native,
            patch.object(wallets_screen, "_fetch_account_token_balances") as mock_tokens,
        ):
            wallets_screen._fetch_account_all_balances(ADDR_EOA, "gnosis", ["OLAS"])
            mock_native.assert_called_once_with(ADDR_EOA, "gnosis")
            mock_tokens.assert_called_once_with(ADDR_EOA, "gnosis", ["OLAS"])


# ===========================================================================
# Tests for _fetch_account_native_balance
# ===========================================================================

class TestFetchAccountNativeBalance:
    """Test _fetch_account_native_balance."""

    def test_fetches_when_no_cache(self, wallets_screen):
        """Test fetching native balance when not cached."""
        wallets_screen.balance_cache = {"gnosis": {ADDR_EOA: {}}}
        wallets_screen.wallet.balance_service.get_native_balance_eth.return_value = 1.5

        wallets_screen._fetch_account_native_balance(ADDR_EOA, "gnosis")

        wallets_screen.wallet.balance_service.get_native_balance_eth.assert_called_once_with(
            ADDR_EOA, chain_name="gnosis"
        )
        assert wallets_screen.balance_cache["gnosis"][ADDR_EOA]["NATIVE"] == "1.5000"
        wallets_screen.app.call_from_thread.assert_called_once()

    def test_skips_when_cached(self, wallets_screen):
        """Test skipping fetch when balance already cached."""
        wallets_screen.balance_cache = {"gnosis": {ADDR_EOA: {"NATIVE": "2.0000"}}}

        wallets_screen._fetch_account_native_balance(ADDR_EOA, "gnosis")

        wallets_screen.wallet.balance_service.get_native_balance_eth.assert_not_called()
        wallets_screen.app.call_from_thread.assert_called_once()

    def test_refetches_when_loading(self, wallets_screen):
        """Test refetching when cached value is 'Loading...'."""
        wallets_screen.balance_cache = {"gnosis": {ADDR_EOA: {"NATIVE": "Loading..."}}}
        wallets_screen.wallet.balance_service.get_native_balance_eth.return_value = 3.14

        wallets_screen._fetch_account_native_balance(ADDR_EOA, "gnosis")

        wallets_screen.wallet.balance_service.get_native_balance_eth.assert_called_once()
        assert wallets_screen.balance_cache["gnosis"][ADDR_EOA]["NATIVE"] == "3.1400"

    def test_handles_none_balance(self, wallets_screen):
        """Test handling when balance returns None."""
        wallets_screen.balance_cache = {"gnosis": {ADDR_EOA: {}}}
        wallets_screen.wallet.balance_service.get_native_balance_eth.return_value = None

        wallets_screen._fetch_account_native_balance(ADDR_EOA, "gnosis")

        # Should store "Error" when balance is None
        assert wallets_screen.balance_cache["gnosis"][ADDR_EOA]["NATIVE"] == "Error"

    def test_handles_exception(self, wallets_screen):
        """Test handling balance fetch exception."""
        wallets_screen.balance_cache = {"gnosis": {ADDR_EOA: {}}}
        wallets_screen.wallet.balance_service.get_native_balance_eth.side_effect = Exception("RPC down")

        wallets_screen._fetch_account_native_balance(ADDR_EOA, "gnosis")

        # call_from_thread should still be called with Error value
        wallets_screen.app.call_from_thread.assert_called_once()

    def test_creates_cache_structure(self, wallets_screen):
        """Test that cache structure is created if missing."""
        wallets_screen.balance_cache = {}
        wallets_screen.wallet.balance_service.get_native_balance_eth.return_value = 1.0

        wallets_screen._fetch_account_native_balance(ADDR_EOA, "gnosis")

        assert "gnosis" in wallets_screen.balance_cache
        assert ADDR_EOA in wallets_screen.balance_cache["gnosis"]


# ===========================================================================
# Tests for _fetch_account_token_balances
# ===========================================================================

class TestFetchAccountTokenBalances:
    """Test _fetch_account_token_balances."""

    def test_skips_untracked_token(self, wallets_screen):
        """Test that untracked tokens are skipped."""
        wallets_screen.chain_token_states["gnosis"] = set()  # nothing tracked

        with patch("iwa.tui.screens.wallets.ChainInterfaces") as mock_ci:
            mock_ci.return_value.get.return_value = _make_chain_interface()
            wallets_screen._fetch_account_token_balances(ADDR_EOA, "gnosis", ["OLAS"])

        wallets_screen.app.call_from_thread.assert_not_called()

    def test_fetches_tracked_token(self, wallets_screen):
        """Test fetching a tracked token balance."""
        wallets_screen.chain_token_states["gnosis"] = {"OLAS"}

        with (
            patch("iwa.tui.screens.wallets.ChainInterfaces") as mock_ci,
            patch.object(wallets_screen, "_fetch_single_token_balance", return_value="100.0000"),
        ):
            mock_ci.return_value.get.return_value = _make_chain_interface()
            wallets_screen._fetch_account_token_balances(ADDR_EOA, "gnosis", ["OLAS"])

        wallets_screen.app.call_from_thread.assert_called_once()

    def test_skips_unknown_token_index(self, wallets_screen):
        """Test that ValueError from index() is caught."""
        wallets_screen.chain_token_states["gnosis"] = {"UNKNOWN_TOKEN"}

        with patch("iwa.tui.screens.wallets.ChainInterfaces") as mock_ci:
            # tokens dict doesn't include UNKNOWN_TOKEN
            mock_ci.return_value.get.return_value = _make_chain_interface(tokens={"OLAS": MagicMock()})
            wallets_screen._fetch_account_token_balances(ADDR_EOA, "gnosis", ["UNKNOWN_TOKEN"])

        wallets_screen.app.call_from_thread.assert_not_called()


# ===========================================================================
# Tests for _fetch_single_token_balance
# ===========================================================================

class TestFetchSingleTokenBalance:
    """Test _fetch_single_token_balance."""

    def test_returns_formatted_balance(self, wallets_screen):
        """Test formatting a successful balance."""
        wallets_screen.balance_cache = {"gnosis": {ADDR_EOA: {}}}
        wallets_screen.wallet.balance_service.get_erc20_balance_eth.return_value = 99.1234

        result = wallets_screen._fetch_single_token_balance(ADDR_EOA, "OLAS", "gnosis")

        assert result == "99.1234"
        assert wallets_screen.balance_cache["gnosis"][ADDR_EOA]["OLAS"] == "99.1234"

    def test_returns_dash_on_none(self, wallets_screen):
        """Test returning '-' when balance is None."""
        wallets_screen.balance_cache = {"gnosis": {ADDR_EOA: {}}}
        wallets_screen.wallet.balance_service.get_erc20_balance_eth.return_value = None

        result = wallets_screen._fetch_single_token_balance(ADDR_EOA, "OLAS", "gnosis")

        assert result == "-"
        # Should not cache None result
        assert "OLAS" not in wallets_screen.balance_cache["gnosis"][ADDR_EOA]

    def test_creates_cache_structure_if_missing(self, wallets_screen):
        """Test cache structure creation."""
        wallets_screen.balance_cache = {}
        wallets_screen.wallet.balance_service.get_erc20_balance_eth.return_value = 50.0

        result = wallets_screen._fetch_single_token_balance(ADDR_EOA, "OLAS", "gnosis")

        assert result == "50.0000"
        assert wallets_screen.balance_cache["gnosis"][ADDR_EOA]["OLAS"] == "50.0000"


# ===========================================================================
# Tests for resolve_tag
# ===========================================================================

class TestResolveTag:
    """Test resolve_tag."""

    def test_resolves_known_account(self, wallets_screen):
        """Test resolving address to account tag."""
        eoa = _make_stored_account(ADDR_EOA, "MyEOA")
        wallets_screen.wallet.account_service.get_account_data.return_value = {ADDR_EOA: eoa}

        result = wallets_screen.resolve_tag(ADDR_EOA)
        assert result == "MyEOA"

    def test_resolves_whitelist(self, wallets_screen):
        """Test resolving address from config whitelist."""
        wallets_screen.wallet.account_service.get_account_data.return_value = {}

        with patch("iwa.tui.screens.wallets.Config") as mock_config_cls:
            mock_config = MagicMock()
            mock_config.core.whitelist = {"Recipient": ADDR_EXTERNAL}
            mock_config_cls.return_value = mock_config

            result = wallets_screen.resolve_tag(ADDR_EXTERNAL)
            assert result == "Recipient"

    def test_truncates_unknown_address(self, wallets_screen):
        """Test truncating unknown addresses."""
        wallets_screen.wallet.account_service.get_account_data.return_value = {}

        with patch("iwa.tui.screens.wallets.Config") as mock_config_cls:
            mock_config = MagicMock()
            mock_config.core = None
            mock_config_cls.return_value = mock_config

            result = wallets_screen.resolve_tag(ADDR_EXTERNAL)
            assert result == f"{ADDR_EXTERNAL[:6]}...{ADDR_EXTERNAL[-4:]}"

    def test_resolves_case_insensitive(self, wallets_screen):
        """Test case-insensitive address matching."""
        eoa = _make_stored_account(ADDR_EOA, "MyEOA")
        wallets_screen.wallet.account_service.get_account_data.return_value = {ADDR_EOA: eoa}

        result = wallets_screen.resolve_tag(ADDR_EOA.upper())
        assert result == "MyEOA"


# ===========================================================================
# Tests for add_tx_history_row
# ===========================================================================

class TestAddTxHistoryRow:
    """Test add_tx_history_row."""

    def test_adds_row(self, wallets_screen):
        """Test adding a transaction row."""
        mock_table = MagicMock()
        wallets_screen.query_one.return_value = mock_table

        with patch.object(wallets_screen, "resolve_tag", side_effect=lambda x: x[:6]):
            wallets_screen.add_tx_history_row(
                ADDR_EOA, ADDR_EXTERNAL, "xDAI", "1.0", "Pending", "0xabc123"
            )

        mock_table.add_row.assert_called_once()
        mock_table.sort.assert_called_once_with("Time", reverse=True)

    def test_handles_sort_error(self, wallets_screen):
        """Test that sort errors are silently caught."""
        mock_table = MagicMock()
        mock_table.sort.side_effect = Exception("sort fail")
        wallets_screen.query_one.return_value = mock_table

        with patch.object(wallets_screen, "resolve_tag", return_value="tag"):
            # Should not raise
            wallets_screen.add_tx_history_row(
                ADDR_EOA, ADDR_EXTERNAL, "xDAI", "1.0", "Pending", "0xabc"
            )

    def test_empty_tx_hash(self, wallets_screen):
        """Test adding row with empty tx_hash."""
        mock_table = MagicMock()
        wallets_screen.query_one.return_value = mock_table

        with patch.object(wallets_screen, "resolve_tag", return_value="tag"):
            wallets_screen.add_tx_history_row(
                ADDR_EOA, ADDR_EXTERNAL, "xDAI", "1.0", "Detected", ""
            )

        mock_table.add_row.assert_called_once()


# ===========================================================================
# Tests for stop_monitor
# ===========================================================================

class TestStopMonitor:
    """Test stop_monitor."""

    def test_stops_all_workers(self, wallets_screen):
        """Test that all monitor workers are stopped."""
        w1, w2 = MagicMock(), MagicMock()
        wallets_screen.monitor_workers = [w1, w2]

        wallets_screen.stop_monitor()

        w1.stop.assert_called_once()
        w2.stop.assert_called_once()
        assert wallets_screen.monitor_workers == []


# ===========================================================================
# Tests for monitor_callback
# ===========================================================================

class TestMonitorCallback:
    """Test monitor_callback."""

    def test_calls_handle_new_txs_from_thread(self, wallets_screen):
        """Test that monitor_callback delegates to app.call_from_thread."""
        txs = [{"hash": "0xabc", "from": ADDR_EOA, "to": ADDR_EXTERNAL}]
        wallets_screen.monitor_callback(txs)
        wallets_screen.app.call_from_thread.assert_called_once_with(
            wallets_screen.handle_new_txs, txs
        )


# ===========================================================================
# Tests for handle_new_txs
# ===========================================================================

class TestHandleNewTxs:
    """Test handle_new_txs."""

    def test_processes_transactions(self, wallets_screen):
        """Test processing new transactions."""
        tx = {
            "hash": "0xabcdef1234567890",
            "from": ADDR_EXTERNAL,
            "to": ADDR_EOA,
            "value": str(10**18),
            "timestamp": time.time(),
        }

        with (
            patch.object(wallets_screen, "refresh_accounts"),
            patch.object(wallets_screen, "add_tx_history_row"),
            patch.object(wallets_screen, "enrich_and_log_txs"),
        ):
            wallets_screen.handle_new_txs([tx])
            wallets_screen.notify.assert_called()

    def test_no_notify_for_outgoing(self, wallets_screen):
        """Test that outgoing transactions don't trigger notification."""
        eoa = _make_stored_account(ADDR_EOA, "MyEOA")
        wallets_screen.wallet.account_service.get_account_data.return_value = {ADDR_EOA: eoa}

        tx = {
            "hash": "0xabcdef1234567890",
            "from": ADDR_EOA,
            "to": ADDR_EXTERNAL,
            "value": str(10**18),
            "timestamp": time.time(),
        }

        with (
            patch.object(wallets_screen, "refresh_accounts"),
            patch.object(wallets_screen, "add_tx_history_row"),
            patch.object(wallets_screen, "enrich_and_log_txs"),
        ):
            wallets_screen.handle_new_txs([tx])
            # notify should NOT be called for outgoing tx
            wallets_screen.notify.assert_not_called()

    def test_handles_missing_timestamp(self, wallets_screen):
        """Test handling tx with missing timestamp."""
        tx = {
            "hash": "0xabcdef1234567890",
            "from": ADDR_EXTERNAL,
            "to": ADDR_EOA,
            "value": "0",
        }

        with (
            patch.object(wallets_screen, "refresh_accounts"),
            patch.object(wallets_screen, "add_tx_history_row"),
            patch.object(wallets_screen, "enrich_and_log_txs"),
        ):
            wallets_screen.handle_new_txs([tx])


# ===========================================================================
# Tests for on_button_pressed
# ===========================================================================

class TestOnButtonPressed:
    """Test button press handling."""

    def test_create_eoa_button(self, wallets_screen):
        """Test pressing Create EOA button."""
        event = MagicMock()
        event.button.id = "create_eoa_btn"

        wallets_screen.on_button_pressed(event)

        wallets_screen.app.push_screen.assert_called_once()

    def test_create_safe_button(self, wallets_screen):
        """Test pressing Create Safe button."""
        event = MagicMock()
        event.button.id = "create_safe_btn"

        wallets_screen.on_button_pressed(event)

        wallets_screen.app.push_screen.assert_called_once()

    def test_send_button(self, wallets_screen):
        """Test pressing Send button."""
        event = MagicMock()
        event.button.id = "send_btn"

        with patch.object(wallets_screen, "send_transaction") as mock_send:
            wallets_screen.on_button_pressed(event)
            mock_send.assert_called_once()


# ===========================================================================
# Tests for send_transaction
# ===========================================================================

class TestSendTransaction:
    """Test send_transaction."""

    def test_sends_when_all_fields_present(self, wallets_screen):
        """Test successful send initiation."""
        mock_from = MagicMock()
        mock_from.value = ADDR_EOA
        mock_to = MagicMock()
        mock_to.value = ADDR_EXTERNAL
        mock_amount = MagicMock()
        mock_amount.value = "1.5"
        mock_token = MagicMock()
        mock_token.value = "native"

        def query_side_effect(selector, cls=None):
            mapping = {
                "#from_addr": mock_from,
                "#to_addr": mock_to,
                "#amount": mock_amount,
                "#token": mock_token,
            }
            return mapping.get(selector, MagicMock())

        wallets_screen.query_one = MagicMock(side_effect=query_side_effect)

        with patch.object(wallets_screen, "send_tx_worker") as mock_worker:
            wallets_screen.send_transaction()
            mock_worker.assert_called_once_with(ADDR_EOA, ADDR_EXTERNAL, "native", 1.5)

    def test_missing_fields(self, wallets_screen):
        """Test error when fields are missing."""
        mock_from = MagicMock()
        mock_from.value = ADDR_EOA
        mock_to = MagicMock()
        mock_to.value = None  # missing
        mock_amount = MagicMock()
        mock_amount.value = "1.0"
        mock_token = MagicMock()
        mock_token.value = "native"

        def query_side_effect(selector, cls=None):
            mapping = {
                "#from_addr": mock_from,
                "#to_addr": mock_to,
                "#amount": mock_amount,
                "#token": mock_token,
            }
            return mapping.get(selector, MagicMock())

        wallets_screen.query_one = MagicMock(side_effect=query_side_effect)

        wallets_screen.send_transaction()
        wallets_screen.notify.assert_called_with("Missing fields", severity="error")

    def test_handles_query_exception(self, wallets_screen):
        """Test graceful handling of query exceptions."""
        wallets_screen.query_one = MagicMock(side_effect=Exception("widget not found"))

        # Should not raise
        wallets_screen.send_transaction()


# ===========================================================================
# Tests for update_table_cell
# ===========================================================================

class TestUpdateTableCell:
    """Test update_table_cell."""

    def test_updates_cell(self, wallets_screen):
        """Test updating a specific cell."""
        mock_table = MagicMock()
        mock_col_keys = ["Tag", "Address", "Type", "Balance"]
        mock_table.columns.keys.return_value = mock_col_keys
        wallets_screen.query_one.return_value = mock_table

        wallets_screen.update_table_cell(ADDR_EOA, 3, Text("1.0"))

        mock_table.update_cell.assert_called_once()

    def test_handles_exception(self, wallets_screen):
        """Test that exceptions are silently caught."""
        wallets_screen.query_one.side_effect = Exception("no table")

        # Should not raise
        wallets_screen.update_table_cell(ADDR_EOA, 0, "value")


# ===========================================================================
# Tests for on_account_cell_selected
# ===========================================================================

class TestOnAccountCellSelected:
    """Test on_account_cell_selected."""

    def test_copies_address_from_column_1(self, wallets_screen):
        """Test copying address when clicking column 1."""
        event = MagicMock()
        event.coordinate.column = 1
        event.value = MagicMock()
        event.value.plain = ADDR_EOA

        wallets_screen.on_account_cell_selected(event)

        wallets_screen.app.copy_to_clipboard.assert_called_once_with(ADDR_EOA)
        wallets_screen.notify.assert_called_once_with("Copied address to clipboard")

    def test_ignores_other_columns(self, wallets_screen):
        """Test that other columns don't trigger copy."""
        event = MagicMock()
        event.coordinate.column = 0

        wallets_screen.on_account_cell_selected(event)

        wallets_screen.app.copy_to_clipboard.assert_not_called()

    def test_handles_non_rich_text_value(self, wallets_screen):
        """Test handling plain string value (no .plain attribute)."""
        event = MagicMock()
        event.coordinate.column = 1
        # Use a real string — it has no .plain attribute, triggering the else branch
        event.value = ADDR_EOA

        wallets_screen.on_account_cell_selected(event)

        wallets_screen.app.copy_to_clipboard.assert_called_once_with(ADDR_EOA)


# ===========================================================================
# Tests for on_tx_cell_selected
# ===========================================================================

class TestOnTxCellSelected:
    """Test on_tx_cell_selected."""

    def test_copies_hash_from_hash_column(self, wallets_screen):
        """Test copying tx hash from Hash column."""
        event = MagicMock()
        event.coordinate.column = 2
        mock_col = MagicMock()
        mock_col.label = "Hash"
        event.data_table.columns.values.return_value = [MagicMock(), MagicMock(), mock_col]
        event.cell_key.row_key.value = "0xabcdef1234567890"

        wallets_screen.on_tx_cell_selected(event)

        wallets_screen.app.copy_to_clipboard.assert_called_once_with("0xabcdef1234567890")

    def test_ignores_non_hash_column(self, wallets_screen):
        """Test that non-Hash columns are ignored."""
        event = MagicMock()
        event.coordinate.column = 0
        mock_col = MagicMock()
        mock_col.label = "Time"
        event.data_table.columns.values.return_value = [mock_col]

        wallets_screen.on_tx_cell_selected(event)

        wallets_screen.app.copy_to_clipboard.assert_not_called()

    def test_handles_exception(self, wallets_screen):
        """Test that exceptions are silently caught."""
        event = MagicMock()
        event.data_table.columns.values.side_effect = Exception("oops")

        # Should not raise
        wallets_screen.on_tx_cell_selected(event)


# ===========================================================================
# Tests for on_checkbox_changed
# ===========================================================================

class TestOnCheckboxChanged:
    """Test on_checkbox_changed."""

    def test_tracks_token_on_check(self, wallets_screen):
        """Test that checking a checkbox adds token to tracked set."""
        event = MagicMock()
        event.checkbox.id = "cb_OLAS"
        event.value = True

        with patch.object(wallets_screen, "fetch_all_balances"):
            wallets_screen.on_checkbox_changed(event)

        assert "OLAS" in wallets_screen.chain_token_states["gnosis"]

    def test_untracks_token_on_uncheck(self, wallets_screen):
        """Test that unchecking removes token from tracked set."""
        wallets_screen.chain_token_states["gnosis"] = {"OLAS"}
        event = MagicMock()
        event.checkbox.id = "cb_OLAS"
        event.value = False

        with patch.object(wallets_screen, "refresh_table_structure_and_data"):
            wallets_screen.on_checkbox_changed(event)

        assert "OLAS" not in wallets_screen.chain_token_states["gnosis"]

    def test_ignores_non_token_checkbox(self, wallets_screen):
        """Test that non-token checkboxes are ignored."""
        event = MagicMock()
        event.checkbox.id = "some_other_cb"

        wallets_screen.on_checkbox_changed(event)
        # No error, no state change

    def test_ignores_checkbox_without_id(self, wallets_screen):
        """Test that checkboxes without id are ignored."""
        event = MagicMock()
        event.checkbox.id = None

        wallets_screen.on_checkbox_changed(event)

    def test_creates_chain_state_if_missing(self, wallets_screen):
        """Test that chain token state dict is created if missing."""
        wallets_screen.chain_token_states = {}
        wallets_screen.active_chain = "gnosis"
        event = MagicMock()
        event.checkbox.id = "cb_OLAS"
        event.value = True

        with patch.object(wallets_screen, "fetch_all_balances"):
            wallets_screen.on_checkbox_changed(event)

        assert "OLAS" in wallets_screen.chain_token_states["gnosis"]


# ===========================================================================
# Tests for on_unmount
# ===========================================================================

class TestOnUnmount:
    """Test on_unmount."""

    def test_stops_monitor(self, wallets_screen):
        """Test that unmounting stops the monitor."""
        with patch.object(wallets_screen, "stop_monitor") as mock_stop:
            wallets_screen.on_unmount()
            mock_stop.assert_called_once()


# ===========================================================================
# Tests for start_monitor
# ===========================================================================

class TestStartMonitor:
    """Test start_monitor."""

    def test_starts_monitors_for_chains(self, wallets_screen):
        """Test that monitors are started for available chains."""
        eoa = _make_stored_account(ADDR_EOA, "MyEOA")
        wallets_screen.wallet.key_storage.accounts.values.return_value = [eoa]

        mock_interface = _make_chain_interface()
        chain_items = [("gnosis", mock_interface)]

        with (
            patch("iwa.tui.screens.wallets.ChainInterfaces") as mock_ci,
            patch("iwa.tui.screens.wallets.EventMonitor") as mock_em,
            patch("iwa.tui.screens.wallets.MonitorWorker") as mock_mw,
            patch.object(wallets_screen, "stop_monitor"),
        ):
            mock_ci.return_value.items.return_value = chain_items
            wallets_screen.start_monitor()

        assert len(wallets_screen.monitor_workers) == 1

    def test_skips_chain_without_rpc(self, wallets_screen):
        """Test that chains without RPC are skipped."""
        eoa = _make_stored_account(ADDR_EOA, "MyEOA")
        wallets_screen.wallet.key_storage.accounts.values.return_value = [eoa]

        mock_interface = MagicMock()
        mock_interface.current_rpc = None

        with (
            patch("iwa.tui.screens.wallets.ChainInterfaces") as mock_ci,
            patch.object(wallets_screen, "stop_monitor"),
        ):
            mock_ci.return_value.items.return_value = [("ethereum", mock_interface)]
            wallets_screen.start_monitor()

        assert len(wallets_screen.monitor_workers) == 0


# ===========================================================================
# Tests for load_recent_txs
# ===========================================================================

class TestLoadRecentTxs:
    """Test load_recent_txs."""

    def test_handles_db_error(self, wallets_screen):
        """Test that database errors are caught."""
        with patch("iwa.tui.screens.wallets.WalletsScreen.load_recent_txs") as mock_load:
            mock_load.side_effect = Exception("db error")
            # Actually test the real method
            pass

        # Test the actual error handling
        mock_table = MagicMock()
        wallets_screen.query_one.return_value = mock_table

        with patch.dict("sys.modules", {"iwa.core.db": MagicMock(side_effect=ImportError)}):
            # The try/except in load_recent_txs will catch this
            wallets_screen.load_recent_txs()

    def test_loads_transactions(self, wallets_screen):
        """Test loading transactions from database."""
        mock_table = MagicMock()
        wallets_screen.query_one.return_value = mock_table

        mock_tx = MagicMock()
        mock_tx.timestamp = datetime.datetime.now()
        mock_tx.from_tag = "sender"
        mock_tx.from_address = ADDR_EOA
        mock_tx.to_tag = "receiver"
        mock_tx.to_address = ADDR_EXTERNAL
        mock_tx.token = "NATIVE"
        mock_tx.chain = "gnosis"
        mock_tx.amount_wei = str(10**18)
        mock_tx.value_eur = 1.5
        mock_tx.gas_value_eur = 0.001
        mock_tx.gas_cost = "21000"
        mock_tx.tx_hash = "0xabcdef1234567890"
        mock_tx.tags = None

        # Mock the SentTransaction model — the import happens inside load_recent_txs
        # Use _FieldMock for timestamp and chain so Peewee-style comparisons
        # (e.g. SentTransaction.timestamp > datetime) work without TypeError.
        mock_sent_tx = MagicMock()
        mock_sent_tx.timestamp = _FieldMock()
        mock_sent_tx.chain = _FieldMock()
        mock_sent_tx.select.return_value.where.return_value.order_by.return_value = [mock_tx]

        with (
            patch("iwa.core.db.SentTransaction", mock_sent_tx),
            patch("iwa.tui.screens.wallets.ChainInterfaces") as mock_ci,
        ):
            mock_ci.return_value.get.return_value = _make_chain_interface()
            wallets_screen.load_recent_txs()

        mock_table.clear.assert_called_once()
        mock_table.add_row.assert_called_once()
