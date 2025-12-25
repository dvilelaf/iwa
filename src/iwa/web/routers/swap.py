"""Swap Router for Web API."""

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from web3 import Web3

from iwa.core.chain import ChainInterfaces
from iwa.plugins.gnosis.cow import CowSwap
from iwa.web.dependencies import verify_auth, wallet

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/swap", tags=["swap"])


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
async def swap_tokens(req: SwapRequest, auth: bool = Depends(verify_auth)):
    """Execute a token swap via CowSwap."""
    try:
        from iwa.plugins.gnosis.cow import OrderType

        order_type = OrderType.SELL if req.order_type == "sell" else OrderType.BUY

        success = await wallet.transfer_service.swap(
            account_address_or_tag=req.account,
            amount_eth=req.amount_eth,
            sell_token_name=req.sell_token,
            buy_token_name=req.buy_token,
            chain_name=req.chain,
            order_type=order_type,
        )

        if success:
            return {"status": "success", "message": "Swap order placed and executed"}
        else:
            return {"status": "pending", "message": "Swap order placed, waiting for execution"}
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
        amount_wei = Web3.to_wei(amount, "ether")

        chain_obj = ChainInterfaces().get(chain).chain
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
        chain_obj = ChainInterfaces().get(chain).chain
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
        error_msg = str(e)
        # Handle common CowSwap errors with clearer messages
        if "NoLiquidity" in error_msg or "no route found" in error_msg.lower():
            raise HTTPException(
                status_code=400,
                detail="No liquidity available for this token pair. Try a different pair.",
            ) from None
        logger.error(f"Error getting max swap amount: {e}")
        raise HTTPException(status_code=400, detail=error_msg) from None
