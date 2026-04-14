"""Utilities for CowSwap plugin."""

import importlib
import logging
import sys
from typing import Any

logger = logging.getLogger(__name__)


class CowApiUnavailableError(RuntimeError):
    """Raised when the CoW Protocol API is unreachable.

    Callers should treat this as a transient failure and retry later,
    rather than letting it propagate as an unhandled exception.
    """

# Lazy import cache for cowdao_cowpy modules to avoid asyncio.run() conflict
_cowpy_cache: dict[str, Any] = {}

# Mapping of module names to (module_path, attribute_name)
_COWPY_IMPORTS: dict[str, tuple[str, str]] = {
    "DEFAULT_APP_DATA_HASH": ("cowdao_cowpy.app_data.utils", "DEFAULT_APP_DATA_HASH"),
    "Chain": ("cowdao_cowpy.common.chains", "Chain"),
    "SupportedChainId": ("cowdao_cowpy.common.chains", "SupportedChainId"),
    "Order": ("cowdao_cowpy.contracts.order", "Order"),
    "PreSignSignature": ("cowdao_cowpy.contracts.sign", "PreSignSignature"),
    "SigningScheme": ("cowdao_cowpy.contracts.sign", "SigningScheme"),
    "CompletedOrder": ("cowdao_cowpy.cow.swap", "CompletedOrder"),
    "get_order_quote": ("cowdao_cowpy.cow.swap", "get_order_quote"),
    "post_order": ("cowdao_cowpy.cow.swap", "post_order"),
    "sign_order": ("cowdao_cowpy.cow.swap", "sign_order"),
    "swap_tokens": ("cowdao_cowpy.cow.swap", "swap_tokens"),
    "OrderBookApi": ("cowdao_cowpy.order_book.api", "OrderBookApi"),
    "Envs": ("cowdao_cowpy.order_book.config", "Envs"),
    "OrderBookAPIConfigFactory": ("cowdao_cowpy.order_book.config", "OrderBookAPIConfigFactory"),
    "OrderQuoteRequest": ("cowdao_cowpy.order_book.generated.model", "OrderQuoteRequest"),
    "OrderQuoteSide3": ("cowdao_cowpy.order_book.generated.model", "OrderQuoteSide3"),
    "OrderQuoteSideKindBuy": ("cowdao_cowpy.order_book.generated.model", "OrderQuoteSideKindBuy"),
    "TokenAmount": ("cowdao_cowpy.order_book.generated.model", "TokenAmount"),
    "OrderQuoteSide1": ("cowdao_cowpy.order_book.generated.model", "OrderQuoteSide1"),
    "OrderQuoteSideKindSell": ("cowdao_cowpy.order_book.generated.model", "OrderQuoteSideKindSell"),
}


def get_cowpy_module(name: str) -> Any:
    """Lazily import cowdao_cowpy submodules with httpx shim to bypass CloudFront WAF.

    Temporarily replaces sys.modules["httpx"] with our requests-based shim
    during cowdao-cowpy imports. This ensures:
    1. Import-time code (app_data.utils) uses the shim (urllib3 TLS fingerprint)
    2. Runtime code in cowdao-cowpy modules uses the shim (bound at import time)
    3. Other httpx users (python-telegram-bot) are NOT affected (restored after import)
    """
    if name not in _cowpy_cache:
        if name not in _COWPY_IMPORTS:
            raise ValueError(f"Unknown cowpy module: {name}")

        # Import shim before swapping (this import uses real httpx internally)
        from iwa.plugins.gnosis import cowpy_httpx_shim

        # Swap sys.modules["httpx"] with our shim during cowpy import
        real_httpx = sys.modules.get("httpx")
        sys.modules["httpx"] = cowpy_httpx_shim
        try:
            module_path, attr_name = _COWPY_IMPORTS[name]
            module = importlib.import_module(module_path)
            _cowpy_cache[name] = getattr(module, attr_name)
        except Exception as exc:
            if name == "DEFAULT_APP_DATA_HASH":
                # cowdao_cowpy.app_data.utils runs build_all_app_codes() at module
                # level, which contacts api.cow.fi. If the API is unreachable (DNS
                # hijack, outage, maintenance), the import raises. We convert this to
                # a controlled error so callers can fail the swap gracefully instead
                # of crashing the whole process.
                logger.warning(
                    "CoW Protocol API unreachable — could not fetch DEFAULT_APP_DATA_HASH "
                    f"({exc}). CoW swaps will be unavailable until the API recovers."
                )
                raise CowApiUnavailableError(
                    f"CoW Protocol API unreachable: {exc}"
                ) from exc
            raise
        finally:
            # Always restore real httpx, even if import fails
            if real_httpx is not None:
                sys.modules["httpx"] = real_httpx
            else:
                sys.modules.pop("httpx", None)

    return _cowpy_cache[name]
