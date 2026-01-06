"""Chain interaction helpers.

This package provides chain-related utilities for blockchain interactions:
- ChainInterface: Main interface for interacting with a blockchain
- ChainInterfaces: Singleton manager for all supported chains
- SupportedChain: Base model for chain definitions
- Rate limiting and error handling utilities

All symbols are re-exported here for backward compatibility.
Import from `iwa.core.chain` to use these utilities.
"""

from typing import TypeVar

# Re-export all public symbols for backward compatibility
from iwa.core.chain.errors import (
    TenderlyQuotaExceededError,
    sanitize_rpc_url,
)
from iwa.core.chain.interface import (
    DEFAULT_RPC_TIMEOUT,
    ChainInterface,
)
from iwa.core.chain.manager import ChainInterfaces
from iwa.core.chain.models import (
    Base,
    Ethereum,
    Gnosis,
    SupportedChain,
    SupportedChains,
)
from iwa.core.chain.rate_limiter import (
    RateLimitedEth,
    RateLimitedWeb3,
    RPCRateLimiter,
    get_rate_limiter,
)

# Backward compatibility alias
_sanitize_rpc_url = sanitize_rpc_url

# Expose type variable for retry decorator (used in type hints)
T = TypeVar("T")

__all__ = [
    # Errors
    "TenderlyQuotaExceededError",
    "sanitize_rpc_url",
    "_sanitize_rpc_url",
    # Rate limiting
    "RPCRateLimiter",
    "RateLimitedEth",
    "RateLimitedWeb3",
    "get_rate_limiter",
    # Models
    "SupportedChain",
    "Gnosis",
    "Ethereum",
    "Base",
    "SupportedChains",
    # Interface
    "ChainInterface",
    "DEFAULT_RPC_TIMEOUT",
    # Manager
    "ChainInterfaces",
    # Types
    "T",
]
