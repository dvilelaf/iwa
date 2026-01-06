"""Tests for CowSwap module."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from iwa.core.chain import SupportedChain
from iwa.plugins.gnosis.cow import CowSwap, OrderType


@pytest.fixture
def mock_chain():
    """Mock supported chain."""
    mock = MagicMock(spec=SupportedChain)
    mock.chain_id = 100
    mock.name = "Gnosis"
    mock.get_token_address.return_value = "0xToken"
    return mock


@pytest.fixture
def mock_cowpy_modules():
    """Mock cowpy modules."""
    with (
        patch("iwa.plugins.gnosis.cow.swap.get_cowpy_module") as mock_get_swap,
        patch("iwa.plugins.gnosis.cow.quotes.get_cowpy_module") as mock_get_quotes,
    ):
        # Create mocks for all various modules
        mocks = {
            "SupportedChainId": MagicMock(),
            "Chain": MagicMock(),
            "OrderBookApi": MagicMock(),
            "OrderBookAPIConfigFactory": MagicMock(),
            "get_order_quote": AsyncMock(),
            "OrderQuoteRequest": MagicMock(),
            "OrderQuoteSide3": MagicMock(),
            "OrderQuoteSideKindBuy": MagicMock(),
            "TokenAmount": MagicMock(),
            "OrderQuoteSide1": MagicMock(),
            "OrderQuoteSideKindSell": MagicMock(),
            "Order": MagicMock(),
            "PreSignSignature": MagicMock(),
            "SigningScheme": MagicMock(),
            "sign_order": MagicMock(),
            "post_order": AsyncMock(),
            "CompletedOrder": MagicMock(),
            "swap_tokens": AsyncMock(),
        }

        # Setup specific returns
        mocks["get_order_quote"].return_value.quote.sellAmount.root = "100"
        mocks["get_order_quote"].return_value.quote.buyAmount.root = "90"
        mocks["get_order_quote"].return_value.quote.validTo = 1234567890

        mocks["post_order"].return_value = "0xOrderUID"

        # Correctly mock Chain iteration for get_chain logic
        # chain.value[0] == supported_chain_id (which is mocked as MagicMock by default,
        # but in init it calls SupportedChainId(chain.chain_id))

        # Let's make supported_chain_id return a specific value and chain matching it
        mock_supported_id = MagicMock()
        mocks["SupportedChainId"].return_value = mock_supported_id

        mock_chain_enum_item = MagicMock()
        mock_chain_enum_item.value = [mock_supported_id]

        # Make Chain iterable
        mocks["Chain"].__iter__.return_value = [mock_chain_enum_item]

        mock_get_swap.side_effect = lambda name: mocks.get(name, MagicMock())
        mock_get_quotes.side_effect = mock_get_swap.side_effect
        yield mocks


@pytest.fixture
def cowswap(mock_chain, mock_cowpy_modules):
    """CowSwap instance fixture."""
    return CowSwap("0x0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef", mock_chain)


def test_init(cowswap, mock_chain):
    """Test initialization."""
    assert cowswap.chain == mock_chain
    assert cowswap.cow_chain is not None


@pytest.mark.asyncio
async def test_get_max_sell_amount_wei(cowswap, mock_cowpy_modules):
    """Test get_max_sell_amount_wei."""
    amount = await cowswap.get_max_sell_amount_wei(100, "0xSell", "0xBuy")
    # mocked sellAmount root is "100", slippage is 0.005 default -> 100 * 1.005 = 100
    assert amount == 100
    mock_cowpy_modules["get_order_quote"].assert_called_once()


@pytest.mark.asyncio
async def test_get_max_buy_amount_wei(cowswap, mock_cowpy_modules):
    """Test get_max_buy_amount_wei."""
    amount = await cowswap.get_max_buy_amount_wei(100, "0xSell", "0xBuy")
    # mocked buyAmount root is "90", slippage 0.005 -> 90 * 0.995 = 89.55 -> int 89
    assert amount == 89
    mock_cowpy_modules["get_order_quote"].assert_called_once()


@pytest.mark.asyncio
async def test_swap_defaults(cowswap, mock_cowpy_modules):
    """Test swap with default settings."""
    # Test SWAP with default logic (using swap_tokens from module)
    # We need to make sure global swap_tokens is None or handled.
    # In test context, we rely on _get_cowpy_module returning the mock.

    mock_cowpy_modules["swap_tokens"].return_value = MagicMock(uid=MagicMock(root="0x123"))

    # Mock verify order to return True immediately to avoid sleep
    with patch.object(CowSwap, "check_cowswap_order", return_value={"status": "fulfilled"}):
        result = await cowswap.swap(100, "OLAS", "WXDAI", order_type=OrderType.SELL)
        assert result is not None
        mock_cowpy_modules["swap_tokens"].assert_called()


@pytest.mark.asyncio
async def test_swap_buy_order_type(cowswap, mock_cowpy_modules):
    """Test swap with BUY order type."""
    # For BUY order type, it uses self.swap_tokens_to_exact_tokens
    # checking patching of global swap_tokens

    with patch("iwa.plugins.gnosis.cow.swap.swap_tokens", new=None):
        with patch.object(
            CowSwap, "swap_tokens_to_exact_tokens", new_callable=AsyncMock
        ) as mock_custom_swap:
            mock_custom_swap.return_value = MagicMock(uid=MagicMock(root="0x123"))
            with patch.object(CowSwap, "check_cowswap_order", return_value={"status": "fulfilled"}):
                result = await cowswap.swap(100, "OLAS", "WXDAI", order_type=OrderType.BUY)
                assert result is not None
                mock_custom_swap.assert_called()


@pytest.mark.asyncio
async def test_swap_tokens_to_exact_tokens(cowswap, mock_cowpy_modules):
    """Test swap_tokens_to_exact_tokens custom logic."""
    # Test the custom implementation
    # It calls get_order_quote, post_order

    mock_cowpy_modules["post_order"].return_value = "0xOrderUID"
    mock_cowpy_modules["OrderBookApi"].return_value.get_order_link.return_value = "http://link"

    # Mock CompletedOrder to return an object with attributes set from constructor
    def side_effect(uid, url):
        m = MagicMock()
        m.uid = uid
        m.url = url
        return m

    mock_cowpy_modules["CompletedOrder"].side_effect = side_effect

    result = await CowSwap.swap_tokens_to_exact_tokens(
        amount=100,
        account=MagicMock(address="0xUser"),
        chain=MagicMock(value=[100]),
        sell_token="0xSell",
        buy_token="0xBuy",
        env="prod",
    )

    assert result.uid == "0xOrderUID"
    assert result.url == "http://link"
    mock_cowpy_modules["get_order_quote"].assert_called()  # Quote needed for sell amount calc
    mock_cowpy_modules["post_order"].assert_called()


@pytest.mark.asyncio
async def test_check_cowswap_order_success(cowswap):
    """Test check_cowswap_order success path."""
    mock_order = MagicMock()
    mock_order.url = "http://api/order"

    with patch("requests.get") as mock_get:
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {
            "status": "fulfilled",
            "executedSellAmount": "100",
            "executedBuyAmount": "90",
        }

        # Need to mock loop.run_in_executor since check_cowswap_order uses it
        # Or just let it run if requests.get is mocked?
        # check_cowswap_order calls loop.run_in_executor(None, lambda: requests.get(...))
        # This will run the lambda in a thread. The mock should work.

        result = await cowswap.check_cowswap_order(mock_order)

        assert result == {
            "status": "fulfilled",
            "executedSellAmount": "100",
            "executedBuyAmount": "90",
        }


@pytest.mark.asyncio
async def test_check_cowswap_order_expired(cowswap):
    """Test check_cowswap_order expiration."""
    mock_order = MagicMock()
    mock_order.url = "http://api/order"

    with patch("requests.get") as mock_get:
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {"status": "expired"}

        result = await cowswap.check_cowswap_order(mock_order)
        assert result is None


@pytest.mark.asyncio
async def test_check_cowswap_order_timeout(cowswap):
    """Test check_cowswap_order timeout."""
    mock_order = MagicMock()
    mock_order.url = "http://api/order"

    with patch("requests.get") as mock_get:
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {"status": "open", "executedSellAmount": "0"}

        # Speed up retry sleep (asyncio.sleep)
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await cowswap.check_cowswap_order(mock_order)
            assert result is None
