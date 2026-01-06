"""CoW Swap quote utilities."""

from typing import TYPE_CHECKING

from eth_typing.evm import ChecksumAddress
from web3.types import Wei

from iwa.plugins.gnosis.cow_utils import get_cowpy_module

if TYPE_CHECKING:
    from cowdao_cowpy.order_book.config import Envs


# Placeholders for cowdao_cowpy functions/classes to allow patching in tests
get_order_quote = None
OrderQuoteRequest = None
OrderQuoteSide1 = None
OrderQuoteSide3 = None
OrderQuoteSideKindBuy = None
OrderQuoteSideKindSell = None
TokenAmount = None
SupportedChainId = None
OrderBookApi = None
OrderBookAPIConfigFactory = None


async def get_max_sell_amount_wei(
    amount_wei: Wei,
    sell_token: ChecksumAddress,
    buy_token: ChecksumAddress,
    chain_id_val: int,
    account_address: ChecksumAddress,
    safe_address: ChecksumAddress | None = None,
    app_data: str | None = None,
    env: "Envs" = "prod",
    slippage_tolerance: float = 0.005,
) -> int:
    """Calculate the estimated sell amount needed to buy a fixed amount of tokens."""
    if app_data is None:
        app_data = get_cowpy_module("DEFAULT_APP_DATA_HASH")

    # In testing context, these might be patched
    global \
        get_order_quote, \
        OrderQuoteRequest, \
        OrderQuoteSide3, \
        OrderQuoteSideKindBuy, \
        TokenAmount, \
        SupportedChainId, \
        OrderBookApi, \
        OrderBookAPIConfigFactory

    _get_order_quote = get_order_quote or get_cowpy_module("get_order_quote")
    _order_quote_request_cls = OrderQuoteRequest or get_cowpy_module("OrderQuoteRequest")
    _order_quote_side_cls = OrderQuoteSide3 or get_cowpy_module("OrderQuoteSide3")
    _order_quote_side_kind_buy_cls = OrderQuoteSideKindBuy or get_cowpy_module(
        "OrderQuoteSideKindBuy"
    )
    _token_amount_cls = TokenAmount or get_cowpy_module("TokenAmount")
    _supported_chain_id_cls = SupportedChainId or get_cowpy_module("SupportedChainId")
    _order_book_api_cls = OrderBookApi or get_cowpy_module("OrderBookApi")
    _order_book_api_config_factory_cls = OrderBookAPIConfigFactory or get_cowpy_module(
        "OrderBookAPIConfigFactory"
    )

    chain_id = _supported_chain_id_cls(chain_id_val)
    order_book_api = _order_book_api_cls(
        _order_book_api_config_factory_cls.get_config(env, chain_id)
    )

    order_quote_request = _order_quote_request_cls(
        sellToken=sell_token,
        buyToken=buy_token,
        from_=safe_address if safe_address is not None else account_address,
        appData=app_data,
    )

    order_side = _order_quote_side_cls(
        kind=_order_quote_side_kind_buy_cls.buy,
        buyAmountAfterFee=_token_amount_cls(str(amount_wei)),
    )

    order_quote = await _get_order_quote(order_quote_request, order_side, order_book_api)

    sell_amount_wei = int(int(order_quote.quote.sellAmount.root) * (1.0 + slippage_tolerance))
    return sell_amount_wei


async def get_max_buy_amount_wei(
    sell_amount_wei: Wei,
    sell_token: ChecksumAddress,
    buy_token: ChecksumAddress,
    chain_id_val: int,
    account_address: ChecksumAddress,
    safe_address: ChecksumAddress | None = None,
    app_data: str | None = None,
    env: "Envs" = "prod",
    slippage_tolerance: float = 0.005,
) -> int:
    """Calculate the maximum buy amount for a given sell amount."""
    if app_data is None:
        app_data = get_cowpy_module("DEFAULT_APP_DATA_HASH")

    global \
        get_order_quote, \
        OrderQuoteRequest, \
        OrderQuoteSide1, \
        OrderQuoteSideKindSell, \
        TokenAmount, \
        SupportedChainId, \
        OrderBookApi, \
        OrderBookAPIConfigFactory

    _get_order_quote = get_order_quote or get_cowpy_module("get_order_quote")
    _order_quote_request_cls = OrderQuoteRequest or get_cowpy_module("OrderQuoteRequest")
    _order_quote_side_cls = OrderQuoteSide1 or get_cowpy_module("OrderQuoteSide1")
    _order_quote_side_kind_sell_cls = OrderQuoteSideKindSell or get_cowpy_module(
        "OrderQuoteSideKindSell"
    )
    _token_amount_cls = TokenAmount or get_cowpy_module("TokenAmount")
    _supported_chain_id_cls = SupportedChainId or get_cowpy_module("SupportedChainId")
    _order_book_api_cls = OrderBookApi or get_cowpy_module("OrderBookApi")
    _order_book_api_config_factory_cls = OrderBookAPIConfigFactory or get_cowpy_module(
        "OrderBookAPIConfigFactory"
    )

    chain_id = _supported_chain_id_cls(chain_id_val)
    order_book_api = _order_book_api_cls(
        _order_book_api_config_factory_cls.get_config(env, chain_id)
    )

    order_quote_request = _order_quote_request_cls(
        sellToken=sell_token,
        buyToken=buy_token,
        from_=safe_address if safe_address is not None else account_address,
        appData=app_data,
    )

    order_side = _order_quote_side_cls(
        kind=_order_quote_side_kind_sell_cls.sell,
        sellAmountBeforeFee=_token_amount_cls(str(sell_amount_wei)),
    )

    order_quote = await _get_order_quote(order_quote_request, order_side, order_book_api)

    # Apply slippage (reduce buy amount)
    buy_amount_wei = int(int(order_quote.quote.buyAmount.root) * (1.0 - slippage_tolerance))
    return buy_amount_wei
