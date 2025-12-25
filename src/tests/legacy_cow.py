from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# We need to mock cowdao_cowpy before importing CowSwap to avoid import errors
# if the library is not installed.
@pytest.fixture(autouse=True)
def mock_cowpy_modules():
    """Mock cowdao_cowpy modules and submodules globally for these tests."""
    mock_cow = MagicMock()
    mock_common = MagicMock()
    mock_chains = MagicMock()

    # Configure Chain enum mock
    mock_chain_enum = MagicMock()
    mock_chain_enum.value = [100]  # Gnosis
    mock_chains.Chain = [mock_chain_enum]
    mock_chains.SupportedChainId = lambda x: x

    modules = {
        "cowdao_cowpy": MagicMock(),
        "cowdao_cowpy.cow": mock_cow,
        "cowdao_cowpy.cow.swap": MagicMock(),
        "cowdao_cowpy.common": mock_common,
        "cowdao_cowpy.common.chains": mock_chains,
        "cowdao_cowpy.app_data": MagicMock(),
        "cowdao_cowpy.app_data.utils": MagicMock(),
        "cowdao_cowpy.contracts": MagicMock(),
        "cowdao_cowpy.contracts.order": MagicMock(),
        "cowdao_cowpy.contracts.sign": MagicMock(),
        "cowdao_cowpy.order_book": MagicMock(),
        "cowdao_cowpy.order_book.api": MagicMock(),
        "cowdao_cowpy.order_book.config": MagicMock(),
        "cowdao_cowpy.order_book.generated": MagicMock(),
        "cowdao_cowpy.order_book.generated.model": MagicMock(),
    }

    with patch.dict("sys.modules", modules):
        yield modules


@pytest.fixture(autouse=True)
def clear_cowswap_cache():
    """Clear the lazy loading cache in CowSwap module."""
    from iwa.plugins.gnosis.cow import _cowpy_cache

    _cowpy_cache.clear()
    yield
    _cowpy_cache.clear()


from iwa.core.chain import Gnosis
from iwa.plugins.gnosis.cow import CowSwap, OrderType


@pytest.fixture
def mock_account():
    with patch("iwa.plugins.gnosis.cow.Account") as mock:
        mock.from_key.return_value = MagicMock(address="0xAccount", _address="0xAccount")
        yield mock


@pytest.fixture
def cow_swap(mock_account):
    return CowSwap("private_key", Gnosis())


@pytest.mark.asyncio
async def test_swap_sell(cow_swap):
    with patch("iwa.plugins.gnosis.cow.swap_tokens", new_callable=AsyncMock) as mock_swap_tokens:
        mock_swap_tokens.return_value = MagicMock(uid=MagicMock(root="order_uid"))

        with patch.object(CowSwap, "check_cowswap_order", return_value=True):
            success = await cow_swap.swap(1000, "OLAS", "WXDAI", order_type=OrderType.SELL)
            assert success is True
            mock_swap_tokens.assert_called_once()


@pytest.mark.asyncio
async def test_swap_buy(cow_swap):
    with patch(
        "iwa.plugins.gnosis.cow.CowSwap.swap_tokens_to_exact_tokens", new_callable=AsyncMock
    ) as mock_swap_tokens:
        mock_swap_tokens.return_value = MagicMock(uid=MagicMock(root="order_uid"))

        with patch.object(CowSwap, "check_cowswap_order", return_value=True):
            success = await cow_swap.swap(1000, "OLAS", "WXDAI", order_type=OrderType.BUY)
            assert success is True
            mock_swap_tokens.assert_called_once()


def test_check_cowswap_order_executed(cow_swap):
    order = MagicMock()
    order.url = "http://order.url"

    with patch("iwa.plugins.gnosis.cow.requests.get") as mock_get:
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {
            "status": "fulfilled",
            "executedSellAmount": "100",
            "executedBuyAmount": "100",
            "quote": {"sellTokenPrice": 1.0, "buyTokenPrice": 1.0},
        }

        success = cow_swap.check_cowswap_order(order)
        assert success is True


def test_check_cowswap_order_expired(cow_swap):
    order = MagicMock()
    order.url = "http://order.url"

    with patch("iwa.plugins.gnosis.cow.requests.get") as mock_get:
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {"status": "expired"}

        success = cow_swap.check_cowswap_order(order)
        assert success is False


def test_get_chain_unsupported(cow_swap):
    # Set to an ID that won't be found in our mock Chain list
    cow_swap.supported_chain_id = 999
    with pytest.raises(ValueError, match="Unsupported SupportedChainId"):
        cow_swap.get_chain()


def test_check_cowswap_order_retries(cow_swap):
    order = MagicMock()
    order.url = "http://order.url"

    with (
        patch("iwa.plugins.gnosis.cow.requests.get") as mock_get,
        patch("iwa.plugins.gnosis.cow.time.sleep") as mock_sleep,
    ):
        mock_get.side_effect = [
            MagicMock(status_code=404),
            MagicMock(
                status_code=200, json=lambda: {"status": "fulfilled", "executedSellAmount": "100"}
            ),
        ]

        success = cow_swap.check_cowswap_order(order)
        assert success is True
        assert mock_get.call_count == 2
        mock_sleep.assert_called_once()


def test_check_cowswap_order_max_retries(cow_swap):
    order = MagicMock()
    order.url = "http://order.url"

    with (
        patch("iwa.plugins.gnosis.cow.requests.get") as mock_get,
        patch("iwa.plugins.gnosis.cow.time.sleep"),
    ):
        mock_get.return_value.status_code = 404

        success = cow_swap.check_cowswap_order(order)
        assert success is False
        assert mock_get.call_count == 8


@pytest.mark.asyncio
async def test_swap_exception(cow_swap):
    with patch("iwa.plugins.gnosis.cow.swap_tokens", side_effect=Exception("Swap failed")):
        success = await cow_swap.swap(1000, "OLAS", "WXDAI")
        assert success is False


@pytest.mark.asyncio
async def test_get_max_sell_amount_wei(cow_swap):
    with patch("iwa.plugins.gnosis.cow.get_order_quote", new_callable=AsyncMock) as mock_get_quote:
        mock_quote = MagicMock()
        mock_quote.quote.sellAmount.root = "1000"
        mock_get_quote.return_value = mock_quote

        amount = await cow_swap.get_max_sell_amount_wei(1000, "0xSell", "0xBuy")
        assert amount == int(1000 * 1.005)


@pytest.mark.asyncio
async def test_swap_tokens_to_exact_tokens(cow_swap):
    with (
        patch("iwa.plugins.gnosis.cow.get_order_quote", new_callable=AsyncMock) as mock_get_quote,
        patch("iwa.plugins.gnosis.cow.post_order", new_callable=AsyncMock) as mock_post_order,
        patch("iwa.plugins.gnosis.cow.sign_order"),
        patch("iwa.plugins.gnosis.cow.CompletedOrder") as mock_completed_order,
    ):
        mock_quote = MagicMock()
        mock_quote.quote.sellAmount.root = "1000"
        mock_quote.quote.validTo = 1234567890
        mock_get_quote.return_value = mock_quote

        mock_post_order.return_value = MagicMock(root="order_uid")

        cow_swap.order_book_api = MagicMock()
        cow_swap.order_book_api.get_order_link.return_value = "http://order.link"

        mock_order_instance = MagicMock()
        mock_order_instance.uid = MagicMock(root="order_uid")
        mock_order_instance.url = "http://order.link"
        mock_completed_order.return_value = mock_order_instance

        order = await CowSwap.swap_tokens_to_exact_tokens(
            amount=1000,
            account=MagicMock(address="0xAccount", _address="0xAccount"),
            chain=MagicMock(value=[100]),
            sell_token="0xSell",
            buy_token="0xBuy",
        )

        assert order.uid.root == "order_uid"
        assert order.url == "http://order.link"


def test_check_cowswap_order_pending(cow_swap):
    order = MagicMock()
    order.url = "http://order.url"

    with (
        patch("iwa.plugins.gnosis.cow.requests.get") as mock_get,
        patch("iwa.plugins.gnosis.cow.time.sleep") as mock_sleep,
    ):
        mock_get.side_effect = [
            MagicMock(
                status_code=200,
                json=lambda: {
                    "status": "open",
                    "executedSellAmount": "0",
                    "executedBuyAmount": "0",
                },
            ),
            MagicMock(
                status_code=200,
                json=lambda: {
                    "status": "fulfilled",
                    "executedSellAmount": "100",
                    "executedBuyAmount": "0",
                },
            ),
        ]

        success = cow_swap.check_cowswap_order(order)
        assert success is True
        assert mock_get.call_count == 2
        mock_sleep.assert_called_once()
