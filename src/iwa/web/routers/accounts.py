"""Accounts Router for Web API."""

import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from iwa.web.dependencies import verify_auth, wallet

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/accounts", tags=["accounts"])


# --- Models (Temporary: will move to shared models file later) ---
class AccountCreateRequest(BaseModel):
    """Request model for creating an EOA."""

    tag: str = Field(description="Human-readable tag for the new account")

    @field_validator("tag")
    @classmethod
    def validate_tag(cls, v: str) -> str:
        """Validate tag is not empty and alphanumeric."""
        if not v or not v.strip():
            raise ValueError("Tag cannot be empty")
        if not v.replace("_", "").replace("-", "").isalnum():
            raise ValueError("Tag contains invalid characters")
        return v


class SafeCreateRequest(BaseModel):
    """Request model for creating a Safe."""

    tag: str = Field(description="Human-readable tag for the Safe")
    owners: List[str] = Field(description="List of owner addresses (checksummed or lowercase)")
    threshold: int = Field(description="Required signatures threshold")
    chains: List[str] = Field(default=["gnosis"], description="List of chains to deploy on")

    @field_validator("owners")
    @classmethod
    def validate_owners(cls, v: List[str]) -> List[str]:
        """Validate owners list is not empty and contains valid addresses."""
        if not v:
            raise ValueError("Owners list cannot be empty")
        for owner in v:
            if not owner.startswith("0x") or len(owner) != 42:
                raise ValueError(f"Invalid owner address: {owner}")
        # Check for duplicates
        if len(v) != len(set(v)):
            raise ValueError("Duplicate owners not allowed")
        return v

    @field_validator("threshold")
    @classmethod
    def validate_threshold(cls, v: int, info) -> int:
        """Validate threshold is valid."""
        if v < 1:
            raise ValueError("Threshold must be at least 1")
        # Access owners if available to validate threshold <= len(owners)
        # Note: Pydantic V2 uses ValidationInfo, V1 uses 'values' dict. Assuming V2 based on usage.
        # If 'owners' failed validation, it might not be in info.data
        if info.data and "owners" in info.data:
            owners = info.data["owners"]
            if v > len(owners):
                raise ValueError("Threshold cannot be greater than number of owners")
        return v

    @field_validator("chains")
    @classmethod
    def validate_chains(cls, v: List[str]) -> List[str]:
        """Validate chains list."""
        if not v:
            raise ValueError("Must specify at least one chain")
        for chain in v:
            if not chain.replace("-", "").isalnum():
                raise ValueError(f"Invalid chain name: {chain}")
        return v


@router.get(
    "",
    summary="Get accounts",
    description="Retrieve all stored accounts and their balances for the specified chain.",
)
def get_accounts(chain: str = "gnosis", auth: bool = Depends(verify_auth)):
    """Get all accounts and their balances for a specific chain."""
    if not chain.replace("-", "").isalnum():
        raise HTTPException(status_code=400, detail="Invalid chain name")
    try:
        # We fetch balances for native currency and known tokens
        # For now, just hardcode a list of common tokens or fetch from config
        # Ideally this comes from a TokenService or Config
        token_names = ["native", "OLAS", "WXDAI", "USDC"]

        accounts_data, balances = wallet.get_accounts_balances(chain, token_names)

        # Merge data
        result = []
        for addr, data in accounts_data.items():
            account_balances = balances.get(addr, {})
            result.append(
                {
                    "address": addr,
                    "tag": data.tag,
                    "is_safe": data.is_safe,
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
def create_eoa(req: AccountCreateRequest, auth: bool = Depends(verify_auth)):
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
