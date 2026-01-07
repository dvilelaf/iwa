"""Swap Router for Web API."""

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor

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


class SwapRequest(BaseModel):
    """Request to swap tokens via CowSwap."""

    account: str = Field(description="Account address or tag")
    sell_token: str = Field(description="Token symbol to sell (e.g., WXDAI)")
    buy_token: str = Field(description="Token symbol to buy (e.g., OLAS)")
    amount_eth: float = Field(description="Amount in human-readable units (ETH)")
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
    def validate_amount(cls, v: float) -> float:
        """Validate amount is positive."""
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
    description="Execute a token swap on CowSwap (CoW Protocol).",
)
@limiter.limit("10/minute")
async def swap_tokens(request: Request, req: SwapRequest, auth: bool = Depends(verify_auth)):
    """Execute a token swap via CowSwap."""
    try:
        from iwa.plugins.gnosis.cow import OrderType

        order_type = OrderType.SELL if req.order_type == "sell" else OrderType.BUY

        order_data = await wallet.transfer_service.swap(
            account_address_or_tag=req.account,
            amount_eth=req.amount_eth,
            sell_token_name=req.sell_token,
            buy_token_name=req.buy_token,
            chain_name=req.chain,
            order_type=order_type,
        )

        if order_data:
            # Calculate analytics
            executed_sell = float(order_data.get("executedSellAmount", 0))
            executed_buy = float(order_data.get("executedBuyAmount", 0))

            # Get actual token decimals for accurate calculations
            sell_decimals = 18
            buy_decimals = 18
            try:
                from iwa.core.chain import ChainInterfaces
                from iwa.core.contracts.erc20 import ERC20Contract

                chain_interface = ChainInterfaces().get(req.chain)
                if chain_interface:
                    sell_addr = chain_interface.chain.get_token_address(req.sell_token)
                    buy_addr = chain_interface.chain.get_token_address(req.buy_token)
                    if sell_addr:
                        sell_decimals = ERC20Contract(sell_addr, req.chain).decimals
                    if buy_addr:
                        buy_decimals = ERC20Contract(buy_addr, req.chain).decimals
            except Exception:
                pass  # Default to 18 if we can't get decimals

            # Calculating price ratio with actual decimals
            execution_price = 0.0
            if executed_sell > 0:
                # Get quote prices from CowSwap API (already adjusted for decimals)
                quote = order_data.get("quote", {})
                sell_price_usd = float(quote.get("sellTokenPrice", 0) or 0)
                buy_price_usd = float(quote.get("buyTokenPrice", 0) or 0)

                # Calculate value using correct decimals
                value_sold = (executed_sell / (10**sell_decimals)) * sell_price_usd
                value_bought = (executed_buy / (10**buy_decimals)) * buy_price_usd

                value_change_pct = 0.0
                if value_sold > 0:
                    # Change = (Value Bought - Value Sold) / Value Sold * 100
                    # Positive = Gain, Negative = Loss
                    value_change_pct = ((value_bought - value_sold) / value_sold) * 100

            # Log analytics for visibility
            logger.info(
                f"Swap Analytics: Execution Price={execution_price:.4f}, "
                f"Value Change={value_change_pct:.2f}%, "
                f"Sell=${sell_price_usd:.2f}, Buy=${buy_price_usd:.2f}"
            )

            return {
                "status": "success",
                "message": "Swap executed successfully",
                "order": order_data,
                "analytics": {
                    "executed_sell_amount": executed_sell,
                    "executed_buy_amount": executed_buy,
                    "value_change_pct": value_change_pct if "value_change_pct" in locals() else 0,
                    "sell_price_usd": sell_price_usd if "sell_price_usd" in locals() else 0,
                    "buy_price_usd": buy_price_usd if "buy_price_usd" in locals() else 0,
                },
            }
        else:
            return {
                "status": "pending",
                "message": "Swap order placed, waiting for execution or failed",
            }
    except Exception as e:
        logger.error(f"Error swapping tokens: {e}")
        # import traceback
        # logger.error(traceback.format_exc())
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
        amount_wei = Web3.to_wei(amount, "ether")

        chain_interface = ChainInterfaces().get(chain)
        chain_obj: SupportedChain = chain_interface.chain  # type: ignore[assignment]
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
                if mode == "sell":
                    # Get buy amount for given sell amount
                    return loop.run_until_complete(
                        cow.get_max_buy_amount_wei(
                            amount_wei,
                            chain_obj.get_token_address(sell_token),
                            chain_obj.get_token_address(buy_token),
                        )
                    )
                else:
                    # Get sell amount for given buy amount
                    return loop.run_until_complete(
                        cow.get_max_sell_amount_wei(
                            amount_wei,
                            chain_obj.get_token_address(sell_token),
                            chain_obj.get_token_address(buy_token),
                        )
                    )
            finally:
                loop.close()

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(run_async_quote)
            result_wei = future.result(timeout=30)

        result_eth = float(Web3.from_wei(result_wei, "ether"))
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
        # Get the sell token balance
        sell_balance = wallet.balance_service.get_erc20_balance_wei(account, sell_token, chain)
        if sell_balance is None or sell_balance == 0:
            return {"max_amount": 0.0, "mode": mode}

        sell_balance_eth = float(Web3.from_wei(sell_balance, "ether"))

        if mode == "sell":
            return {"max_amount": sell_balance_eth, "mode": "sell"}

        # For buy mode, use CowSwap to get quote in a separate thread
        chain_interface = ChainInterfaces().get(chain)
        chain_obj: SupportedChain = chain_interface.chain  # type: ignore[assignment]
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

        max_buy_eth = float(Web3.from_wei(max_buy_wei, "ether"))
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
