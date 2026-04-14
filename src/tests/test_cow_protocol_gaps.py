"""Tests for CoW Protocol gaps: swap order creation/signing/submission, quotes."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from iwa.plugins.gnosis.cow.types import OrderType
from iwa.plugins.gnosis.cow_utils import CowApiUnavailableError

# ---- CowSwap.swap() tests ----


class TestCowSwapSwap:
    @pytest.mark.asyncio
    @patch("iwa.plugins.gnosis.cow.swap.get_cowpy_module")
    async def test_swap_sell_order_no_wait(self, mock_get_module):
        """SELL order placed without wait returns order info immediately."""
        # Mock all cowpy dependencies
        mock_chain_cls = MagicMock()
        mock_chain_cls.__iter__ = lambda self: iter([MagicMock(value=(MagicMock(),))])

        mock_supported_chain_id = MagicMock()
        mock_order_book_api = MagicMock()
        mock_config_factory = MagicMock()

        def get_module(name):
            mapping = {
                "SupportedChainId": mock_supported_chain_id,
                "OrderBookApi": mock_order_book_api,
                "OrderBookAPIConfigFactory": mock_config_factory,
                "Chain": mock_chain_cls,
                "swap_tokens": AsyncMock(return_value=MagicMock(
                    uid=MagicMock(root="order-uid-123"),
                    url="https://explorer.cow.fi/orders/order-uid-123",
                )),
            }
            return mapping.get(name, MagicMock())

        mock_get_module.side_effect = get_module

        from iwa.plugins.gnosis.cow.swap import CowSwap

        chain = MagicMock()
        chain.chain_id = 100
        chain.name = "gnosis"
        chain.get_token_address.return_value = "0xTokenAddr"

        # Patch the get_chain to avoid real chain lookup
        with patch.object(CowSwap, "get_chain", return_value=MagicMock()):
            cow = CowSwap(private_key_or_signer=MagicMock(), chain=chain)
            result = await cow.swap(
                amount_wei=10**18,
                sell_token_name="olas",
                buy_token_name="wxdai",
                order_type=OrderType.SELL,
                wait_for_execution=False,
            )

        assert result is not None
        assert result["status"] == "open"
        assert result["uid"] == "order-uid-123"

    @pytest.mark.asyncio
    @patch("iwa.plugins.gnosis.cow.swap.get_cowpy_module")
    async def test_swap_returns_none_on_exception(self, mock_get_module):
        """swap() returns None when cowpy raises an exception."""
        mock_chain_cls = MagicMock()
        mock_chain_cls.__iter__ = lambda self: iter([MagicMock(value=(MagicMock(),))])

        def get_module(name):
            mapping = {
                "SupportedChainId": MagicMock(),
                "OrderBookApi": MagicMock(),
                "OrderBookAPIConfigFactory": MagicMock(),
                "Chain": mock_chain_cls,
                "swap_tokens": AsyncMock(side_effect=Exception("API error")),
            }
            return mapping.get(name, MagicMock())

        mock_get_module.side_effect = get_module

        from iwa.plugins.gnosis.cow.swap import CowSwap

        chain = MagicMock()
        chain.chain_id = 100
        chain.name = "gnosis"
        chain.get_token_address.return_value = "0xTokenAddr"

        with patch.object(CowSwap, "get_chain", return_value=MagicMock()):
            cow = CowSwap(private_key_or_signer=MagicMock(), chain=chain)
            result = await cow.swap(
                amount_wei=10**18,
                sell_token_name="olas",
                buy_token_name="wxdai",
            )

        assert result is None


# ---- CowSwap.check_cowswap_order() tests ----


class TestCheckCowswapOrder:
    @pytest.mark.asyncio
    @patch("iwa.plugins.gnosis.cow.swap._get_session")
    async def test_fulfilled_order_returns_data(self, mock_get_session):
        """Fulfilled order returns order data."""
        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "status": "fulfilled",
            "executedSellAmount": "1000000",
            "executedBuyAmount": "2000000",
            "validTo": 0,
        }

        # Make run_in_executor return our mock response
        mock_get_session.return_value = mock_session

        from iwa.plugins.gnosis.cow.swap import CowSwap

        order = MagicMock()
        order.uid.root = "uid123"
        order.url = "https://api.cow.fi/orders/uid123"

        with patch("asyncio.get_event_loop") as mock_loop:
            mock_loop.return_value.run_in_executor = AsyncMock(return_value=mock_response)
            result = await CowSwap.check_cowswap_order(order)

        assert result is not None
        assert result["status"] == "fulfilled"

    @pytest.mark.asyncio
    @patch("iwa.plugins.gnosis.cow.swap._get_session")
    async def test_cancelled_order_returns_none(self, mock_get_session):
        """Cancelled order returns None."""
        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "status": "cancelled",
            "executedSellAmount": "0",
            "executedBuyAmount": "0",
            "validTo": 0,
        }

        mock_get_session.return_value = mock_session

        from iwa.plugins.gnosis.cow.swap import CowSwap

        order = MagicMock()
        order.uid.root = "uid123"
        order.url = "https://api.cow.fi/orders/uid123"

        with patch("asyncio.get_event_loop") as mock_loop:
            mock_loop.return_value.run_in_executor = AsyncMock(return_value=mock_response)
            result = await CowSwap.check_cowswap_order(order)

        assert result is None


# ---- Quote tests ----


class TestCowQuotes:
    @pytest.mark.asyncio
    async def test_get_max_sell_amount_wei(self):
        """get_max_sell_amount_wei returns amount with slippage."""
        mock_quote = MagicMock()
        mock_quote.quote.sellAmount.root = "1000000"

        mock_get_order_quote = AsyncMock(return_value=mock_quote)

        with patch("iwa.plugins.gnosis.cow.quotes.get_cowpy_module") as mock_get_module:
            mock_get_module.side_effect = lambda name: {
                "DEFAULT_APP_DATA_HASH": "0xhash",
                "get_order_quote": mock_get_order_quote,
                "OrderQuoteRequest": MagicMock(),
                "OrderQuoteSide3": MagicMock(),
                "OrderQuoteSideKindBuy": MagicMock(),
                "TokenAmount": MagicMock(),
                "SupportedChainId": MagicMock(),
                "OrderBookApi": MagicMock(),
                "OrderBookAPIConfigFactory": MagicMock(),
            }.get(name, MagicMock())

            # Reset module globals
            import iwa.plugins.gnosis.cow.quotes as quotes_mod
            quotes_mod.get_order_quote = None
            quotes_mod.OrderQuoteRequest = None
            quotes_mod.OrderQuoteSide3 = None
            quotes_mod.OrderQuoteSideKindBuy = None
            quotes_mod.TokenAmount = None
            quotes_mod.SupportedChainId = None
            quotes_mod.OrderBookApi = None
            quotes_mod.OrderBookAPIConfigFactory = None

            result = await quotes_mod.get_max_sell_amount_wei(
                amount_wei=500000,
                sell_token="0xSellToken",
                buy_token="0xBuyToken",
                chain_id_val=100,
                account_address="0xAccount",
                slippage_tolerance=0.015,
            )

        # 1000000 + 1.5% = 1015000
        assert result == 1015000

    @pytest.mark.asyncio
    async def test_get_max_buy_amount_wei(self):
        """get_max_buy_amount_wei returns amount with slippage reduction."""
        mock_quote = MagicMock()
        mock_quote.quote.buyAmount.root = "2000000"

        mock_get_order_quote = AsyncMock(return_value=mock_quote)

        with patch("iwa.plugins.gnosis.cow.quotes.get_cowpy_module") as mock_get_module:
            mock_get_module.side_effect = lambda name: {
                "DEFAULT_APP_DATA_HASH": "0xhash",
                "get_order_quote": mock_get_order_quote,
                "OrderQuoteRequest": MagicMock(),
                "OrderQuoteSide1": MagicMock(),
                "OrderQuoteSideKindSell": MagicMock(),
                "TokenAmount": MagicMock(),
                "SupportedChainId": MagicMock(),
                "OrderBookApi": MagicMock(),
                "OrderBookAPIConfigFactory": MagicMock(),
            }.get(name, MagicMock())

            import iwa.plugins.gnosis.cow.quotes as quotes_mod
            quotes_mod.get_order_quote = None
            quotes_mod.OrderQuoteRequest = None
            quotes_mod.OrderQuoteSide1 = None
            quotes_mod.OrderQuoteSideKindSell = None
            quotes_mod.TokenAmount = None
            quotes_mod.SupportedChainId = None
            quotes_mod.OrderBookApi = None
            quotes_mod.OrderBookAPIConfigFactory = None

            result = await quotes_mod.get_max_buy_amount_wei(
                sell_amount_wei=1000000,
                sell_token="0xSellToken",
                buy_token="0xBuyToken",
                chain_id_val=100,
                account_address="0xAccount",
                slippage_tolerance=0.015,
            )

        # 2000000 - 1.5% = 1970000
        assert result == 1970000


# ---- CowApiUnavailableError resilience tests ----


class TestCowApiUnavailableResilience:
    """CoW API down must never crash triton. All entry points must degrade gracefully."""

    @staticmethod
    def _make_cowswap(mock_get_module):
        """Build a CowSwap instance with fully mocked cowpy."""
        from iwa.plugins.gnosis.cow.swap import CowSwap

        chain = MagicMock()
        chain.chain_id = 100
        chain.name = "gnosis"
        chain.get_token_address.return_value = "0xTokenAddr"

        with patch.object(CowSwap, "get_chain", return_value=MagicMock()):
            return CowSwap(private_key_or_signer=MagicMock(), chain=chain)

    @pytest.mark.asyncio
    @patch("iwa.plugins.gnosis.cow.swap.get_cowpy_module")
    async def test_sell_swap_returns_none_when_cow_api_down(self, mock_get_module):
        """Regression: CowSwap.swap(SELL) must return None when CoW API is down, not crash.

        swap_tokens raises CowApiUnavailableError → caught by swap()'s except block.
        """
        mock_chain_cls = MagicMock()
        mock_chain_cls.__iter__ = lambda self: iter([MagicMock(value=(MagicMock(),))])

        def get_module(name):
            return {
                "SupportedChainId": MagicMock(),
                "OrderBookApi": MagicMock(),
                "OrderBookAPIConfigFactory": MagicMock(),
                "Chain": mock_chain_cls,
                "swap_tokens": AsyncMock(
                    side_effect=CowApiUnavailableError("api.cow.fi unreachable")
                ),
            }.get(name, MagicMock())

        mock_get_module.side_effect = get_module
        cow = self._make_cowswap(mock_get_module)

        result = await cow.swap(
            amount_wei=10**18,
            sell_token_name="olas",
            buy_token_name="wxdai",
            order_type=OrderType.SELL,
            wait_for_execution=False,
        )

        assert result is None, "swap() must return None when CoW API is down, not crash"

    @pytest.mark.asyncio
    @patch("iwa.plugins.gnosis.cow.swap.get_cowpy_module")
    async def test_buy_swap_returns_none_when_cow_api_down(self, mock_get_module):
        """BUY path: CowApiUnavailableError from swap_tokens_to_exact_tokens → swap() returns None."""
        mock_get_module.return_value = MagicMock()

        cow = self._make_cowswap(mock_get_module)

        with patch(
            "iwa.plugins.gnosis.cow.swap.CowSwap.swap_tokens_to_exact_tokens",
            new=AsyncMock(side_effect=CowApiUnavailableError("api.cow.fi unreachable")),
        ):
            result = await cow.swap(
                amount_wei=10**18,
                sell_token_name="olas",
                buy_token_name="wxdai",
                order_type=OrderType.BUY,
                wait_for_execution=False,
            )

        assert result is None, "BUY swap() must return None when CoW API is down"

    @pytest.mark.asyncio
    async def test_get_max_sell_amount_raises_cow_api_unavailable(self):
        """get_max_sell_amount_wei propagates CowApiUnavailableError when API is down.

        Callers (e.g. get_swap_execution_cost_pct in trader.py) have their own
        try/except and must handle this explicitly.
        """
        import iwa.plugins.gnosis.cow.quotes as quotes_mod

        def raise_if_app_data(name):
            if name == "DEFAULT_APP_DATA_HASH":
                raise CowApiUnavailableError("api.cow.fi down")
            return MagicMock()

        with patch("iwa.plugins.gnosis.cow.quotes.get_cowpy_module", side_effect=raise_if_app_data):
            quotes_mod.get_order_quote = None  # force re-fetch via get_cowpy_module

            with pytest.raises(CowApiUnavailableError):
                await quotes_mod.get_max_sell_amount_wei(
                    amount_wei=10**18,
                    sell_token="0xSell",
                    buy_token="0xBuy",
                    chain_id_val=100,
                    account_address="0xAccount",
                )

    @pytest.mark.asyncio
    async def test_get_max_buy_amount_raises_cow_api_unavailable(self):
        """get_max_buy_amount_wei propagates CowApiUnavailableError when API is down."""
        import iwa.plugins.gnosis.cow.quotes as quotes_mod

        def raise_if_app_data(name):
            if name == "DEFAULT_APP_DATA_HASH":
                raise CowApiUnavailableError("api.cow.fi down")
            return MagicMock()

        with patch("iwa.plugins.gnosis.cow.quotes.get_cowpy_module", side_effect=raise_if_app_data):
            quotes_mod.get_order_quote = None  # force re-fetch via get_cowpy_module

            with pytest.raises(CowApiUnavailableError):
                await quotes_mod.get_max_buy_amount_wei(
                    sell_amount_wei=10**18,
                    sell_token="0xSell",
                    buy_token="0xBuy",
                    chain_id_val=100,
                    account_address="0xAccount",
                )

    def test_server_preload_does_not_crash_when_cow_api_down(self):
        """Regression: api.cow.fi down at startup must NOT crash the web server.

        _preload_cow_modules() catches CowApiUnavailableError and logs a warning.
        This prevents the triton reboot loop caused by the CoW DNS hijacking incident.
        """
        from iwa.web import server as server_mod

        with patch.object(server_mod, "get_cowpy_module") as mock_get:
            mock_get.side_effect = CowApiUnavailableError("api.cow.fi unreachable at startup")
            # Must not raise — must only log a warning
            server_mod._preload_cow_modules()  # no exception = pass
