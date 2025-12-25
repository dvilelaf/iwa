"""State Router for Web API."""

from fastapi import APIRouter, Depends

from iwa.core.chain import ChainInterfaces
from iwa.web.dependencies import verify_auth

router = APIRouter(prefix="/api", tags=["state"])


@router.get(
    "/state",
    summary="Get App State",
    description="Get the current application state, including configured chains and default settings.",
)
def get_state(auth: bool = Depends(verify_auth)):
    """Get the current application state (configured chains, etc)."""
    # Build native currencies map, tokens map, and collect chain names
    chain_names = []
    native_currencies = {}
    tokens = {}
    for name, interface in ChainInterfaces().items():
        chain_names.append(name)
        native_currencies[name] = interface.chain.native_currency
        # Get token symbols from the interface (dict of symbol -> address)
        tokens[name] = list(interface.tokens.keys())

    return {
        "chains": chain_names,
        "tokens": tokens,
        "native_currencies": native_currencies,
        "default_chain": "gnosis",
    }


def _obscure_url(url: str) -> str:
    """Obscure API keys in URL."""
    if any(param in url for param in ["api_key", "project_id", "key"]):
        return url.split("?")[0] + "?***"
    return url


@router.get(
    "/rpc-status",
    summary="Get RPC Status",
    description="Check the connectivity and sync status of RPC endpoints for all chains.",
)
def get_rpc_status(auth: bool = Depends(verify_auth)):
    """Get status of RPC endpoints."""
    from iwa.core.chain import ChainInterfaces

    status = {}
    for name, interface in ChainInterfaces().items():
        try:
            # Simple check using block number
            block = interface.web3.eth.block_number
            rpcs = [_obscure_url(rpc) for rpc in interface.chain.rpcs]
            status[name] = {"status": "online", "block": block, "rpcs": rpcs}
        except Exception as e:
            status[name] = {
                "status": "offline",
                "error": str(e),
                "rpcs": [_obscure_url(rpc) for rpc in interface.chain.rpcs],
            }
    return status
