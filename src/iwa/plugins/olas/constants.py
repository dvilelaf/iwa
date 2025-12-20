"""OLAS protocol constants."""

from enum import IntEnum
from typing import Dict

from iwa.core.models import EthereumAddress


class AgentType(IntEnum):
    """Supported OLAS agent types."""

    TRADER = 25


TRADER_CONFIG_HASH = "108e90795119d6015274ef03af1a669c6d13ab6acc9e2b2978be01ee9ea2ec93"
DEFAULT_DEPLOY_PAYLOAD = "0x0000000000000000000000000000000000000000{fallback_handler}000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"


# OLAS Protocol Contracts categorized by chain
OLAS_CONTRACTS: Dict[str, Dict[str, EthereumAddress]] = {
    "gnosis": {
        "OLAS_SERVICE_REGISTRY": EthereumAddress("0x9338b5153AE39BB89f50468E608eD9d764B755fD"),
        "OLAS_SERVICE_REGISTRY_TOKEN_UTILITY": EthereumAddress("0xa45E64d13A30a51b91ae0eb182e88a40e9b18eD8"),
        "OLAS_SERVICE_MANAGER": EthereumAddress("0x068a4f0946cF8c7f9C1B58a3b5243Ac8843bf473"),
        "OLAS_MECH": EthereumAddress("0x77af31De935740567Cf4fF1986D04B2c964A786a"),
        "OLAS_MECH_MARKETPLACE": EthereumAddress("0x4554fE75c1f5576c1d7F765B2A036c199Adae329"),
    },
    "ethereum": {
        "OLAS_SERVICE_REGISTRY": EthereumAddress("0x48b6F34dDAf31f94086BFB45e69e0618DDe3677b"),
        "OLAS_SERVICE_MANAGER": EthereumAddress("0x9C14948a39a9c1A58e3f94639908F0076FA715C6"),
    },
    "base": {
        "OLAS_SERVICE_REGISTRY": EthereumAddress("0x3841C312061daB948332A78F042Ec61Ad09fc3D8"),
        "OLAS_SERVICE_MANAGER": EthereumAddress("0xF36183B106692DeD8b6e3B2B7347C9665f8a09B1"),
    },
}

# TRADER-compatible staking contracts categorized by chain
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
