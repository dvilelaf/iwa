"""Accounts Router for Web API."""

import logging
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from iwa.web.dependencies import verify_auth, wallet
from iwa.web.models import AccountCreateRequest, SafeCreateRequest

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/accounts", tags=["accounts"])

# Rate limiter for this router
limiter = Limiter(key_func=get_remote_address)


@router.get(
    "",
    summary="Get accounts",
    description="Retrieve all stored accounts and their balances for the specified chain.",
)
def get_accounts(
    chain: str = "gnosis",
    tokens: str = None,
    auth: bool = Depends(verify_auth),
):
    """Get all accounts and their balances for a specific chain."""
    if not chain.replace("-", "").isalnum():
        raise HTTPException(status_code=400, detail="Invalid chain name")
    try:
        # Parse tokens from query parameter or use defaults
        if tokens:
            token_names = [t.strip() for t in tokens.split(",") if t.strip()]
        else:
            token_names = ["native", "OLAS", "WXDAI", "USDC"]

        accounts_data, balances = wallet.get_accounts_balances(chain, token_names)

        # Merge data
        result = []
        for addr, data in accounts_data.items():
            account_balances = balances.get(addr, {})
            # Determine account type: if it has 'signers' attribute, it's a Safe
            account_type = "Safe" if hasattr(data, "signers") else "EOA"
            result.append(
                {
                    "address": addr,
                    "tag": data.tag,
                    "type": account_type,
                    "balances": account_balances,
                }
            )

        return result
    except Exception as e:
        logger.error(f"Error fetching accounts: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from None


@router.post(
    "/eoa",
    summary="Create EOA",
    description="Create a new Externally Owned Account (EOA) with a unique tag.",
)
@limiter.limit("5/minute")
def create_eoa(request: Request, req: AccountCreateRequest, auth: bool = Depends(verify_auth)):
    """Create a new EOA account with the given tag."""
    try:
        wallet.key_storage.create_account(req.tag)
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from None


@router.post(
    "/safe",
    summary="Create Safe",
    description="Deploy a new Gnosis Safe multisig wallet on selected chains.",
)
@limiter.limit("3/minute")
def create_safe(request: Request, req: SafeCreateRequest, auth: bool = Depends(verify_auth)):
    """Create a new Safe multisig account."""
    try:
        # We use a timestamp-based salt to avoid collisions
        salt_nonce = int(time.time() * 1000)

        # Resolve owner tags to addresses
        resolved_owners = []
        for owner in req.owners:
            if owner.startswith("0x"):
                resolved_owners.append(owner)
            else:
                # It's a tag, resolve to address
                account = wallet.account_service.resolve_account(owner)
                if not account:
                    raise ValueError(f"Owner account not found: {owner}")
                resolved_owners.append(account.address)

        # Deploy on all requested chains
        for chain_name in req.chains:
            wallet.safe_service.create_safe(
                "master",  # WebUI uses master as deployer by default
                resolved_owners,
                req.threshold,
                chain_name,
                req.tag,
                salt_nonce,
            )
        return {"status": "success"}
    except Exception as e:
        logger.error(f"Error creating Safe: {e}")
        raise HTTPException(status_code=400, detail=str(e)) from None
