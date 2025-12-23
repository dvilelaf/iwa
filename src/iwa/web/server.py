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
                acct_balances["native"] = f"{bal:.2f}" if bal is not None else None
            else:
                bal = token_balances.get(addr, {}).get(t) if token_balances else None
                acct_balances[t] = f"{bal:.2f}" if bal is not None else None

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
                "amount": f"{float(tx.amount_wei or 0) / 10**18:.2f}",
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


# ==============================================================================
# Olas Plugin API Endpoints
# ==============================================================================


@app.get("/api/olas/price")
def get_olas_price(auth: bool = Depends(verify_auth)):
    """Get current OLAS token price in EUR from CoinGecko."""
    try:
        from iwa.core.pricing import PriceService

        price_service = PriceService()
        price = price_service.get_token_price("autonolas", "eur")

        return {"price_eur": price, "symbol": "OLAS"}
    except Exception as e:
        logger.error(f"Error fetching OLAS price: {e}")
        return {"price_eur": None, "symbol": "OLAS", "error": str(e)}


@app.get("/api/olas/services/basic")
def get_olas_services_basic(chain: str = "gnosis", auth: bool = Depends(verify_auth)):
    """Get basic Olas service info from config (fast, no RPC calls).

    Returns just service metadata for instant card rendering.
    """
    try:
        from iwa.core.models import Config
        from iwa.plugins.olas.models import OlasConfig

        config = Config()
        if "olas" not in config.plugins:
            return []

        olas_config = OlasConfig.model_validate(config.plugins["olas"])

        result = []
        for service_key, service in olas_config.services.items():
            if service.chain_name != chain:
                continue

            # Get tags from wallet storage (fast, local lookup)
            accounts = {}
            for role, addr in [
                ("agent", service.agent_address),
                ("safe", str(service.multisig_address) if service.multisig_address else None),
                ("owner", service.service_owner_address),
            ]:
                if addr:
                    stored = wallet.key_storage.find_stored_account(addr)
                    accounts[role] = {
                        "address": addr,
                        "tag": stored.tag if stored else None,
                        "native": None,  # Will be filled by details endpoint
                        "olas": None,
                    }

            result.append({
                "key": service_key,
                "name": service.service_name,
                "service_id": service.service_id,
                "chain": service.chain_name,
                "accounts": accounts,
                "staking": {"is_staked": bool(service.staking_contract_address)} if service.staking_contract_address else None,
            })

        return result

    except ImportError:
        return []
    except Exception as e:
        logger.error(f"Error getting basic Olas services: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from None


@app.get("/api/olas/services/{service_key}/details")
def get_olas_service_details(service_key: str, auth: bool = Depends(verify_auth)):
    """Get full details for a single Olas service (staking, balances)."""
    try:
        from iwa.core.models import Config
        from iwa.plugins.olas.models import OlasConfig
        from iwa.plugins.olas.service_manager import ServiceManager

        config = Config()
        if "olas" not in config.plugins:
            raise HTTPException(status_code=404, detail="Olas plugin not configured")

        olas_config = OlasConfig.model_validate(config.plugins["olas"])
        if service_key not in olas_config.services:
            raise HTTPException(status_code=404, detail=f"Service '{service_key}' not found")

        service = olas_config.services[service_key]
        chain = service.chain_name

        manager = ServiceManager(wallet)
        manager.service = service
        staking_status = manager.get_staking_status()

        # Get balances
        balances = {}
        for role, addr in [
            ("agent", service.agent_address),
            ("safe", str(service.multisig_address) if service.multisig_address else None),
            ("owner", service.service_owner_address),
        ]:
            if addr:
                native_bal = wallet.get_native_balance_eth(addr, chain)
                olas_bal = wallet.balance_service.get_erc20_balance_wei(addr, "OLAS", chain)
                olas_bal_eth = float(olas_bal) / 1e18 if olas_bal else 0
                stored = wallet.key_storage.find_stored_account(addr)
                balances[role] = {
                    "address": addr,
                    "tag": stored.tag if stored else None,
                    "native": f"{native_bal:.2f}" if native_bal else "0.00",
                    "olas": f"{olas_bal_eth:.2f}",
                }

        staking = None
        if staking_status:
            staking = {
                "is_staked": staking_status.is_staked,
                "staking_state": staking_status.staking_state,
                "staking_contract_address": staking_status.staking_contract_address,
                "staking_contract_name": staking_status.staking_contract_name,
                "accrued_reward_olas": staking_status.accrued_reward_olas,
                "accrued_reward_wei": staking_status.accrued_reward_wei,
                "epoch_number": staking_status.epoch_number,
                "epoch_end_utc": staking_status.epoch_end_utc,
                "remaining_epoch_seconds": staking_status.remaining_epoch_seconds,
                "mech_requests_this_epoch": staking_status.mech_requests_this_epoch,
                "required_mech_requests": staking_status.required_mech_requests,
                "has_enough_requests": staking_status.has_enough_requests,
                "liveness_ratio_passed": staking_status.liveness_ratio_passed,
                "unstake_available_at": staking_status.unstake_available_at,
            }

        return {
            "key": service_key,
            "accounts": balances,
            "staking": staking,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting service details: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from None


@app.get("/api/olas/services")
def get_olas_services(chain: str = "gnosis", auth: bool = Depends(verify_auth)):
    """Get all Olas services with staking status for a specific chain.

    Returns service information including:
    - Service metadata (name, id, chain)
    - Account addresses and balances (agent, safe, operator)
    - Staking status and rewards
    """
    try:
        from iwa.core.models import Config
        from iwa.plugins.olas.models import OlasConfig
        from iwa.plugins.olas.service_manager import ServiceManager

        config = Config()

        # Check if Olas plugin is available
        if "olas" not in config.plugins:
            return []

        olas_config = OlasConfig.model_validate(config.plugins["olas"])

        result = []
        for service_key, service in olas_config.services.items():
            if service.chain_name != chain:
                continue

            # Create service manager for this service
            manager = ServiceManager(wallet)
            manager.service = service

            # Get staking status
            staking_status = manager.get_staking_status()

            # Get balances for service accounts
            balances = {}
            accounts = {
                "agent": service.agent_address,
                "safe": str(service.multisig_address) if service.multisig_address else None,
                "owner": service.service_owner_address,
            }

            for role, address in accounts.items():
                if address:
                    native_bal = wallet.get_native_balance_eth(address, chain)
                    olas_bal = wallet.balance_service.get_erc20_balance_wei(address, "OLAS", chain)
                    olas_bal_eth = float(olas_bal) / 1e18 if olas_bal else 0

                    # Get tag if account exists in wallet
                    stored = wallet.key_storage.find_stored_account(address)
                    tag = stored.tag if stored else None

                    balances[role] = {
                        "address": address,
                        "tag": tag,
                        "native": f"{native_bal:.2f}" if native_bal else "0.00",
                        "olas": f"{olas_bal_eth:.2f}",
                    }

            # Build service data
            service_data = {
                "key": service_key,
                "name": service.service_name,
                "service_id": service.service_id,
                "chain": service.chain_name,
                "accounts": balances,
                "staking": None,
            }

            if staking_status:
                service_data["staking"] = {
                    "is_staked": staking_status.is_staked,
                    "staking_state": staking_status.staking_state,
                    "staking_contract_address": staking_status.staking_contract_address,
                    "staking_contract_name": staking_status.staking_contract_name,
                    "accrued_reward_olas": staking_status.accrued_reward_olas,
                    "accrued_reward_wei": staking_status.accrued_reward_wei,
                    "epoch_number": staking_status.epoch_number,
                    "epoch_end_utc": staking_status.epoch_end_utc,
                    "remaining_epoch_seconds": staking_status.remaining_epoch_seconds,
                    "mech_requests_this_epoch": staking_status.mech_requests_this_epoch,
                    "required_mech_requests": staking_status.required_mech_requests,
                    "has_enough_requests": staking_status.has_enough_requests,
                    "liveness_ratio_passed": staking_status.liveness_ratio_passed,
                    "unstake_available_at": staking_status.unstake_available_at,
                }

            result.append(service_data)

        return result

    except ImportError:
        # Olas plugin not installed
        return []
    except Exception as e:
        logger.error(f"Error getting Olas services: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from None


@app.post("/api/olas/claim/{service_key}")
def claim_olas_rewards(service_key: str, auth: bool = Depends(verify_auth)):
    """Claim staking rewards for a specific Olas service."""
    try:
        from iwa.core.models import Config
        from iwa.plugins.olas.contracts.staking import StakingContract
        from iwa.plugins.olas.models import OlasConfig
        from iwa.plugins.olas.service_manager import ServiceManager

        config = Config()
        if "olas" not in config.plugins:
            raise HTTPException(status_code=404, detail="Olas plugin not configured")

        olas_config = OlasConfig.model_validate(config.plugins["olas"])

        if service_key not in olas_config.services:
            raise HTTPException(status_code=404, detail=f"Service '{service_key}' not found")

        service = olas_config.services[service_key]
        manager = ServiceManager(wallet)
        manager.service = service

        if not service.staking_contract_address:
            raise HTTPException(status_code=400, detail="Service is not staked")

        staking = StakingContract(service.staking_contract_address, service.chain_name)
        success, amount = manager.claim_rewards(staking_contract=staking)

        if success:
            return {"status": "success", "claimed_olas": amount / 1e18}
        else:
            raise HTTPException(status_code=400, detail="Claim failed - no rewards or transaction error")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error claiming rewards: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from None


@app.post("/api/olas/unstake/{service_key}")
def unstake_olas_service(service_key: str, auth: bool = Depends(verify_auth)):
    """Unstake an Olas service."""
    try:
        from iwa.core.models import Config
        from iwa.plugins.olas.contracts.staking import StakingContract
        from iwa.plugins.olas.models import OlasConfig
        from iwa.plugins.olas.service_manager import ServiceManager

        logger.info(f"Requests to unstake service: {service_key}")

        config = Config()
        if "olas" not in config.plugins:
            raise HTTPException(status_code=404, detail="Olas plugin not configured")

        olas_config = OlasConfig.model_validate(config.plugins["olas"])

        if service_key not in olas_config.services:
            raise HTTPException(status_code=404, detail=f"Service '{service_key}' not found")

        service = olas_config.services[service_key]
        manager = ServiceManager(wallet)
        manager.service = service

        logger.info(f"Unstaking service {service.service_id} on chain {service.chain_name}")
        logger.info(f"Staking contract: {service.staking_contract_address}")

        if not service.staking_contract_address:
            raise HTTPException(status_code=400, detail="Service is not staked")

        staking = StakingContract(service.staking_contract_address, service.chain_name)
        success = manager.unstake(staking)

        if success:
            logger.info(f"Successfully unstaked service {service.service_id}")
            return {"status": "success"}
        else:
            logger.error(f"Failed to unstake service {service.service_id}")
            raise HTTPException(status_code=400, detail="Unstake failed")

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error unstaking service {service_key}")
        raise HTTPException(status_code=500, detail=str(e)) from None


@app.get("/api/olas/staking-contracts")
def get_staking_contracts(chain: str = "gnosis"):
    """Get available staking contracts for a chain.

    Only returns contracts that have available slots (not full).
    Uses parallel loading for faster response.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    from iwa.plugins.olas.constants import OLAS_TRADER_STAKING_CONTRACTS
    from iwa.plugins.olas.contracts.staking import StakingContract

    contracts = OLAS_TRADER_STAKING_CONTRACTS.get(chain, {})
    result = []

    def check_contract(name: str, addr: str):
        """Check a single contract for available slots."""
        try:
            staking = StakingContract(str(addr), chain)
            staked_services = staking.get_service_ids()
            available_slots = staking.max_num_services - len(staked_services)
            if available_slots > 0:
                return {
                    "name": f"{name} ({available_slots} slots)",
                    "address": str(addr),
                    "available_slots": available_slots
                }
        except Exception:
            pass
        return None

    # Load contracts in parallel
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(check_contract, name, str(addr)): name for name, addr in contracts.items()}
        for future in as_completed(futures):
            contract_info = future.result()
            if contract_info:
                result.append(contract_info)

    return result


@app.post("/api/olas/stake/{service_key}")
def stake_olas_service(
    service_key: str,
    staking_contract: str,
    auth: bool = Depends(verify_auth),
):
    """Stake an Olas service in a staking contract.

    Args:
        service_key: The service key to stake
        staking_contract: The staking contract address

    """
    try:
        from iwa.core.models import Config
        from iwa.plugins.olas.contracts.staking import StakingContract
        from iwa.plugins.olas.models import OlasConfig
        from iwa.plugins.olas.service_manager import ServiceManager

        logger.info(f"Staking service {service_key} in contract {staking_contract}")
        print(f"[STAKE] Starting stake for {service_key} with contract {staking_contract}", flush=True)

        config = Config()
        if "olas" not in config.plugins:
            raise HTTPException(status_code=404, detail="Olas plugin not configured")

        olas_config = OlasConfig.model_validate(config.plugins["olas"])

        if service_key not in olas_config.services:
            raise HTTPException(status_code=404, detail=f"Service '{service_key}' not found")

        service = olas_config.services[service_key]
        logger.info(f"Service found: id={service.service_id}, chain={service.chain_name}")
        print(f"[STAKE] Service: id={service.service_id}, chain={service.chain_name}", flush=True)

        if service.staking_contract_address:
            raise HTTPException(status_code=400, detail="Service is already staked")

        manager = ServiceManager(wallet, service_key=service_key)
        staking = StakingContract(staking_contract, service.chain_name)
        logger.info(f"Staking contract: min_deposit={staking.min_staking_deposit}, slots={staking.max_num_services}")
        print(f"[STAKE] Contract: min_deposit={staking.min_staking_deposit}, slots={staking.max_num_services}", flush=True)

        success = manager.stake(staking)
        logger.info(f"Stake result: {success}")
        print(f"[STAKE] Result: {success}", flush=True)

        if success:
            return {"status": "success", "staking_contract": staking_contract}
        else:
            raise HTTPException(status_code=400, detail="Stake failed - check logs for details")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error staking service: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from None


@app.post("/api/olas/drain/{service_key}")
def drain_olas_service(
    service_key: str,
    target: Optional[str] = None,
    auth: bool = Depends(verify_auth),
):
    """Drain all accounts from an Olas service to a target address.

    This drains Safe, Agent, and Owner accounts, claiming any staking rewards first.

    Args:
        service_key: The service key to drain
        target: Optional target address/tag (defaults to master account)

    """
    try:
        from iwa.core.models import Config
        from iwa.plugins.olas.models import OlasConfig
        from iwa.plugins.olas.service_manager import ServiceManager

        config = Config()
        if "olas" not in config.plugins:
            raise HTTPException(status_code=404, detail="Olas plugin not configured")

        olas_config = OlasConfig.model_validate(config.plugins["olas"])

        if service_key not in olas_config.services:
            raise HTTPException(status_code=404, detail=f"Service '{service_key}' not found")

        # Use ServiceManager to drain all accounts
        manager = ServiceManager(wallet, service_key=service_key)

        # Target defaults to master
        target_address = target or wallet.master_account.address

        drained = manager.drain_service(target_address=target_address)

        return {"status": "success", "drained": drained}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error draining service: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from None


class CreateServiceRequest(BaseModel):
    """Request to create a new Olas service."""

    service_name: str
    chain: str = "gnosis"
    stake_on_create: bool = False
    staking_contract: Optional[str] = None


@app.post("/api/olas/create")
def create_olas_service(req: CreateServiceRequest, auth: bool = Depends(verify_auth)):
    """Create a new Olas service and deploy it.

    This creates a new service on the specified chain, then runs spin_up to
    deploy it fully. Optionally stakes it if a staking_contract is provided.
    """
    try:
        from iwa.plugins.olas.service_manager import ServiceManager
        from iwa.plugins.olas.contracts.staking import StakingContract

        logger.info(f"Creating service: name={req.service_name}, chain={req.chain}, stake_on_create={req.stake_on_create}, staking_contract={req.staking_contract}")

        # Load staking contract FIRST if we're going to stake
        # We need its staking_token_address for service creation
        staking_contract = None
        token_address = None  # Token to use for bonding

        if req.stake_on_create and req.staking_contract:
            logger.info(f"Loading staking contract: {req.staking_contract}")
            staking_contract = StakingContract(req.staking_contract, req.chain)
            token_address = staking_contract.staking_token_address
            logger.info(f"Staking contract loaded: min_deposit={staking_contract.min_staking_deposit}, "
                       f"max_services={staking_contract.max_num_services}, token={token_address}")

        manager = ServiceManager(wallet)

        # Pass the staking token if we're going to stake, otherwise no token
        service_id = manager.create(
            chain_name=req.chain,
            service_name=req.service_name,
            token_address_or_tag=token_address,
            bond_amount_wei=staking_contract.min_staking_deposit if staking_contract else 1,
        )

        if not service_id:
            raise HTTPException(status_code=400, detail="Failed to create service")

        result = {"status": "success", "service_id": service_id, "service_key": f"{req.chain}:{service_id}"}
        logger.info(f"Service created with ID: {service_id}")

        # Spin up to deploy the service fully (staking contract already loaded above)
        logger.info(f"Running spin_up with staking_contract={'yes' if staking_contract else 'no'}")
        spin_up_success = manager.spin_up(staking_contract=staking_contract)
        result["deployed"] = spin_up_success
        logger.info(f"spin_up result: {spin_up_success}")
        if staking_contract:
            result["staked"] = spin_up_success

        if not spin_up_success:
            result["status"] = "partial"
            result["message"] = "Service created but deployment failed"

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating service: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from None


@app.post("/api/olas/terminate/{service_key}")
def terminate_olas_service(service_key: str, auth: bool = Depends(verify_auth)):
    """Terminate (wind down) an Olas service.

    This unstakes (if staked), terminates, and unbonds the service,
    returning it to PRE_REGISTRATION state.
    """
    try:
        from iwa.core.models import Config
        from iwa.plugins.olas.contracts.staking import StakingContract
        from iwa.plugins.olas.models import OlasConfig
        from iwa.plugins.olas.service_manager import ServiceManager

        config = Config()
        if "olas" not in config.plugins:
            raise HTTPException(status_code=404, detail="Olas plugin not configured")

        olas_config = OlasConfig.model_validate(config.plugins["olas"])

        if service_key not in olas_config.services:
            raise HTTPException(status_code=404, detail=f"Service '{service_key}' not found")

        service = olas_config.services[service_key]
        manager = ServiceManager(wallet)
        manager.service = service

        # Get staking contract if staked
        staking_contract = None
        if service.staking_contract_address:
            staking_contract = StakingContract(service.staking_contract_address, service.chain_name)

        success = manager.wind_down(staking_contract=staking_contract)

        if success:
            return {"status": "success", "message": "Service terminated"}
        else:
            raise HTTPException(status_code=400, detail="Failed to terminate service")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error terminating service: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from None


@app.get("/api/olas/debug/{service_key}")
async def debug_olas_service(service_key: str):
    """Debug endpoint to check service manager state."""
    logger.info(f"Debugging service {service_key}")
    try:
        from iwa.core.models import Config
        from iwa.core.wallet import Wallet
        from iwa.plugins.olas.models import OlasConfig
        from iwa.plugins.olas.service_manager import ServiceManager
        from iwa.plugins.olas.constants import OLAS_CONTRACTS

        config = Config()
        wallet = Wallet()
        if "olas" not in config.plugins:
             return {"error": "Olas plugin not found in config"}

        # Ensure we can load service manager
        sm = ServiceManager(wallet, service_key)

        staking_status = None
        try:
             # Try to get detailed staking status
             status_obj = sm.get_staking_status()
             if status_obj:
                 staking_status = status_obj.model_dump()
        except Exception as e:
            logger.error(f"Debug staking status failed: {e}")

        debug_info = {
            "service_id": sm.service.service_id if sm.service else None,
            "chain_name": sm.chain_name,
            "registry_address": str(sm.registry.address),
            "manager_address": str(sm.manager.address),
            "staking_contract_address_from_service": str(sm.service.staking_contract_address) if sm.service else None,
            "OLAS_CONTRACTS_ENTRY": OLAS_CONTRACTS.get(sm.chain_name, {}),
            "staking_status": staking_status
        }
        return debug_info
    except Exception as e:
        logger.exception(f"Debug failed: {e}")
        return {"error": str(e)}


class FundServiceRequest(BaseModel):
    """Request to fund Olas service accounts."""

    agent_amount_eth: float = 0.0
    safe_amount_eth: float = 0.0

    @field_validator("agent_amount_eth", "safe_amount_eth")
    @classmethod
    def validate_amounts(cls, v: float) -> float:
        """Validate amounts are non-negative."""
        if v < 0:
            raise ValueError("Amount cannot be negative")
        if v > 1e18:
            raise ValueError("Amount too large")
        return v


@app.post("/api/olas/fund/{service_key}")
def fund_olas_service(
    service_key: str,
    req: FundServiceRequest,
    auth: bool = Depends(verify_auth),
):
    """Fund Olas service accounts from the master wallet.

    Sends native tokens to the agent and/or safe addresses.
    """
    try:
        from iwa.core.models import Config
        from iwa.plugins.olas.models import OlasConfig

        config = Config()
        if "olas" not in config.plugins:
            raise HTTPException(status_code=404, detail="Olas plugin not configured")

        olas_config = OlasConfig.model_validate(config.plugins["olas"])

        if service_key not in olas_config.services:
            raise HTTPException(status_code=404, detail=f"Service '{service_key}' not found")

        service = olas_config.services[service_key]
        chain_name = service.chain_name
        result = {"status": "success", "funded": {}}

        # Fund agent if amount > 0
        if req.agent_amount_eth > 0 and service.agent_address:
            tx_hash = wallet.send(
                from_address_or_tag="master",
                to_address_or_tag=service.agent_address,
                amount_wei=Web3.to_wei(req.agent_amount_eth, "ether"),
                token_address_or_name="native",
                chain_name=chain_name,
            )
            result["funded"]["agent"] = {"amount": req.agent_amount_eth, "tx_hash": tx_hash}

        # Fund safe if amount > 0
        if req.safe_amount_eth > 0 and service.multisig_address:
            tx_hash = wallet.send(
                from_address_or_tag="master",
                to_address_or_tag=str(service.multisig_address),
                amount_wei=Web3.to_wei(req.safe_amount_eth, "ether"),
                token_address_or_name="native",
                chain_name=chain_name,
            )
            result["funded"]["safe"] = {"amount": req.safe_amount_eth, "tx_hash": tx_hash}

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error funding service: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from None


@app.post("/api/olas/checkpoint/{service_key}")
def checkpoint_olas_service(service_key: str, auth: bool = Depends(verify_auth)):
    """Call checkpoint on the staking contract for a specific Olas service."""
    try:
        from iwa.plugins.olas.service_manager import ServiceManager

        manager = ServiceManager(wallet, service_key=service_key)
        # We use a grace period of 0 since it's a manual call
        success = manager.call_checkpoint(grace_period_seconds=0)

        if success:
            return {"status": "success"}
        else:
            raise HTTPException(status_code=400, detail="Checkpoint failed - epoch may not have ended yet")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error calling checkpoint: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from None


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
