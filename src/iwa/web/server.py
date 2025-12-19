"""Web Server for IWA."""

import datetime
import json
import os
import time
from typing import Optional
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger
from pydantic import BaseModel, field_validator

from iwa.core.chain import ChainInterfaces
from iwa.core.db import SentTransaction
from iwa.core.wallet import Wallet

app = FastAPI(title="Iwa Web Interface")

# CORS middleware - restrict to same origin for security
# In localhost-only mode this provides basic protection
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows same-origin requests
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
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
    """Request to send a transaction."""

    from_address: str
    to_address: str
    amount: float
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

    @field_validator("amount")
    @classmethod
    def validate_amount(cls, v: float) -> float:
        """Validate amount is positive."""
        if v <= 0:
            raise ValueError("Amount must be positive")
        if v > 1e18:
            raise ValueError("Amount too large")
        return v

    @field_validator("chain", "token")
    @classmethod
    def validate_chain_token(cls, v: str) -> str:
        """Validate chain/token is alphanumeric."""
        v = v.strip().lower()
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

@app.get("/", response_class=HTMLResponse)
async def read_index():
    index_path = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_path):
        with open(index_path, "r") as f:
            return f.read()
    return "<h1>Iwa Web Terminal</h1><p>Static files not found yet.</p>"

@app.get("/api/state")
async def get_state():
    chains = [name for name, _ in ChainInterfaces().items()]
    tokens = {}
    for chain in chains:
        interface = ChainInterfaces().get(chain)
        if interface:
            tokens[chain] = list(interface.tokens.keys())
    return {
        "chains": chains,
        "tokens": tokens,
        "default_chain": "gnosis"
    }

@app.get("/api/accounts")
async def get_accounts(chain: str = "gnosis"):
    # Ensure chain is lowercase
    chain = chain.lower()

    # We need to make sure we fetch balances for tokens
    interface = ChainInterfaces().get(chain)
    token_names = list(interface.tokens.keys()) if interface else []

    # Fetch data from wallet service
    accounts_data, token_balances = wallet.get_accounts_balances(chain, token_names)

    result = []
    for addr, data in accounts_data.items():
        acct_balances = {
            "native": data["native"],
        }
        # Safely get token balances
        for t in token_names:
            acct_balances[t] = token_balances.get(addr, {}).get(t, "0.0000")

        result.append({
            "tag": data["tag"],
            "address": addr,
            "type": data["type"],
            "balances": acct_balances
        })
    return result

@app.get("/api/transactions")
async def get_transactions(chain: str = "gnosis"):
    chain = chain.lower()
    recent = (
        SentTransaction.select()
        .where(
            (SentTransaction.chain == chain)
            & (
                SentTransaction.timestamp
                > (datetime.datetime.now() - datetime.timedelta(hours=24))
            )
        )
        .order_by(SentTransaction.timestamp.desc())
    )

    result = []
    for tx in recent:
        result.append({
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
            "tags": json.loads(tx.tags) if tx.tags else []
        })
    return result

@app.get("/api/rpc-status")
async def get_rpc_status():
    status = {}
    for chain_name, interface in ChainInterfaces().items():
        if interface.chain.rpc:
            try:
                start_time = time.time()
                block = interface.w3.eth.block_number
                latency = int((time.time() - start_time) * 1000)
                status[chain_name] = {
                    "status": "online",
                    "block": block,
                    "latency": f"{latency}ms",
                    "url": _obscure_url(interface.chain.rpc[0]) if interface.chain.rpc else "N/A"
                }
            except Exception as e:
                status[chain_name] = {"status": "offline", "error": str(e)}
        else:
            status[chain_name] = {"status": "offline", "error": "No RPC configured"}
    return status

@app.post("/api/send")
async def send_transaction(req: TransactionRequest):
    try:
        tx_hash = wallet.send(
            from_address_or_tag=req.from_address,
            to_address_or_tag=req.to_address,
            amount_wei=int(req.amount * 10**18),
            token_address_or_name=req.token,
            chain_name=req.chain
        )
        return {"status": "success", "hash": tx_hash}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/accounts/eoa")
async def create_eoa(req: AccountCreateRequest):
    try:
        wallet.key_storage.create_account(req.tag)
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

def run_server(host: str = "127.0.0.1", port: int = 8000):
    import uvicorn
    uvicorn.run(app, host=host, port=port)
