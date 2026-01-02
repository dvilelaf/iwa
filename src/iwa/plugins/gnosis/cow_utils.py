"""Utilities for CowSwap plugin."""

from typing import Any

# Lazy import cache for cowdao_cowpy modules to avoid asyncio.run() conflict
_cowpy_cache: dict[str, Any] = {}


def get_cowpy_module(name: str) -> Any:  # noqa: C901
    """Lazily import cowdao_cowpy submodules to avoid asyncio conflict at import time."""
    if name not in _cowpy_cache:
        if name == "DEFAULT_APP_DATA_HASH":
            from cowdao_cowpy.app_data.utils import DEFAULT_APP_DATA_HASH

            _cowpy_cache[name] = DEFAULT_APP_DATA_HASH
        elif name == "Chain":
            from cowdao_cowpy.common.chains import Chain

            _cowpy_cache[name] = Chain
        elif name == "SupportedChainId":
            from cowdao_cowpy.common.chains import SupportedChainId

            _cowpy_cache[name] = SupportedChainId
        elif name == "Order":
            from cowdao_cowpy.contracts.order import Order

            _cowpy_cache[name] = Order
        elif name == "PreSignSignature":
            from cowdao_cowpy.contracts.sign import PreSignSignature

            _cowpy_cache[name] = PreSignSignature
        elif name == "SigningScheme":
            from cowdao_cowpy.contracts.sign import SigningScheme

            _cowpy_cache[name] = SigningScheme
        elif name == "CompletedOrder":
            from cowdao_cowpy.cow.swap import CompletedOrder

            _cowpy_cache[name] = CompletedOrder
        elif name == "get_order_quote":
            from cowdao_cowpy.cow.swap import get_order_quote

            _cowpy_cache[name] = get_order_quote
        elif name == "post_order":
            from cowdao_cowpy.cow.swap import post_order

            _cowpy_cache[name] = post_order
        elif name == "sign_order":
            from cowdao_cowpy.cow.swap import sign_order

            _cowpy_cache[name] = sign_order
        elif name == "swap_tokens":
            from cowdao_cowpy.cow.swap import swap_tokens

            _cowpy_cache[name] = swap_tokens
        elif name == "OrderBookApi":
            from cowdao_cowpy.order_book.api import OrderBookApi

            _cowpy_cache[name] = OrderBookApi
        elif name == "Envs":
            from cowdao_cowpy.order_book.config import Envs

            _cowpy_cache[name] = Envs
        elif name == "OrderBookAPIConfigFactory":
            from cowdao_cowpy.order_book.config import OrderBookAPIConfigFactory

            _cowpy_cache[name] = OrderBookAPIConfigFactory
        elif name == "OrderQuoteRequest":
            from cowdao_cowpy.order_book.generated.model import OrderQuoteRequest

            _cowpy_cache[name] = OrderQuoteRequest
        elif name == "OrderQuoteSide3":
            from cowdao_cowpy.order_book.generated.model import OrderQuoteSide3

            _cowpy_cache[name] = OrderQuoteSide3
        elif name == "OrderQuoteSideKindBuy":
            from cowdao_cowpy.order_book.generated.model import OrderQuoteSideKindBuy

            _cowpy_cache[name] = OrderQuoteSideKindBuy
        elif name == "TokenAmount":
            from cowdao_cowpy.order_book.generated.model import TokenAmount

            _cowpy_cache[name] = TokenAmount
        elif name == "OrderQuoteSide1":
            from cowdao_cowpy.order_book.generated.model import OrderQuoteSide1

            _cowpy_cache[name] = OrderQuoteSide1
        elif name == "OrderQuoteSideKindSell":
            from cowdao_cowpy.order_book.generated.model import OrderQuoteSideKindSell

            _cowpy_cache[name] = OrderQuoteSideKindSell
        else:
            raise ValueError(f"Unknown cowpy module: {name}")
    return _cowpy_cache[name]
