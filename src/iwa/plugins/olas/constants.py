"""OLAS protocol constants."""

from enum import IntEnum
from typing import Dict

from iwa.core.models import EthereumAddress


class AgentType(IntEnum):
    """Supported OLAS agent types."""

    TRADER = 25


# Mech Marketplace Payment Types (bytes32 hex strings, without 0x prefix)
# From mech-client/marketplace_interact.py
PAYMENT_TYPE_NATIVE = "ba699a34be8fe0e7725e93dcbce1701b0211a8ca61330aaeb8a05bf2ec7abed1"
PAYMENT_TYPE_TOKEN = "3679d66ef546e66ce9057c4a052f317b135bc8e8c509638f7966edfd4fcf45e9"
PAYMENT_TYPE_NATIVE_NVM = "803dd08fe79d91027fc9024e254a0942372b92f3ccabc1bd19f4a5c2b251c316"
PAYMENT_TYPE_TOKEN_NVM_USDC = "0d6fd99afa9c4c580fab5e341922c2a5c4b61d880da60506193d7bf88944dd14"

# Mech Factory to Mech Type mappings by chain
# From mech-client/mech_marketplace_subgraph.py
MECH_FACTORY_TO_TYPE: Dict[str, Dict[str, str]] = {
    "gnosis": {
        "0x8b299c20F87e3fcBfF0e1B86dC0acC06AB6993EF": "Fixed Price Native",
        "0x31ffDC795FDF36696B8eDF7583A3D115995a45FA": "Fixed Price Token",
        "0x65fd74C29463afe08c879a3020323DD7DF02DA57": "NvmSubscription Native",
    },
    "base": {
        "0x2E008211f34b25A7d7c102403c6C2C3B665a1abe": "Fixed Price Native",
        "0x97371B1C0cDA1D04dFc43DFb50a04645b7Bc9BEe": "Fixed Price Token",
        "0x847bBE8b474e0820215f818858e23F5f5591855A": "NvmSubscription Native",
        "0x7beD01f8482fF686F025628e7780ca6C1f0559fc": "NvmSubscription Token USDC",
    },
}

TRADER_CONFIG_HASH = "108e90795119d6015274ef03af1a669c6d13ab6acc9e2b2978be01ee9ea2ec93"
DEFAULT_DEPLOY_PAYLOAD = "0x0000000000000000000000000000000000000000{fallback_handler}000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"

# OLAS Token address on Gnosis chain
OLAS_TOKEN_ADDRESS_GNOSIS = EthereumAddress("0xcE11e14225575945b8E6Dc0D4F2dD4C570f79d9f")


# OLAS Protocol Contracts categorized by chain
# See mech_reference.py for comprehensive documentation of the mech ecosystem
OLAS_CONTRACTS: Dict[str, Dict[str, EthereumAddress]] = {
    "gnosis": {
        "OLAS_SERVICE_REGISTRY": EthereumAddress("0x9338b5153AE39BB89f50468E608eD9d764B755fD"),
        "OLAS_SERVICE_REGISTRY_TOKEN_UTILITY": EthereumAddress(
            "0xa45E64d13A30a51b91ae0eb182e88a40e9b18eD8"
        ),
        "OLAS_SERVICE_MANAGER": EthereumAddress("0x068a4f0946cF8c7f9C1B58a3b5243Ac8843bf473"),
        # Legacy mech - used by TRADER staking contracts for liveness
        "OLAS_MECH": EthereumAddress("0x77af31De935740567Cf4fF1986D04B2c964A786a"),
        # NEW Marketplace (v2) - no staking support yet
        "OLAS_MECH_MARKETPLACE": EthereumAddress("0x735FAAb1c4Ec41128c367AFb5c3baC73509f70bB"),
        # OLD Marketplace (v1) - used by Pearl Beta Mech Marketplace staking
        "OLAS_MECH_MARKETPLACE_OLD": EthereumAddress("0x4554fE75c1f5576c1d7F765B2A036c199Adae329"),
    },
    "ethereum": {
        "OLAS_SERVICE_REGISTRY": EthereumAddress("0x48b6F34dDAf31f94086BFB45e69e0618DDe3677b"),
        "OLAS_SERVICE_MANAGER": EthereumAddress("0x9C14948a39a9c1A58e3f94639908F0076FA715C6"),
    },
    "base": {
        "OLAS_SERVICE_REGISTRY": EthereumAddress("0x3841C312061daB948332A78F042Ec61Ad09fc3D8"),
        "OLAS_SERVICE_MANAGER": EthereumAddress("0xF36183B106692DeD8b6e3B2B7347C9665f8a09B1"),
        "OLAS_MECH_MARKETPLACE": EthereumAddress("0x4554fE75c1f5576c1d7F765B2A036c199Adae329"),
    },
}

# TRADER-compatible staking contracts categorized by chain
# See https://govern.olas.network/contracts
# NOTE: All TRADER staking contracts use the LEGACY MECH for activity tracking.
# The activity checker calls agentMech.getRequestsCount(multisig), where agentMech
# is hardcoded to the legacy mech (0x77af31De935740567Cf4fF1986D04B2c964A786a).
#
# This means:
#   - Legacy mech requests (use_marketplace=False) -> COUNT for liveness rewards
#   - Marketplace mech requests (use_marketplace=True) -> DO NOT COUNT
#
# For staking rewards, services MUST use legacy mech requests.
OLAS_TRADER_STAKING_CONTRACTS: Dict[str, Dict[str, EthereumAddress]] = {
    "gnosis": {
        "Hobbyist 1 (100 OLAS)": EthereumAddress("0x389B46C259631Acd6a69Bde8B6cEe218230bAE8C"),
        "Hobbyist 2 (500 OLAS)": EthereumAddress("0x238EB6993b90A978ec6AAD7530D6429c949C08DA"),
        "Expert (1k OLAS)": EthereumAddress("0x5344B7DD311e5d3DdDd46A4f71481Bd7b05AAA3e"),
        "Expert 2 (1k OLAS)": EthereumAddress("0xb964e44c126410df341ae04B13aB10A985fE3513"),
        "Expert 3 (2k OLAS)": EthereumAddress("0x80faD33Cadb5F53f9D29F02Db97D682E8B101618"),
        "Expert 4 (10k OLAS)": EthereumAddress("0xaD9d891134443B443D7F30013c7e14Fe27F2E029"),
        "Expert 5 (10k OLAS)": EthereumAddress("0xE56dF1E563De1B10715cB313D514af350D207212"),
        "Expert 6 (1k OLAS)": EthereumAddress("0x2546214aEE7eEa4bEE7689C81231017CA231Dc93"),
        "Expert 7 (10k OLAS)": EthereumAddress("0xD7A3C8b975f71030135f1a66E9e23164d54fF455"),
        "Expert 8 (2k OLAS)": EthereumAddress("0x356C108D49C5eebd21c84c04E9162de41933030c"),
        "Expert 9 (10k OLAS)": EthereumAddress("0x17dBAe44BC5618Cc254055B386A29576b4F87015"),
        "Expert 10 (10k OLAS)": EthereumAddress("0xB0ef657b8302bd2c74B6E6D9B2b4b39145b19c6f"),
        "Expert 11 (10k OLAS)": EthereumAddress("0x3112c1613eAC3dBAE3D4E38CeF023eb9E2C91CF7"),
        "Expert 12 (10k OLAS)": EthereumAddress("0xF4a75F476801B3fBB2e7093aCDcc3576593Cc1fc"),
        "Expert 15 (10k OLAS)": EthereumAddress("0x88eB38FF79fBa8C19943C0e5Acfa67D5876AdCC1"),
        "Expert 16 (10k OLAS)": EthereumAddress("0x6c65430515c70a3f5E62107CC301685B7D46f991"),
        "Expert 17 (10k OLAS)": EthereumAddress("0x1430107A785C3A36a0C1FC0ee09B9631e2E72aFf"),
        "Expert 18 (10k OLAS)": EthereumAddress("0x041e679d04Fc0D4f75Eb937Dea729Df09a58e454"),
    },
    "ethereum": {},
    "base": {},
}
