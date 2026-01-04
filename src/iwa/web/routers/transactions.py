"""Transactions Router for Web API."""

import datetime
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from slowapi import Limiter
from slowapi.util import get_remote_address
from web3 import Web3

from iwa.core.db import SentTransaction
from iwa.web.dependencies import verify_auth, wallet

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["transactions"])

# Rate limiter for this router
limiter = Limiter(key_func=get_remote_address)


class TransactionRequest(BaseModel):
    """Request model for sending a transaction."""

    from_address: str = Field(description="Sender address or tag")
    to_address: str = Field(description="Recipient address or tag")
    amount_eth: float = Field(description="Amount to send in ETH/Tokens")
    token: str = Field(default="native", description="Token symbol (e.g., OLAS) or 'native'")
    chain: str = Field(default="gnosis", description="Target blockchain")

    @field_validator("from_address", "to_address")
    @classmethod
    def validate_address(cls, v: str) -> str:
        """Validate address format."""
        if not v:
            raise ValueError("Address cannot be empty")
        if v.startswith("0x"):
            if len(v) != 42:
                raise ValueError("Invalid address format")
        else:
            # Assume it's a tag - allow alphanumeric, underscores, dashes, and spaces
            if not v.replace("_", "").replace("-", "").replace(" ", "").isalnum():
                raise ValueError("Invalid tag format")
        return v

    @field_validator("chain")
    @classmethod
    def validate_chain(cls, v: str) -> str:
        """Validate chain name."""
        if not v.replace("-", "").isalnum():
            raise ValueError("Invalid chain name")
        return v

    @field_validator("token")
    @classmethod
    def validate_token(cls, v: str) -> str:
        """Validate token symbol or address."""
        # Token can be "native", a symbol "OLAS", or address "0x..."
        if not v:
            raise ValueError("Token cannot be empty")
        if v.startswith("0x") and len(v) != 42:
            raise ValueError("Invalid token address")
        return v

    @field_validator("amount_eth")
    @classmethod
    def validate_amount(cls, v: float) -> float:
        """Validate amount is positive."""
        if v < 0:
            raise ValueError("Amount must be positive")
        if v > 1e18:  # Sanity check
            raise ValueError("Amount too large")
        return v


@router.get(
    "/transactions",
    summary="Get Transactions",
    description="Retrieve recent sent transactions (last 24h) for a chain.",
)
def get_transactions(chain: str = "gnosis", auth: bool = Depends(verify_auth)):
    """Get recent transactions for a specific chain."""
    if not chain.replace("-", "").isalnum():
        raise HTTPException(status_code=400, detail="Invalid chain name")
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
        # Get token decimals for proper display
        token_decimals = 18  # Default for native
        if tx.token and tx.token.lower() not in ["native", "native currency"]:
            try:
                from iwa.core.chain import ChainInterfaces
                from iwa.core.contracts.erc20 import ERC20Contract

                chain_interface = ChainInterfaces().get(chain)
                if chain_interface:
                    token_address = chain_interface.chain.get_token_address(tx.token)
                    if token_address:
                        erc20 = ERC20Contract(token_address, chain)
                        token_decimals = erc20.decimals
            except Exception:
                pass  # Default to 18 if we can't get decimals

        amount_display = float(tx.amount_wei or 0) / (10**token_decimals)

        result.append(
            {
                "timestamp": tx.timestamp.isoformat(),
                "chain": tx.chain.capitalize(),
                "from": tx.from_tag or tx.from_address,
                "to": tx.to_tag or tx.to_address,
                "token": tx.token,
                "amount": f"{amount_display:.2f}",
                "value_eur": f"€{(tx.value_eur or 0.0):.2f}",
                "status": "Confirmed",
                "hash": tx.tx_hash,
                "gas_cost": str(tx.gas_cost or "0"),
                "gas_value_eur": f"€{tx.gas_value_eur:.4f}" if tx.gas_value_eur else "?",
                "tags": json.loads(tx.tags) if tx.tags else [],
            }
        )
    return result


@router.post(
    "/send",
    summary="Send Transaction",
    description="Send native currency or ERC20 tokens from a managed account.",
)
@limiter.limit("10/minute")
def send_transaction(request: Request, req: TransactionRequest, auth: bool = Depends(verify_auth)):
    """Send a transaction from an account."""
    try:
        tx_hash = wallet.send(
            from_address_or_tag=req.from_address,
            to_address_or_tag=req.to_address,
            amount_wei=Web3.to_wei(req.amount_eth, "ether"),
            token_address_or_name=req.token,
            chain_name=req.chain,
        )
        return {"status": "success", "hash": tx_hash}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
