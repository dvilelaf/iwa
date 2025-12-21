"""Web Server for IWA."""

import datetime
import json
import os
import time
from typing import Optional
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger
from pydantic import BaseModel, field_validator
from web3 import Web3

from iwa.core.chain import ChainInterfaces
from iwa.core.db import SentTransaction
from iwa.core.wallet import Wallet

WEBUI_PASSWORD = os.getenv("WEBUI_PASSWORD")

app = FastAPI(title="Iwa Web Interface")


async def verify_auth(request: Request):
    """Verify bearer token authentication if configured."""
    if WEBUI_PASSWORD:
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Unauthorized")
        token = auth_header.split(" ")[1]
        if token != WEBUI_PASSWORD:
            raise HTTPException(status_code=401, detail="Unauthorized")
    return True


# CORS middleware - restricted to localhost only for security
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8080",
        "http://127.0.0.1:8080",
        "http://localhost:3000",  # For development
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _obscure_url(url: str) -> str:
    """Obscure RPC URL to hide API keys and sensitive path info."""
    try:
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}/..."
    except Exception:
        return "N/A"


# Wallet instance
wallet = Wallet()

# Static files
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
if not os.path.exists(STATIC_DIR):
    os.makedirs(STATIC_DIR)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class TransactionRequest(BaseModel):
    """Request to send a transaction.

    Note: amount_eth is in human-readable ETH units (e.g., 1.5 for 1.5 ETH).
    Conversion to wei happens internally.
    """

    from_address: str
    to_address: str
    amount_eth: float
    token: str
    chain: str

    @field_validator("from_address", "to_address")
    @classmethod
    def validate_address(cls, v: str) -> str:
        """Validate address format - must be hex address or alphanumeric tag."""
        v = v.strip()
        if not v:
            raise ValueError("Address cannot be empty")
        # Allow hex addresses or alphanumeric tags
        if v.startswith("0x"):
            if len(v) != 42 or not all(c in "0123456789abcdefABCDEF" for c in v[2:]):
                raise ValueError("Invalid hex address format")
        elif not v.replace("_", "").replace("-", "").isalnum():
            raise ValueError("Tag must be alphanumeric")
        return v

    @field_validator("amount_eth")
    @classmethod
    def validate_amount_eth(cls, v: float) -> float:
        """Validate amount_eth is positive."""
        if v <= 0:
            raise ValueError("Amount must be positive")
        if v > 1e18:
            raise ValueError("Amount too large")
        return v

    @field_validator("chain")
    @classmethod
    def validate_chain(cls, v: str) -> str:
        """Validate chain is alphanumeric."""
        v = v.strip().lower()
        if not v.replace("_", "").replace("-", "").isalnum():
            raise ValueError("Must be alphanumeric")
        return v

    @field_validator("token")
    @classmethod
    def validate_token(cls, v: str) -> str:
        """Validate token is alphanumeric (preserve case for token names)."""
        v = v.strip()
        if not v.replace("_", "").replace("-", "").isalnum():
            raise ValueError("Must be alphanumeric")
        return v


class AccountCreateRequest(BaseModel):
    """Request to create a new account."""

    tag: Optional[str] = None

    @field_validator("tag")
    @classmethod
    def validate_tag(cls, v: Optional[str]) -> Optional[str]:
        """Validate tag is safe alphanumeric string."""
        if v is None:
            return v
        v = v.strip()
        if not v:
            return None
        # Only allow alphanumeric, underscores, hyphens
        if not v.replace("_", "").replace("-", "").isalnum():
            raise ValueError("Tag must be alphanumeric (underscores and hyphens allowed)")
        if len(v) > 50:
            raise ValueError("Tag too long (max 50 characters)")
        return v


class SafeCreateRequest(BaseModel):
    """Request to create a new Safe."""

    tag: str
    owners: list[str]
    threshold: int
    chains: list[str]


@app.get("/", response_class=HTMLResponse)
def read_index():
    """Serve the main index.html file."""
    index_path = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_path):
        with open(index_path, "r") as f:
            return f.read()
    return "<h1>Iwa Web Terminal</h1><p>Static files not found yet.</p>"


@app.get("/api/state")
def get_state():
    """Get the current application state including available chains and tokens."""
    chains = [name for name, _ in ChainInterfaces().items()]
    tokens = {}
    native_currencies = {}
    for chain in chains:
        interface = ChainInterfaces().get(chain)
        if interface:
            tokens[chain] = list(interface.tokens.keys())
            native_currencies[chain] = interface.chain.native_currency
    return {
        "chains": chains,
        "tokens": tokens,
        "native_currencies": native_currencies,
        "default_chain": "gnosis",
    }


@app.get("/api/accounts")
def get_accounts(chain: str = "gnosis", tokens: str = "", auth: bool = Depends(verify_auth)):
    """Get accounts with optional token balances.

    Args:
        chain: Chain name
        tokens: Comma-separated list of token names to fetch balances for (e.g. "native,OLAS")
        auth: Authentication dependency

    """
    chain = chain.lower()

    # Fetch account data (without balances first)
    accounts_data = wallet.account_service.get_account_data()
    requested_tokens = [t.strip() for t in tokens.split(",") if t.strip()] if tokens else []

    # Fetch account data (without balances first)
    accounts_data = wallet.account_service.get_account_data()

    # Fetch balances only for requested tokens
    token_balances = None
    if requested_tokens:
        _, token_balances = wallet.get_accounts_balances(chain, requested_tokens)

    result = []
    for addr, acct in accounts_data.items():
        if hasattr(acct, "chains"):
            if chain not in acct.chains:
                continue
            acct_type = "Safe"
        else:
            acct_type = "EOA"

        acct_balances = {}
        # Only include balances for requested tokens
        for t in requested_tokens:
            if t == "native":
                bal = wallet.get_native_balance_eth(addr, chain)
                acct_balances["native"] = f"{bal:.4f}" if bal is not None else None
            else:
                bal = token_balances.get(addr, {}).get(t) if token_balances else None
                acct_balances[t] = f"{bal:.4f}" if bal is not None else None

        result.append(
            {"tag": acct.tag, "address": addr, "type": acct_type, "balances": acct_balances}
        )
    return result


@app.get("/api/transactions")
def get_transactions(chain: str = "gnosis", auth: bool = Depends(verify_auth)):
    """Get recent transactions for a specific chain."""
    chain = chain.lower()
    recent = (
        SentTransaction.select()
        .where(
            (SentTransaction.chain == chain)
            & (SentTransaction.timestamp > (datetime.datetime.now() - datetime.timedelta(hours=24)))
        )
        .order_by(SentTransaction.timestamp.desc())
    )

    result = []
    for tx in recent:
        result.append(
            {
                "timestamp": tx.timestamp.isoformat(),
                "chain": tx.chain.capitalize(),
                "from": tx.from_tag or tx.from_address,
                "to": tx.to_tag or tx.to_address,
                "token": tx.token,
                "amount": f"{float(tx.amount_wei or 0) / 10**18:.4f}",
                "value_eur": f"€{(tx.value_eur or 0.0):.2f}",
                "status": "Confirmed",
                "hash": tx.tx_hash,
                "gas_cost": str(tx.gas_cost or "0"),
                "gas_value_eur": f"€{tx.gas_value_eur:.4f}" if tx.gas_value_eur else "?",
                "tags": json.loads(tx.tags) if tx.tags else [],
            }
        )
    return result


@app.get("/api/rpc-status")
def get_rpc_status(auth: bool = Depends(verify_auth)):
    """Get the status of all configured RPC endpoints."""
    status = {}
    for chain_name, interface in ChainInterfaces().items():
        if interface.chain.rpcs:
            try:
                start_time = time.time()
                block = interface.web3.eth.block_number
                latency = int((time.time() - start_time) * 1000)
                status[chain_name] = {"status": "online", "block": block, "latency": f"{latency}ms"}
            except Exception as e:
                status[chain_name] = {"status": "offline", "error": str(e)}
        else:
            status[chain_name] = {"status": "offline", "error": "No RPC configured"}
    return status


@app.post("/api/send")
def send_transaction(req: TransactionRequest, auth: bool = Depends(verify_auth)):
    """Send a transaction from an account."""
    try:
        tx_hash = wallet.send(
            from_address_or_tag=req.from_address,
            to_address_or_tag=req.to_address,
            amount_wei=Web3.to_wei(req.amount_eth_eth, "ether"),
            token_address_or_name=req.token,
            chain_name=req.chain,
        )
        return {"status": "success", "hash": tx_hash}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from None


@app.post("/api/accounts/eoa")
def create_eoa(req: AccountCreateRequest, auth: bool = Depends(verify_auth)):
    """Create a new EOA account with the given tag."""
    try:
        wallet.key_storage.create_account(req.tag)
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from None


@app.post("/api/accounts/safe")
def create_safe(req: SafeCreateRequest, auth: bool = Depends(verify_auth)):
    """Create a new Safe multisig account."""
    try:
        # We use a timestamp-based salt to avoid collisions
        import time

        salt_nonce = int(time.time() * 1000)

        # Deploy on all requested chains
        for chain_name in req.chains:
            wallet.safe_service.create_safe(
                "master",  # WebUI uses master as deployer by default
                req.owners,
                req.threshold,
                chain_name,
                req.tag,
                salt_nonce,
            )
        return {"status": "success"}
    except Exception as e:
        logger.error(f"Error creating Safe: {e}")
        raise HTTPException(status_code=400, detail=str(e)) from None


class SwapRequest(BaseModel):
    """Request to swap tokens via CowSwap.

    Note: amount_eth is in human-readable ETH units (e.g., 1.5 for 1.5 tokens).
    """

    account: str
    sell_token: str
    buy_token: str
    amount_eth: float
    order_type: str  # "sell" or "buy"
    chain: str = "gnosis"

    @field_validator("order_type")
    @classmethod
    def validate_order_type(cls, v: str) -> str:
        """Validate order type."""
        v = v.strip().lower()
        if v not in ("sell", "buy"):
            raise ValueError("Order type must be 'sell' or 'buy'")
        return v


@app.post("/api/swap")
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


@app.get("/api/swap/quote")
def get_swap_quote(
    account: str,
    sell_token: str,
    buy_token: str,
    amount: float,
    mode: str = "sell",
    chain: str = "gnosis",
    auth: bool = Depends(verify_auth),
):
    """Get a quote for a swap.

    For sell mode: given sell amount, returns expected buy amount.
    For buy mode: given buy amount, returns required sell amount.
    """
    try:
        import asyncio
        from concurrent.futures import ThreadPoolExecutor

        from web3 import Web3

        from iwa.core.chain import ChainInterfaces
        from iwa.plugins.gnosis.cow import CowSwap

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


@app.get("/api/swap/max-amount")
def get_swap_max_amount(
    account: str,
    sell_token: str,
    buy_token: str,
    mode: str = "sell",
    chain: str = "gnosis",
    auth: bool = Depends(verify_auth),
):
    """Get the maximum amount for a swap.

    For sell mode: returns the account's balance of the sell token.
    For buy mode: calculates max buy amount using CowSwap quote API.
    """
    try:
        from web3 import Web3

        # Get the sell token balance
        sell_balance = wallet.balance_service.get_erc20_balance_wei(account, sell_token, chain)
        if sell_balance is None or sell_balance == 0:
            return {"max_amount": 0.0, "mode": mode}

        sell_balance_eth = float(Web3.from_wei(sell_balance, "ether"))

        if mode == "sell":
            return {"max_amount": sell_balance_eth, "mode": "sell"}

        # For buy mode, use CowSwap to get quote in a separate thread
        import asyncio
        from concurrent.futures import ThreadPoolExecutor

        from iwa.core.chain import ChainInterfaces
        from iwa.plugins.gnosis.cow import CowSwap

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


def run_server(host: str = "127.0.0.1", port: int = 8080):
    """Run the FastAPI web server."""
    import signal
    import sys

    import uvicorn

    def signal_handler(sig, frame):
        """Handle Ctrl+C gracefully."""
        logger.info("Shutting down server...")
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    uvicorn.run(app, host=host, port=port)
