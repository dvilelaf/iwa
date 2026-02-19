"""Tests to improve coverage for chain/manager, web/routers/state, and services/transfer/swap."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from iwa.core.services.transfer.swap import OrderType, SwapMixin

# Valid Ethereum addresses for testing
ADDR_AGENT = "0x78731D3Ca6b7E34aC0F824c42a7cC18A495cabaB"
ADDR_SAFE = "0x40A2aCCbd92BCA938b02010E17A5b8929b49130D"
ADDR_OWNER = "0x1111111111111111111111111111111111111111"
ADDR_TOKEN = "0x3333333333333333333333333333333333333333"
ADDR_BUY_TOKEN = "0x4444444444444444444444444444444444444444"

# ---------------------------------------------------------------------------
# Web app setup (must mock before importing app)
# ---------------------------------------------------------------------------
with (
    patch("iwa.core.wallet.Wallet"),
    patch("iwa.core.chain.ChainInterfaces"),
    patch("iwa.core.wallet.init_db"),
    patch("iwa.web.dependencies._get_webui_password", return_value=None),
):
    from iwa.web.dependencies import verify_auth
    from iwa.web.server import app


async def override_verify_auth():
    """Override auth for testing."""
    return True


app.dependency_overrides[verify_auth] = override_verify_auth

from iwa.web.routers.olas.admin import limiter as _admin_limiter
from iwa.web.routers.olas.funding import limiter as _funding_limiter

_admin_limiter.enabled = False
_funding_limiter.enabled = False


@pytest.fixture(scope="module")
def client():
    """TestClient for FastAPI app."""
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Module 1: chain/manager.py — Lines 35-38 (check_all_rpcs), 45-46 (close_all)
# ---------------------------------------------------------------------------


class TestChainManagerCheckAllRpcs:
    """Tests for ChainInterfaces.check_all_rpcs method."""

    def test_check_all_rpcs_all_healthy(self):
        """Cover check_all_rpcs when all chains are healthy (lines 35-38)."""
        from iwa.core.chain.manager import ChainInterfaces

        ci = ChainInterfaces()

        mock_gnosis = MagicMock()
        mock_gnosis.check_rpc_health.return_value = True
        mock_ethereum = MagicMock()
        mock_ethereum.check_rpc_health.return_value = True
        mock_base = MagicMock()
        mock_base.check_rpc_health.return_value = True

        orig_gnosis, orig_ethereum, orig_base = ci.gnosis, ci.ethereum, ci.base
        try:
            ci.gnosis = mock_gnosis
            ci.ethereum = mock_ethereum
            ci.base = mock_base

            results = ci.check_all_rpcs()

            assert results == {"gnosis": True, "ethereum": True, "base": True}
            mock_gnosis.check_rpc_health.assert_called_once()
            mock_ethereum.check_rpc_health.assert_called_once()
            mock_base.check_rpc_health.assert_called_once()
        finally:
            ci.gnosis, ci.ethereum, ci.base = orig_gnosis, orig_ethereum, orig_base

    def test_check_all_rpcs_some_unhealthy(self):
        """Cover check_all_rpcs when some chains are unhealthy."""
        from iwa.core.chain.manager import ChainInterfaces

        ci = ChainInterfaces()

        mock_gnosis = MagicMock()
        mock_gnosis.check_rpc_health.return_value = True
        mock_ethereum = MagicMock()
        mock_ethereum.check_rpc_health.return_value = False
        mock_base = MagicMock()
        mock_base.check_rpc_health.return_value = True

        orig_gnosis, orig_ethereum, orig_base = ci.gnosis, ci.ethereum, ci.base
        try:
            ci.gnosis = mock_gnosis
            ci.ethereum = mock_ethereum
            ci.base = mock_base

            results = ci.check_all_rpcs()

            assert results == {"gnosis": True, "ethereum": False, "base": True}
        finally:
            ci.gnosis, ci.ethereum, ci.base = orig_gnosis, orig_ethereum, orig_base


class TestChainManagerCloseAll:
    """Tests for ChainInterfaces.close_all method."""

    def test_close_all_calls_close_on_all_interfaces(self):
        """Cover close_all (lines 45-46)."""
        from iwa.core.chain.manager import ChainInterfaces

        ci = ChainInterfaces()

        mock_gnosis = MagicMock()
        mock_ethereum = MagicMock()
        mock_base = MagicMock()

        orig_gnosis, orig_ethereum, orig_base = ci.gnosis, ci.ethereum, ci.base
        try:
            ci.gnosis = mock_gnosis
            ci.ethereum = mock_ethereum
            ci.base = mock_base

            ci.close_all()

            mock_gnosis.close.assert_called_once()
            mock_ethereum.close.assert_called_once()
            mock_base.close.assert_called_once()
        finally:
            ci.gnosis, ci.ethereum, ci.base = orig_gnosis, orig_ethereum, orig_base


# ---------------------------------------------------------------------------
# Module 2: web/routers/state.py — Lines 24-27, 33, 68-69
# ---------------------------------------------------------------------------


class TestStateGetState:
    """Tests for get_state endpoint covering lines 24-27 and 33."""

    def test_get_state_with_tokens_and_whitelist(self, client):
        """Cover get_state: chain iteration with tokens (24-27), whitelist (33)."""
        mock_gnosis_interface = MagicMock()
        mock_gnosis_interface.chain.native_currency = "xDAI"
        mock_gnosis_interface.tokens = {"OLAS": ADDR_TOKEN, "WETH": ADDR_BUY_TOKEN}
        mock_gnosis_interface.is_tenderly = False

        mock_ethereum_interface = MagicMock()
        mock_ethereum_interface.chain.native_currency = "ETH"
        mock_ethereum_interface.tokens = {"USDC": ADDR_TOKEN}

        mock_base_interface = MagicMock()
        mock_base_interface.chain.native_currency = "ETH"
        mock_base_interface.tokens = {}

        def mock_items():
            yield "gnosis", mock_gnosis_interface
            yield "ethereum", mock_ethereum_interface
            yield "base", mock_base_interface

        mock_ci_instance = MagicMock()
        mock_ci_instance.items = mock_items
        mock_ci_instance.gnosis = mock_gnosis_interface

        mock_config_instance = MagicMock()
        mock_config_instance.core.whitelist = {
            "treasury": ADDR_OWNER,
            "operator": ADDR_AGENT,
        }

        with (
            patch("iwa.web.routers.state.ChainInterfaces", return_value=mock_ci_instance),
            patch("iwa.web.routers.state.Config", return_value=mock_config_instance),
        ):
            response = client.get("/api/state")
            assert response.status_code == 200
            data = response.json()

            # Verify chains
            assert data["chains"] == ["gnosis", "ethereum", "base"]

            # Verify tokens (lines 24-27)
            assert "OLAS" in data["tokens"]["gnosis"]
            assert "WETH" in data["tokens"]["gnosis"]
            assert "USDC" in data["tokens"]["ethereum"]
            assert data["tokens"]["base"] == []

            # Verify native currencies
            assert data["native_currencies"]["gnosis"] == "xDAI"
            assert data["native_currencies"]["ethereum"] == "ETH"

            # Verify whitelist (line 33)
            assert data["whitelist"]["treasury"] == ADDR_OWNER
            assert data["whitelist"]["operator"] == ADDR_AGENT

            # Verify other fields
            assert data["default_chain"] == "gnosis"
            assert data["testing"] is False

    def test_get_state_no_whitelist(self, client):
        """Cover get_state when config.core is None (no whitelist, line 32 false branch)."""
        mock_gnosis_interface = MagicMock()
        mock_gnosis_interface.chain.native_currency = "xDAI"
        mock_gnosis_interface.tokens = {}
        mock_gnosis_interface.is_tenderly = False

        def mock_items():
            yield "gnosis", mock_gnosis_interface

        mock_ci_instance = MagicMock()
        mock_ci_instance.items = mock_items
        mock_ci_instance.gnosis = mock_gnosis_interface

        mock_config_instance = MagicMock()
        mock_config_instance.core = None

        with (
            patch("iwa.web.routers.state.ChainInterfaces", return_value=mock_ci_instance),
            patch("iwa.web.routers.state.Config", return_value=mock_config_instance),
        ):
            response = client.get("/api/state")
            assert response.status_code == 200
            data = response.json()
            assert data["whitelist"] == {}


class TestStateRpcStatus:
    """Tests for get_rpc_status endpoint covering lines 68-69."""

    def test_rpc_status_exception_path(self, client):
        """Cover get_rpc_status exception path (lines 68-69)."""
        mock_gnosis_interface = MagicMock()
        mock_gnosis_interface.web3.eth.block_number = 12345
        mock_gnosis_interface.chain.rpcs = ["https://rpc.gnosis.io"]

        mock_ethereum_interface = MagicMock()
        # Make block_number raise an exception via property
        eth_mock = MagicMock()
        type(eth_mock).block_number = property(
            lambda self: (_ for _ in ()).throw(ConnectionError("RPC unreachable"))
        )
        mock_ethereum_interface.web3.eth = eth_mock
        mock_ethereum_interface.chain.rpcs = ["https://rpc.ethereum.io?api_key=secret"]

        mock_base_interface = MagicMock()
        mock_base_interface.web3.eth.block_number = 99999
        mock_base_interface.chain.rpcs = ["https://rpc.base.org"]

        def mock_items():
            yield "gnosis", mock_gnosis_interface
            yield "ethereum", mock_ethereum_interface
            yield "base", mock_base_interface

        mock_ci_instance = MagicMock()
        mock_ci_instance.items = mock_items

        # The endpoint re-imports ChainInterfaces from iwa.core.chain, so patch there
        with patch("iwa.core.chain.ChainInterfaces", return_value=mock_ci_instance):
            response = client.get("/api/rpc-status")
            assert response.status_code == 200
            data = response.json()

            # Gnosis online
            assert data["gnosis"]["status"] == "online"
            assert data["gnosis"]["block"] == 12345

            # Ethereum offline (lines 68-69 covered)
            assert data["ethereum"]["status"] == "offline"
            assert "RPC unreachable" in data["ethereum"]["error"]
            # API key should be obscured
            assert "?***" in data["ethereum"]["rpcs"][0]

            # Base online
            assert data["base"]["status"] == "online"


class TestObscureUrl:
    """Tests for _obscure_url helper."""

    def test_obscure_url_with_api_key(self):
        """Cover _obscure_url with api_key param."""
        from iwa.web.routers.state import _obscure_url

        result = _obscure_url("https://rpc.example.com?api_key=secret123")
        assert result == "https://rpc.example.com?***"

    def test_obscure_url_without_key(self):
        """Cover _obscure_url without any key params."""
        from iwa.web.routers.state import _obscure_url

        result = _obscure_url("https://rpc.example.com")
        assert result == "https://rpc.example.com"

    def test_obscure_url_with_project_id(self):
        """Cover _obscure_url with project_id param."""
        from iwa.web.routers.state import _obscure_url

        result = _obscure_url("https://rpc.example.com?project_id=abc123")
        assert result == "https://rpc.example.com?***"


# ---------------------------------------------------------------------------
# Module 3: services/transfer/swap.py — Lines 43, 57-69, 73, 78-79, 205-208, 261-262
# ---------------------------------------------------------------------------


class MockTransferService(SwapMixin):
    """Dummy class to test the SwapMixin."""

    def __init__(self):
        self.balance_service = MagicMock()
        self.account_service = MagicMock()
        self.key_storage = MagicMock()
        self.wallet = MagicMock()
        self.get_erc20_allowance = MagicMock()
        self.approve_erc20 = MagicMock()
        self._get_token_price_info = MagicMock(return_value=(1.0, 1.0))


@pytest.fixture
def transfer_service():
    return MockTransferService()


@pytest.fixture
def mock_chain_interfaces():
    with patch("iwa.core.services.transfer.swap.ChainInterfaces") as mock:
        yield mock


@pytest.fixture
def mock_cow_swap():
    with patch("iwa.core.services.transfer.swap.CowSwap") as mock:
        yield mock


@pytest.fixture
def mock_erc20_contract():
    with patch("iwa.core.services.transfer.swap.ERC20Contract") as mock:
        yield mock


@pytest.fixture
def mock_log_transaction():
    with patch("iwa.core.services.transfer.swap.log_transaction") as mock:
        yield mock


class TestSwapReturnNone:
    """Tests covering swap returning None when _prepare_swap_amount returns None (line 43)."""

    @pytest.mark.asyncio
    async def test_swap_returns_none_when_prepare_returns_none(
        self, transfer_service, mock_chain_interfaces
    ):
        """Cover line 43: if amount_wei is None, return None."""
        # Make _prepare_swap_amount return None
        transfer_service._prepare_swap_amount = MagicMock(return_value=None)

        result = await transfer_service.swap(
            account_address_or_tag="user",
            amount_eth=1.0,
            sell_token_name="WETH",
            buy_token_name="USDC",
            chain_name="gnosis",
        )

        assert result is None


class TestSwapBalanceChecks:
    """Tests for swap balance validation (lines 57-69, 73)."""

    @pytest.mark.asyncio
    async def test_swap_adjusts_amount_for_precision_discrepancy(
        self, transfer_service, mock_chain_interfaces, mock_cow_swap, mock_log_transaction
    ):
        """Cover lines 57-65: precision tolerance adjustment when diff <= tolerance."""
        account_mock = MagicMock()
        account_mock.address = "0xUser"
        transfer_service.account_service.resolve_account.return_value = account_mock
        transfer_service.key_storage.get_signer.return_value = "signer"
        transfer_service.get_erc20_allowance.return_value = 10**18 + 100

        # Set balance just slightly below the requested amount (within tolerance)
        requested_amount_wei = 10**18  # 1.0 token
        actual_balance = requested_amount_wei - 10**13  # diff of 10**13, within 10**14 tolerance
        transfer_service.balance_service.get_erc20_balance_wei.return_value = actual_balance

        cow_instance = AsyncMock()
        mock_cow_swap.return_value = cow_instance
        cow_instance.swap.return_value = {
            "executedSellAmount": str(actual_balance),
            "executedBuyAmount": "2000000",
            "quote": {"sellTokenPrice": 1.0, "buyTokenPrice": 500.0},
            "txHash": "0xHash",
        }

        result = await transfer_service.swap(
            account_address_or_tag="user",
            amount_eth=1.0,
            sell_token_name="WETH",
            buy_token_name="USDC",
            chain_name="gnosis",
            order_type=OrderType.SELL,
        )

        assert result is not None
        # Verify the amount was adjusted to actual_balance
        cow_instance.swap.assert_called_once()
        call_kwargs = cow_instance.swap.call_args[1]
        assert call_kwargs["amount_wei"] == actual_balance

    @pytest.mark.asyncio
    async def test_swap_raises_insufficient_balance(
        self, transfer_service, mock_chain_interfaces
    ):
        """Cover lines 66-71: raises ValueError when balance is too low (beyond tolerance)."""
        account_mock = MagicMock()
        account_mock.address = "0xUser"
        transfer_service.account_service.resolve_account.return_value = account_mock

        # Balance much lower than requested (well beyond tolerance)
        transfer_service.balance_service.get_erc20_balance_wei.return_value = 5 * 10**17  # 0.5 token

        with pytest.raises(ValueError, match="Insufficient.*balance"):
            await transfer_service.swap(
                account_address_or_tag="user",
                amount_eth=1.0,
                sell_token_name="WETH",
                buy_token_name="USDC",
                chain_name="gnosis",
                order_type=OrderType.SELL,
            )

    @pytest.mark.asyncio
    async def test_swap_raises_when_balance_is_none(
        self, transfer_service, mock_chain_interfaces
    ):
        """Cover line 73: raises ValueError when balance cannot be retrieved."""
        account_mock = MagicMock()
        account_mock.address = "0xUser"
        transfer_service.account_service.resolve_account.return_value = account_mock

        transfer_service.balance_service.get_erc20_balance_wei.return_value = None

        with pytest.raises(ValueError, match="Could not retrieve balance"):
            await transfer_service.swap(
                account_address_or_tag="user",
                amount_eth=1.0,
                sell_token_name="WETH",
                buy_token_name="USDC",
                chain_name="gnosis",
                order_type=OrderType.SELL,
            )


class TestSwapNoSigner:
    """Tests for swap when signer is not available (lines 78-79)."""

    @pytest.mark.asyncio
    async def test_swap_returns_none_when_no_signer(
        self, transfer_service, mock_chain_interfaces
    ):
        """Cover lines 78-79: returns None when signer cannot be retrieved."""
        account_mock = MagicMock()
        account_mock.address = "0xUser"
        transfer_service.account_service.resolve_account.return_value = account_mock
        transfer_service.key_storage.get_signer.return_value = None

        # Sufficient balance to pass validation
        transfer_service.balance_service.get_erc20_balance_wei.return_value = 2 * 10**18

        result = await transfer_service.swap(
            account_address_or_tag="user",
            amount_eth=1.0,
            sell_token_name="WETH",
            buy_token_name="USDC",
            chain_name="gnosis",
            order_type=OrderType.SELL,
        )

        assert result is None


class TestEnsureAllowanceBuyOrder:
    """Tests for _ensure_allowance_for_swap with BUY order type (lines 205-208)."""

    @pytest.mark.asyncio
    async def test_ensure_allowance_buy_order_insufficient(
        self, transfer_service, mock_chain_interfaces, mock_cow_swap
    ):
        """Cover lines 205-208: BUY order calculates required_amount via get_max_sell_amount_wei."""
        transfer_service.get_erc20_allowance.return_value = 0  # insufficient

        mock_chain_interface = MagicMock()
        mock_chain_interface.chain.get_token_address.side_effect = lambda name: {
            "USDC": ADDR_TOKEN,
            "WETH": ADDR_BUY_TOKEN,
        }.get(name)
        mock_chain_interfaces.return_value.get.return_value = mock_chain_interface

        cow_instance = AsyncMock()
        cow_instance.get_max_sell_amount_wei = AsyncMock(return_value=2 * 10**18)

        required = await transfer_service._ensure_allowance_for_swap(
            account_address_or_tag="user",
            sell_token_name="USDC",
            buy_token_name="WETH",
            chain_name="gnosis",
            amount_wei=10**18,
            order_type=OrderType.BUY,
            cow=cow_instance,
        )

        # Verify get_max_sell_amount_wei was called with correct token addresses
        cow_instance.get_max_sell_amount_wei.assert_called_once_with(
            10**18, ADDR_TOKEN, ADDR_BUY_TOKEN
        )
        assert required == 2 * 10**18
        # Verify approval was called since allowance is insufficient
        transfer_service.approve_erc20.assert_called_once()

    @pytest.mark.asyncio
    async def test_ensure_allowance_buy_order_sufficient(
        self, transfer_service, mock_chain_interfaces, mock_cow_swap
    ):
        """Cover BUY order with sufficient allowance (skips approval)."""
        transfer_service.get_erc20_allowance.return_value = 5 * 10**18  # sufficient

        mock_chain_interface = MagicMock()
        mock_chain_interface.chain.get_token_address.side_effect = lambda name: {
            "USDC": ADDR_TOKEN,
            "WETH": ADDR_BUY_TOKEN,
        }.get(name)
        mock_chain_interfaces.return_value.get.return_value = mock_chain_interface

        cow_instance = AsyncMock()
        cow_instance.get_max_sell_amount_wei = AsyncMock(return_value=2 * 10**18)

        required = await transfer_service._ensure_allowance_for_swap(
            account_address_or_tag="user",
            sell_token_name="USDC",
            buy_token_name="WETH",
            chain_name="gnosis",
            amount_wei=10**18,
            order_type=OrderType.BUY,
            cow=cow_instance,
        )

        assert required == 2 * 10**18
        # Approval should NOT be called since allowance is sufficient
        transfer_service.approve_erc20.assert_not_called()


class TestSwapAnalyticsBuyDecimals:
    """Tests for _calculate_swap_analytics with buy token decimals (lines 261-262)."""

    def test_calculate_swap_analytics_with_buy_token_decimals(
        self, transfer_service, mock_chain_interfaces, mock_erc20_contract
    ):
        """Cover lines 261-262: get buy token decimals via ERC20Contract."""
        mock_chain_interface = MagicMock()
        mock_chain_interface.chain.get_token_address.side_effect = lambda name: {
            "WETH": ADDR_TOKEN,
            "USDC": ADDR_BUY_TOKEN,
        }.get(name)
        mock_chain_interfaces.return_value.get.return_value = mock_chain_interface

        # Mock ERC20Contract to return different decimals for sell vs buy
        def make_erc20(addr, chain):
            m = MagicMock()
            if addr == ADDR_TOKEN:
                m.decimals = 18  # WETH
            elif addr == ADDR_BUY_TOKEN:
                m.decimals = 6  # USDC
            return m

        mock_erc20_contract.side_effect = make_erc20

        result_data = {
            "executedSellAmount": 10**18,  # 1 WETH
            "executedBuyAmount": 2000 * 10**6,  # 2000 USDC
            "quote": {"sellTokenPrice": 2000.0, "buyTokenPrice": 1.0},
        }

        analytics = transfer_service._calculate_swap_analytics(
            result=result_data,
            sell_token_name="WETH",
            buy_token_name="USDC",
            chain_name="gnosis",
        )

        assert analytics["type"] == "swap"
        assert analytics["platform"] == "cowswap"
        assert analytics["sell_token"] == "WETH"
        assert analytics["buy_token"] == "USDC"
        # Verify decimals were properly applied
        # value_sold = (10**18 / 10**18) * 2000.0 = 2000.0
        assert analytics["_value_sold"] == pytest.approx(2000.0)
        # value_bought = (2000 * 10**6 / 10**6) * 1.0 = 2000.0
        assert analytics["value_change_pct"] is not None
        assert analytics["value_change_pct"] != "N/A"

    def test_calculate_swap_analytics_no_token_addresses(
        self, transfer_service, mock_chain_interfaces, mock_erc20_contract
    ):
        """Cover analytics when get_token_address returns None (default 18 decimals)."""
        mock_chain_interface = MagicMock()
        mock_chain_interface.chain.get_token_address.return_value = None
        mock_chain_interfaces.return_value.get.return_value = mock_chain_interface

        result_data = {
            "executedSellAmount": 10**18,
            "executedBuyAmount": 10**18,
            "quote": {"sellTokenPrice": 1.0, "buyTokenPrice": 1.0},
        }

        analytics = transfer_service._calculate_swap_analytics(
            result=result_data,
            sell_token_name="TOKEN_A",
            buy_token_name="TOKEN_B",
            chain_name="gnosis",
        )

        # Should work with default 18 decimals
        assert analytics["execution_price"] == pytest.approx(1.0)
        # ERC20Contract should NOT have been called since addresses are None
        mock_erc20_contract.assert_not_called()

    def test_calculate_swap_analytics_exception_uses_defaults(
        self, transfer_service, mock_chain_interfaces
    ):
        """Cover analytics exception path (line 263-264): falls back to 18 decimals."""
        mock_chain_interfaces.return_value.get.side_effect = Exception("Chain not found")

        result_data = {
            "executedSellAmount": 10**18,
            "executedBuyAmount": 10**18,
            "quote": {"sellTokenPrice": 0, "buyTokenPrice": 0},
        }

        analytics = transfer_service._calculate_swap_analytics(
            result=result_data,
            sell_token_name="WETH",
            buy_token_name="USDC",
            chain_name="gnosis",
        )

        # Should complete without raising, using default 18 decimals
        assert analytics["type"] == "swap"
        assert analytics["value_change_pct"] == "N/A"  # No sell price
