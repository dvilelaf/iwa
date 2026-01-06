"""Shared request models for Web API."""

from typing import List

from pydantic import BaseModel, Field, field_validator


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
        """Validate owners list is not empty and contains valid addresses or tags."""
        if not v:
            raise ValueError("Owners list cannot be empty")
        for owner in v:
            # Accept both addresses (0x...) and tags (alphanumeric with _ and -)
            if owner.startswith("0x"):
                if len(owner) != 42:
                    raise ValueError(f"Invalid owner address: {owner}")
            else:
                # Tag format validation
                if not owner.replace("_", "").replace("-", "").replace(" ", "").isalnum():
                    raise ValueError(f"Invalid owner tag: {owner}")
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
