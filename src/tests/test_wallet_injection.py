"""Tests for wallet injection in web dependencies."""

from unittest.mock import MagicMock, patch


class TestWalletInjection:
    """Tests for get_wallet, set_wallet, and _WalletProxy."""

    def setup_method(self):
        """Reset the global wallet state before each test."""
        # Import fresh to reset state
        import iwa.web.dependencies as deps

        deps._wallet = None

    def test_get_wallet_lazy_initialization(self):
        """get_wallet() creates a Wallet on first call if none injected."""
        import iwa.web.dependencies as deps

        deps._wallet = None

        with patch.object(deps, "Wallet") as mock_wallet_cls:
            mock_wallet_cls.return_value = MagicMock(name="LazyWallet")

            result = deps.get_wallet()

            mock_wallet_cls.assert_called_once()
            assert result == mock_wallet_cls.return_value

    def test_get_wallet_returns_same_instance(self):
        """get_wallet() returns the same instance on subsequent calls."""
        import iwa.web.dependencies as deps

        deps._wallet = None

        with patch.object(deps, "Wallet") as mock_wallet_cls:
            mock_wallet_cls.return_value = MagicMock(name="SingletonWallet")

            first = deps.get_wallet()
            second = deps.get_wallet()

            # Should only create once
            mock_wallet_cls.assert_called_once()
            assert first is second

    def test_set_wallet_injects_external_wallet(self):
        """set_wallet() allows injecting an external wallet instance."""
        import iwa.web.dependencies as deps

        deps._wallet = None

        external_wallet = MagicMock(name="ExternalWallet")
        deps.set_wallet(external_wallet)

        result = deps.get_wallet()

        assert result is external_wallet

    def test_set_wallet_prevents_lazy_init(self):
        """set_wallet() prevents Wallet() from being called."""
        import iwa.web.dependencies as deps

        deps._wallet = None

        with patch.object(deps, "Wallet") as mock_wallet_cls:
            external_wallet = MagicMock(name="InjectedWallet")
            deps.set_wallet(external_wallet)

            result = deps.get_wallet()

            # Wallet() should NOT be called
            mock_wallet_cls.assert_not_called()
            assert result is external_wallet

    def test_set_wallet_overrides_existing(self):
        """set_wallet() can override a previously set wallet."""
        import iwa.web.dependencies as deps

        deps._wallet = None

        wallet1 = MagicMock(name="Wallet1")
        wallet2 = MagicMock(name="Wallet2")

        deps.set_wallet(wallet1)
        assert deps.get_wallet() is wallet1

        deps.set_wallet(wallet2)
        assert deps.get_wallet() is wallet2


class TestWalletProxy:
    """Tests for _WalletProxy backwards compatibility."""

    def setup_method(self):
        """Reset the global wallet state before each test."""
        import iwa.web.dependencies as deps

        deps._wallet = None

    def test_wallet_proxy_forwards_attribute_access(self):
        """wallet.attribute forwards to get_wallet().attribute."""
        import iwa.web.dependencies as deps

        deps._wallet = None

        mock_wallet = MagicMock()
        mock_wallet.balance_service = MagicMock(name="BalanceService")
        deps.set_wallet(mock_wallet)

        # Access through the proxy
        result = deps.wallet.balance_service

        assert result is mock_wallet.balance_service

    def test_wallet_proxy_forwards_method_calls(self):
        """wallet.method() forwards to get_wallet().method()."""
        import iwa.web.dependencies as deps

        deps._wallet = None

        mock_wallet = MagicMock()
        mock_wallet.get_accounts_balances.return_value = ({"0x1": {}}, {"0x1": {}})
        deps.set_wallet(mock_wallet)

        # Call method through proxy
        result = deps.wallet.get_accounts_balances("gnosis", ["native"])

        mock_wallet.get_accounts_balances.assert_called_once_with("gnosis", ["native"])
        assert result == ({"0x1": {}}, {"0x1": {}})

    def test_wallet_proxy_triggers_lazy_init(self):
        """Accessing wallet.attr when no wallet set triggers lazy init."""
        import iwa.web.dependencies as deps

        deps._wallet = None

        with patch.object(deps, "Wallet") as mock_wallet_cls:
            mock_instance = MagicMock()
            mock_instance.key_storage = MagicMock(name="KeyStorage")
            mock_wallet_cls.return_value = mock_instance

            # Access through proxy should trigger lazy init
            result = deps.wallet.key_storage

            mock_wallet_cls.assert_called_once()
            assert result is mock_instance.key_storage


class TestIntegrationWithRouters:
    """Integration tests for wallet injection with routers."""

    def setup_method(self):
        """Reset the global wallet state before each test."""
        import iwa.web.dependencies as deps

        deps._wallet = None

    def test_injected_wallet_used_by_routers(self):
        """Routers using 'wallet' get the injected instance."""
        import iwa.web.dependencies as deps

        # Inject a mock wallet BEFORE routers access it
        mock_wallet = MagicMock()
        mock_wallet.key_storage = MagicMock()
        mock_wallet.key_storage.accounts = {}
        deps.set_wallet(mock_wallet)

        # Simulate what a router does
        from iwa.web.dependencies import wallet

        # Access through the module-level wallet (proxy)
        accounts = wallet.key_storage.accounts

        assert accounts == {}
        # Verify it's using our injected wallet
        assert deps.get_wallet() is mock_wallet


class TestServerAsync:
    """Tests for run_server_async function."""

    def test_run_server_async_source_has_localhost_default(self):
        """run_server_async defaults to localhost for security (source check)."""
        import pathlib

        # Read the source file directly to verify default
        server_path = pathlib.Path(__file__).parent.parent / "iwa" / "web" / "server.py"
        source = server_path.read_text()

        # Verify the function signature has localhost default
        assert 'async def run_server_async(host: str = "127.0.0.1"' in source

    def test_run_server_source_has_async_function(self):
        """run_server_async function exists in server.py source."""
        import pathlib

        server_path = pathlib.Path(__file__).parent.parent / "iwa" / "web" / "server.py"
        source = server_path.read_text()

        # Verify the async function exists
        assert "async def run_server_async" in source
        assert "uvicorn.Config" in source
        assert "uvicorn.Server" in source
        assert "await server.serve()" in source
