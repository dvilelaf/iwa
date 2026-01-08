"""Swap Router for Web API."""

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from slowapi import Limiter
from slowapi.util import get_remote_address
from web3 import Web3

from iwa.core.chain import ChainInterfaces, SupportedChain
from iwa.plugins.gnosis.cow import CowSwap
from iwa.web.dependencies import verify_auth, wallet

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/swap", tags=["swap"])

limiter = Limiter(key_func=get_remote_address)


@lru_cache(maxsize=128)
def get_cached_decimals(token_address: str, chain: str) -> int:
    """Get token decimals with caching to prevent excessive RPC calls."""
    try:
        from iwa.core.contracts.erc20 import ERC20Contract

        # Note: ERC20Contract init makes 4 RPC calls (decimals, symbol, name, supply)
        # Caching this result is critical for performance.
        # FIX: Web3 requires checksum addresses
        checksum_address = Web3.to_checksum_address(token_address)
        contract = ERC20Contract(checksum_address, chain)
        return contract.decimals
    except Exception as e:
        logger.warning(f"Error fetching decimals for {token_address}: {e}")
        return 18


class SwapRequest(BaseModel):
    """Request to swap tokens via CowSwap."""

    account: str = Field(description="Account address or tag")
    sell_token: str = Field(description="Token symbol to sell (e.g., WXDAI)")
    buy_token: str = Field(description="Token symbol to buy (e.g., OLAS)")
    amount_eth: Optional[float] = Field(
        default=None,
        description="Amount in human-readable units (ETH). If null, uses entire balance.",
    )
    order_type: str = Field(description="Type of order: 'sell' or 'buy'")
    chain: str = Field(default="gnosis", description="Blockchain network name")

    @field_validator("order_type")
    @classmethod
    def validate_order_type(cls, v: str) -> str:
        """Validate order type is 'sell' or 'buy'."""
        v = v.strip().lower()
        if v not in ("sell", "buy"):
            raise ValueError("Order type must be 'sell' or 'buy'")
        return v

    @field_validator("account")
    @classmethod
    def validate_account(cls, v: str) -> str:
        """Validate account address or tag."""
        if not v:
            raise ValueError("Account cannot be empty")
        if v.startswith("0x") and len(v) != 42:
            raise ValueError("Invalid account format")
        return v

    @field_validator("sell_token", "buy_token")
    @classmethod
    def validate_tokens(cls, v: str) -> str:
        """Validate token address or symbol."""
        if not v:
            raise ValueError("Token cannot be empty")
        if v.startswith("0x") and len(v) != 42:
            raise ValueError("Invalid token address")
        return v

    @field_validator("amount_eth")
    @classmethod
    def validate_amount(cls, v: Optional[float]) -> Optional[float]:
        """Validate amount is positive (if provided)."""
        if v is None:
            return v  # None means use entire balance
        if v <= 0:  # Swaps must be positive
            raise ValueError("Amount must be greater than 0")
        if v > 1e18:  # Sanity check
            raise ValueError("Amount too large")
        return v

    @field_validator("chain")
    @classmethod
    def validate_chain(cls, v: str) -> str:
        """Validate chain name is alphanumeric."""
        if not v.replace("-", "").isalnum():
            raise ValueError("Invalid chain name")
        return v


@router.post(
    "",
    summary="Swap Tokens",
    description="Execute a token swap on CowSwap (CoW Protocol). Returns immediately after order placement.",
)
@limiter.limit("10/minute")
async def swap_tokens(request: Request, req: SwapRequest, auth: bool = Depends(verify_auth)):
    """Execute a token swap via CowSwap.

    This endpoint places the order and returns immediately.
    Use GET /api/swap/orders to track order status.
    """
    try:
        from iwa.plugins.gnosis.cow import OrderType

        order_type = OrderType.SELL if req.order_type == "sell" else OrderType.BUY

        # Run swap in a separate thread with its own event loop to avoid
        # asyncio.run() conflict with cowdao_cowpy library
        def run_swap_in_thread():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                return loop.run_until_complete(
                    wallet.transfer_service.swap(
                        account_address_or_tag=req.account,
                        amount_eth=req.amount_eth,
                        sell_token_name=req.sell_token,
                        buy_token_name=req.buy_token,
                        chain_name=req.chain,
                        order_type=order_type,
                    )
                )
            finally:
                loop.close()

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(run_swap_in_thread)
            order_data = future.result(timeout=120)

        if order_data:
            # Check if order was executed (blocking mode) or just placed (non-blocking)
            status = order_data.get("status", "unknown")

            if status == "open":
                # Non-blocking: order placed but not yet executed
                return {
                    "status": "success",
                    "message": "Swap order placed! Track progress in Recent Orders.",
                    "order": order_data,
                }
            elif status == "fulfilled":
                # Order was executed (if wait_for_execution=True was used)
                executed_sell = float(order_data.get("executedSellAmount", 0))
                executed_buy = float(order_data.get("executedBuyAmount", 0))

                return {
                    "status": "success",
                    "message": "Swap executed successfully!",
                    "order": order_data,
                    "analytics": {
                        "executed_sell_amount": executed_sell,
                        "executed_buy_amount": executed_buy,
                    },
                }
            else:
                # Other status (expired, cancelled, etc)
                return {
                    "status": "success",
                    "message": f"Order placed with status: {status}",
                    "order": order_data,
                }
        else:
            raise HTTPException(status_code=400, detail="Failed to place swap order")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error swapping tokens: {e}")
        raise HTTPException(status_code=400, detail=str(e)) from None


@router.get(
    "/quote",
    summary="Get Swap Quote",
    description="Get a price quote for a potential swap from CowSwap API.",
)
def get_swap_quote(
    account: str,
    sell_token: str,
    buy_token: str,
    amount: float,
    mode: str = "sell",
    chain: str = "gnosis",
    auth: bool = Depends(verify_auth),
):
    """Get a quote for a swap."""
    try:
        chain_interface = ChainInterfaces().get(chain)
        chain_obj: SupportedChain = chain_interface.chain  # type: ignore[assignment]
        account_obj = wallet.account_service.resolve_account(account)
        signer = wallet.key_storage.get_signer(account_obj.address)

        if not signer:
            raise HTTPException(status_code=400, detail="Could not get signer for account")

        # Get token addresses and decimals
        sell_token_addr = chain_obj.get_token_address(sell_token)
        buy_token_addr = chain_obj.get_token_address(buy_token)

        sell_decimals = get_cached_decimals(sell_token_addr, chain)
        buy_decimals = get_cached_decimals(buy_token_addr, chain)

        # Convert input amount to wei using the correct decimals
        if mode == "sell":
            amount_wei = int(amount * (10**sell_decimals))
        else:
            amount_wei = int(amount * (10**buy_decimals))

        def run_async_quote():
            """Run the async CowSwap quote in a new event loop."""
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                cow = CowSwap(private_key_or_signer=signer, chain=chain_obj)
                if mode == "sell":
                    # Get buy amount for given sell amount
                    return loop.run_until_complete(
                        cow.get_max_buy_amount_wei(
                            amount_wei,
                            sell_token_addr,
                            buy_token_addr,
                        )
                    )
                else:
                    # Get sell amount for given buy amount
                    return loop.run_until_complete(
                        cow.get_max_sell_amount_wei(
                            amount_wei,
                            sell_token_addr,
                            buy_token_addr,
                        )
                    )
            finally:
                loop.close()

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(run_async_quote)
            result_wei = future.result(timeout=30)

        # Convert result using the correct decimals
        if mode == "sell":
            result_eth = result_wei / (10**buy_decimals)
        else:
            result_eth = result_wei / (10**sell_decimals)

        return {"amount": result_eth, "mode": mode}

    except Exception as e:
        error_msg = str(e)
        if "NoLiquidity" in error_msg or "no route found" in error_msg.lower():
            raise HTTPException(
                status_code=400, detail="No liquidity available for this token pair."
            ) from None
        logger.error(f"Error getting swap quote: {e}")
        raise HTTPException(status_code=400, detail=error_msg) from None


@router.get(
    "/max-amount",
    summary="Get Max Swap Amount",
    description="Calculate maximum available amount for a swap, considering balances and slippage.",
)
def get_swap_max_amount(
    account: str,
    sell_token: str,
    buy_token: str,
    mode: str = "sell",
    chain: str = "gnosis",
    auth: bool = Depends(verify_auth),
):
    """Get the maximum amount for a swap."""
    try:
        # Get token address and decimals
        chain_interface = ChainInterfaces().get(chain)
        chain_obj = chain_interface.chain
        sell_token_addr = chain_obj.get_token_address(sell_token)
        sell_decimals = get_cached_decimals(sell_token_addr, chain)

        # Get the sell token balance
        sell_balance = wallet.balance_service.get_erc20_balance_wei(account, sell_token, chain)
        if sell_balance is None or sell_balance == 0:
            return {"max_amount": 0.0, "mode": mode}

        sell_balance_eth = sell_balance / (10**sell_decimals)

        if mode == "sell":
            return {"max_amount": sell_balance_eth, "mode": "sell"}

        # For buy mode, use CowSwap to get quote in a separate thread
        account_obj = wallet.account_service.resolve_account(account)
        signer = wallet.key_storage.get_signer(account_obj.address)

        if not signer:
            raise HTTPException(status_code=400, detail="Could not get signer for account")

        def run_async_quote():
            """Run the async CowSwap quote in a new event loop."""
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                cow = CowSwap(private_key_or_signer=signer, chain=chain_obj)
                return loop.run_until_complete(
                    cow.get_max_buy_amount_wei(
                        sell_balance,
                        chain_obj.get_token_address(sell_token),
                        chain_obj.get_token_address(buy_token),
                    )
                )
            finally:
                loop.close()

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(run_async_quote)
            max_buy_wei = future.result(timeout=30)

        # Convert buy amount using buy token decimals (which involves querying decimals for buy token too)
        # Note: cow.get_max_buy_amount_wei returns result in terms of BUY token amount if we asked for max sell?
        # Re-reading: The function calculates "max buy amount".
        # If mode is buy, we want to know how much SELL token we need? No, function is "get_swap_max_amount".
        # If mode is buy, frontend is asking "I want to buy MAX?". That doesn't make sense.
        # "MAX" button is usually only for SELL.
        # The frontend calls this endpoint with mode="sell" or "buy" depending on button.
        # If mode="buy", handleMaxClick(false) calls this. But Max Buy button is usually HIDDEN in UI for sell mode.
        # In buy mode (Buy exact amount), MAX means "Buy as much as possible with my sell token".
        # So we return the max BUY amount.

        # We need buy token decimals
        buy_token_addr = chain_obj.get_token_address(buy_token)
        buy_decimals = get_cached_decimals(buy_token_addr, chain)

        max_buy_eth = max_buy_wei / (10**buy_decimals)
        return {"max_amount": max_buy_eth, "mode": "buy", "sell_balance": sell_balance_eth}

    except Exception as e:
        import traceback

        error_msg = str(e) or repr(e)
        logger.error(f"Error getting max swap amount: {error_msg}\n{traceback.format_exc()}")
        # Handle common CowSwap errors with clearer messages
        if "NoLiquidity" in error_msg or "no route found" in error_msg.lower():
            raise HTTPException(
                status_code=400,
                detail="No liquidity available for this token pair. Try a different pair.",
            ) from None
        raise HTTPException(status_code=400, detail=error_msg or "Unknown error") from None


class WrapRequest(BaseModel):
    """Request to wrap/unwrap native currency."""

    account: str = Field(description="Account address or tag")
    amount_eth: float = Field(description="Amount in human-readable units (ETH)")
    chain: str = Field(default="gnosis", description="Blockchain network name")

    @field_validator("account")
    @classmethod
    def validate_account(cls, v: str) -> str:
        """Validate account address or tag."""
        if not v:
            raise ValueError("Account cannot be empty")
        if v.startswith("0x") and len(v) != 42:
            raise ValueError("Invalid account format")
        return v

    @field_validator("amount_eth")
    @classmethod
    def validate_amount(cls, v: float) -> float:
        """Validate amount is positive."""
        if v <= 0:
            raise ValueError("Amount must be greater than 0")
        if v > 1e18:
            raise ValueError("Amount too large")
        return v

    @field_validator("chain")
    @classmethod
    def validate_chain(cls, v: str) -> str:
        """Validate chain name is alphanumeric."""
        if not v.replace("-", "").isalnum():
            raise ValueError("Invalid chain name")
        return v


@router.post(
    "/wrap",
    summary="Wrap Native Currency",
    description="Wrap native currency to wrapped token (e.g., xDAI → WXDAI).",
)
@limiter.limit("10/minute")
async def wrap_native(request: Request, req: WrapRequest, auth: bool = Depends(verify_auth)):
    """Wrap native currency to WXDAI."""
    try:
        amount_wei = Web3.to_wei(req.amount_eth, "ether")
        tx_hash = wallet.transfer_service.wrap_native(
            account_address_or_tag=req.account,
            amount_wei=amount_wei,
            chain_name=req.chain,
        )
        if tx_hash:
            return {
                "status": "success",
                "message": f"Wrapped {req.amount_eth:.4f} xDAI → WXDAI",
                "hash": tx_hash,
            }
        else:
            raise HTTPException(status_code=400, detail="Wrap transaction failed")
    except Exception as e:
        logger.error(f"Error wrapping: {e}")
        raise HTTPException(status_code=400, detail=str(e)) from None


@router.post(
    "/unwrap",
    summary="Unwrap to Native Currency",
    description="Unwrap wrapped token to native currency (e.g., WXDAI → xDAI).",
)
@limiter.limit("10/minute")
async def unwrap_native(request: Request, req: WrapRequest, auth: bool = Depends(verify_auth)):
    """Unwrap WXDAI to native xDAI."""
    try:
        amount_wei = Web3.to_wei(req.amount_eth, "ether")
        tx_hash = wallet.transfer_service.unwrap_native(
            account_address_or_tag=req.account,
            amount_wei=amount_wei,
            chain_name=req.chain,
        )
        if tx_hash:
            return {
                "status": "success",
                "message": f"Unwrapped {req.amount_eth:.4f} WXDAI → xDAI",
                "hash": tx_hash,
            }
        else:
            raise HTTPException(status_code=400, detail="Unwrap transaction failed")
    except Exception as e:
        logger.error(f"Error unwrapping: {e}")
        raise HTTPException(status_code=400, detail=str(e)) from None


@router.get(
    "/wrap/balance",
    summary="Get Wrap/Unwrap Balances",
    description="Get native and WXDAI balances for an account.",
)
def get_wrap_balances(
    account: str,
    chain: str = "gnosis",
    auth: bool = Depends(verify_auth),
):
    """Get balances for wrap/unwrap operations."""
    try:
        native_balance_wei = wallet.balance_service.get_native_balance_wei(account, chain)
        wxdai_balance_wei = wallet.balance_service.get_erc20_balance_wei(account, "WXDAI", chain)

        native_eth = float(Web3.from_wei(native_balance_wei or 0, "ether"))
        wxdai_eth = float(Web3.from_wei(wxdai_balance_wei or 0, "ether"))

        return {
            "native": native_eth,
            "wxdai": wxdai_eth,
        }
    except Exception as e:
        logger.error(f"Error getting wrap balances: {e}")
        raise HTTPException(status_code=400, detail=str(e)) from None


@router.get(
    "/orders",
    summary="Get Recent Orders",
    description="Get recent swap orders for an account from CowSwap API.",
)
def get_recent_orders(
    account: str = "master",
    chain: str = "gnosis",
    limit: int = 5,
    auth: bool = Depends(verify_auth),
):
    """Get recent orders for an account from CowSwap API."""
    import time

    import requests

    try:
        # Resolve account address
        account_obj = wallet.account_service.resolve_account(account)
        address = account_obj.address

        # Get API URL for chain
        chain_interface = ChainInterfaces().get(chain)
        chain_id = chain_interface.chain.chain_id

        api_urls = {
            100: "https://api.cow.fi/xdai",
            1: "https://api.cow.fi/mainnet",
            11155111: "https://api.cow.fi/sepolia",
        }
        api_url = api_urls.get(chain_id)
        if not api_url:
            return {"orders": []}

        # Fetch orders from CowSwap API
        url = f"{api_url}/api/v1/account/{address}/orders?limit={limit}"
        response = requests.get(url, timeout=10)

        if response.status_code != 200:
            return {"orders": []}

        orders = response.json()
        current_time = int(time.time())

        # Process orders for frontend
        result = []
        chain_interface = ChainInterfaces().get(chain)

        for order in orders[:limit]:
            order_data = _process_order_for_frontend(order, chain_interface, chain, current_time)
            result.append(order_data)

        return {"orders": result}

    except Exception as e:
        logger.error(f"Error fetching orders: {e}")
        return {"orders": []}


def _process_order_for_frontend(
    order: dict, chain_interface: Any, chain: str, current_time: int
) -> dict:
    """Process a single order for frontend display."""
    valid_to = int(order.get("validTo", 0))
    created = order.get("creationDate", "")
    status = order.get("status", "unknown")

    # Calculate progress for pending orders
    progress_pct = 0
    if status in ["open", "presignaturePending"] and valid_to > current_time:
        # Calculate time elapsed vs total time
        created_ts = 0
        if created:
            try:
                from datetime import datetime

                created_ts = int(datetime.fromisoformat(created.replace("Z", "+00:00")).timestamp())
            except ValueError:
                created_ts = current_time - 180  # Default 3 min ago

        total_duration = valid_to - created_ts
        time_remaining = valid_to - current_time
        if total_duration > 0:
            progress_pct = int(max(0, min(100, (time_remaining / total_duration) * 100)))
    else:
        time_remaining = 0

    # Resolve token addresses to names
    sell_token_addr = order.get("sellToken", "")
    buy_token_addr = order.get("buyToken", "")
    sell_token_name = (
        chain_interface.chain.get_token_name(sell_token_addr) or sell_token_addr[:8] + "..."
    )
    buy_token_name = (
        chain_interface.chain.get_token_name(buy_token_addr) or buy_token_addr[:8] + "..."
    )

    # Calculate human-readable amounts
    try:
        sell_decimals = 18
        buy_decimals = 18

        # Try to get decimals from contract with caching!
        try:
            sell_decimals = get_cached_decimals(sell_token_addr, chain)
        except Exception:
            pass

        try:
            buy_decimals = get_cached_decimals(buy_token_addr, chain)
        except Exception:
            pass

        sell_amount_wei = float(order.get("sellAmount", "0"))
        buy_amount_wei = float(order.get("buyAmount", "0"))

        sell_amount_fmt = sell_amount_wei / (10**sell_decimals)
        buy_amount_fmt = buy_amount_wei / (10**buy_decimals)

    except Exception as e:
        logger.warning(f"Error converting amounts: {e}")
        sell_amount_fmt = 0.0
        buy_amount_fmt = 0.0

    return {
        "uid": order.get("uid", "")[:12] + "...",
        "full_uid": order.get("uid", ""),
        "status": status,
        "sellToken": sell_token_name,
        "buyToken": buy_token_name,
        "sellAmount": f"{sell_amount_fmt:.4f}",
        "buyAmount": f"{buy_amount_fmt:.4f}",
        "validTo": valid_to,
        "created": created,
        "progressPct": round(progress_pct, 1),
        "timeRemaining": max(0, valid_to - current_time),
    }
