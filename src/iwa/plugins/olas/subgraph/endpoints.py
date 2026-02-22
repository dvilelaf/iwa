"""Subgraph endpoint registry — maps chain + subgraph type to URLs."""

from enum import Enum
from typing import Optional


class SubgraphType(Enum):
    """Types of OLAS subgraphs."""

    SERVICE_REGISTRY = "service_registry"
    STAKING = "staking"
    TOKENOMICS = "tokenomics"
    PROTOCOL_REGISTRY = "protocol_registry"


# Direct proxy endpoints (no API key needed)
PROXY_ENDPOINTS: dict[str, dict[SubgraphType, str]] = {
    "gnosis": {
        SubgraphType.SERVICE_REGISTRY: (
            "https://subgraph.staging.autonolas.tech"
            "/subgraphs/name/service-registry-gnosis-v0_0_1"
        ),
    },
    "mode": {
        SubgraphType.SERVICE_REGISTRY: (
            "https://api.subgraph.autonolas.tech/api/proxy/service-registry-mode"
        ),
        SubgraphType.STAKING: (
            "https://api.subgraph.autonolas.tech/api/proxy/staking-mode"
        ),
        SubgraphType.TOKENOMICS: (
            "https://api.subgraph.autonolas.tech/api/proxy/tokenomics-mode"
        ),
    },
    "ethereum": {
        SubgraphType.PROTOCOL_REGISTRY: (
            "https://api.subgraph.autonolas.tech/api/proxy/autonolas"
        ),
    },
}

# TheGraph subgraph IDs (need API key via gateway.thegraph.com)
THEGRAPH_IDS: dict[str, dict[SubgraphType, str]] = {
    "ethereum": {
        SubgraphType.SERVICE_REGISTRY: "89VhY3d7w6Ran1C86wkchzYNEG3rLBgWvyDUZMEFyjtQ",
        SubgraphType.STAKING: "F3iqL2iw5UTrP1qbb4S694pGEkBwzoxXp1TRikB2K4e",
        SubgraphType.TOKENOMICS: "H7dChkrYGwFGML2w9b7ti54NcRZQH8Aa9Eazd41eK4bw",
    },
    "gnosis": {
        SubgraphType.STAKING: "F3iqL2iw5UTrP1qbb4S694pGEkBwzoxXp1TRikB2K4e",
        SubgraphType.TOKENOMICS: "CWCQsUk2zfD9JMYmsSYKvwhRjmTxFKRJtZK62w6x3bPX",
    },
    "base": {
        SubgraphType.SERVICE_REGISTRY: "Baqj7bPWWQKw8HXwfqbMZnFhkSamuUYFa3JgCRYF8Tcr",
        SubgraphType.STAKING: "9etc5Ht8eQGghXrkbWJk2yMzNypCFTL46m1iLXqE2rnq",
        SubgraphType.TOKENOMICS: "4PfoaqBSC8zJKGSVxKmyQPHLvK4VrHu9ZiLeaGjhN59G",
    },
    "optimism": {
        SubgraphType.SERVICE_REGISTRY: "BksA3aj8vX68TVs91ieDoGzFGASuLC7BaYo2HsGCea7p",
        SubgraphType.STAKING: "2fe1izA4aVvBHVwbPzP1BqxLkoR9ebygWM9iHXwLCnPE",
        SubgraphType.TOKENOMICS: "6PX6KaJdKtmeB3FmpA9s6PRRdB6yi7LMQipfSiJnNBRH",
    },
    "polygon": {
        SubgraphType.SERVICE_REGISTRY: "HHRBjVWFT2bV7eNSRqbCNDtUVnLPt911hcp8mSe4z6KG",
        SubgraphType.STAKING: "DULB7Nm5TwjQfcPnfMRzwtguvPBhumcjRbXV5fpBuNVV",
        SubgraphType.TOKENOMICS: "B1BF29s7xVhueYcr6ZHhQiiSYr3h3uqpZnnqeP6Wefc3",
    },
    "arbitrum": {
        SubgraphType.SERVICE_REGISTRY: "GpQfE1C5DzXz1KCFvvj6jZkuhpMouwtbf9yYSv2y2V4p",
        SubgraphType.TOKENOMICS: "EKdR7Xqiz3iEtZuAQPChPku14aSxnb85pVpx9Nb13J2",
    },
    "celo": {
        SubgraphType.SERVICE_REGISTRY: "BxkMNoiEHdbJDtrmMG1bqVvUfwVUWnf5bn47WnCdB1A4",
        SubgraphType.TOKENOMICS: "pVCUc7dQYpRFPBjX6trqqvJDedZKPRXn1C1yaihwLRQ",
    },
}

THEGRAPH_GATEWAY = "https://gateway.thegraph.com/api"

# All chains that have at least one subgraph endpoint
ALL_CHAINS = sorted(
    set(list(PROXY_ENDPOINTS.keys()) + list(THEGRAPH_IDS.keys()))
)


def get_endpoint(
    chain: str,
    subgraph_type: SubgraphType,
    api_key: Optional[str] = None,
) -> Optional[str]:
    """Resolve the endpoint URL for a chain + subgraph type.

    Prefers proxy (free) endpoints. Falls back to TheGraph with API key.

    Args:
        chain: Chain name (e.g. "gnosis", "ethereum").
        subgraph_type: Type of subgraph.
        api_key: Optional TheGraph API key.

    Returns:
        Endpoint URL, or None if not available.

    """
    chain_lower = chain.lower()

    # Try proxy first (free, no key needed)
    proxy = PROXY_ENDPOINTS.get(chain_lower, {}).get(subgraph_type)
    if proxy:
        return proxy

    # Try TheGraph (needs API key)
    if api_key:
        subgraph_id = THEGRAPH_IDS.get(chain_lower, {}).get(subgraph_type)
        if subgraph_id:
            return f"{THEGRAPH_GATEWAY}/{api_key}/subgraphs/id/{subgraph_id}"

    return None


def get_available_chains(
    subgraph_type: SubgraphType,
    api_key: Optional[str] = None,
) -> list[str]:
    """Return chains that have an endpoint for the given subgraph type.

    Args:
        subgraph_type: Type of subgraph.
        api_key: Optional TheGraph API key.

    Returns:
        List of chain names.

    """
    return [
        chain
        for chain in ALL_CHAINS
        if get_endpoint(chain, subgraph_type, api_key) is not None
    ]
