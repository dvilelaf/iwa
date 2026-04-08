"""OLAS protocol constants."""

from dataclasses import dataclass
from enum import IntEnum, StrEnum
from typing import Dict, List, Optional, Sequence

from iwa.core.models import EthereumAddress


class AgentType(IntEnum):
    """Supported OLAS agent types."""

    TRADER = 25
    PEARL = 14
    MEME = 43


class MarketplaceType(StrEnum):
    """Type of mech marketplace used by the staking contract's activity checker."""

    LEGACY = "legacy"  # No marketplace, legacy mech agentMech.getRequestsCount()
    MM_V2 = "mm_v2"  # New marketplace 0x735FAAb1...
    PEARL = "pearl"  # Pearl-specific activity checker
    PEARL_MM = "pearl_mm"  # Pearl with marketplace
    MM_V1_DEFUNCT = "mm_v1_defunct"  # Old marketplace V1 (mech 975 retired 2026-03-17)
    SUPPLY = "supply"  # Mech supply side (deliveries, not requests)
    DEMAND = "demand"  # Marketplace demand side
    UNKNOWN = "unknown"  # Unclassified activity checker


class ContractStatus(StrEnum):
    """Operational status of a staking contract."""

    ACTIVE = "active"  # Accepting stakes, rewards flowing
    DEPLETED = "depleted"  # No rewards left but contract still running
    FULL = "full"  # All slots occupied
    DEFUNCT = "defunct"  # Retired/broken, do not use


@dataclass(frozen=True)
class StakingContractInfo:
    """Metadata for an OLAS staking contract.

    required_requests: min actions per epoch to earn rewards.
      For demand/trader contracts: mech requests sent (0.01 xDAI each on Gnosis).
      For supply contracts: mech deliveries (responses processed).
      For pearl contracts: multisig nonce increments (any tx counts).
    epoch_hours: epoch duration in hours (all are 24h currently).
    """

    name: str
    address: EthereumAddress
    chain: str
    agent_id: Optional[int]  # None for supply/demand contracts
    marketplace: MarketplaceType
    status: ContractStatus
    bond_olas: int  # Total bond required in OLAS
    required_requests: int = 0  # Min actions per epoch (from livenessRatio)
    epoch_hours: int = 24  # Epoch duration


# ---------------------------------------------------------------------------
# Master registry of ALL known OLAS staking contracts
# Source: https://govern.olas.network/contracts
# Source: https://github.com/valory-xyz/olas-operate-middleware/blob/main/operate/ledger/profiles.py
# Verified on-chain 2026-03-28
# ---------------------------------------------------------------------------
STAKING_CONTRACTS: List[StakingContractInfo] = [
    # =====================================================================
    # GNOSIS — Agent ID 25 (Trader) — Legacy mech
    # =====================================================================
    StakingContractInfo(
        name="Hobbyist 1 Legacy (100 OLAS)",
        address=EthereumAddress("0x389B46C259631Acd6a69Bde8B6cEe218230bAE8C"),
        chain="gnosis",
        agent_id=25,
        marketplace=MarketplaceType.LEGACY,
        status=ContractStatus.ACTIVE,
        bond_olas=100,
        required_requests=40,
    ),
    StakingContractInfo(
        name="Hobbyist 2 Legacy (500 OLAS)",
        address=EthereumAddress("0x238EB6993b90A978ec6AAD7530D6429c949C08DA"),
        chain="gnosis",
        agent_id=25,
        marketplace=MarketplaceType.LEGACY,
        status=ContractStatus.ACTIVE,
        bond_olas=500,
        required_requests=20,
    ),
    StakingContractInfo(
        name="Expert Legacy (1k OLAS)",
        address=EthereumAddress("0x5344B7DD311e5d3DdDd46A4f71481Bd7b05AAA3e"),
        chain="gnosis",
        agent_id=25,
        marketplace=MarketplaceType.LEGACY,
        status=ContractStatus.ACTIVE,
        bond_olas=1000,
        required_requests=40,
    ),
    StakingContractInfo(
        name="Expert 2 Legacy (1k OLAS)",
        address=EthereumAddress("0xb964e44c126410df341ae04B13aB10A985fE3513"),
        chain="gnosis",
        agent_id=25,
        marketplace=MarketplaceType.LEGACY,
        status=ContractStatus.ACTIVE,
        bond_olas=1000,
        required_requests=40,
    ),
    StakingContractInfo(
        name="Expert 3 Legacy (2k OLAS)",
        address=EthereumAddress("0x80faD33Cadb5F53f9D29F02Db97D682E8B101618"),
        chain="gnosis",
        agent_id=25,
        marketplace=MarketplaceType.LEGACY,
        status=ContractStatus.ACTIVE,
        bond_olas=2000,
        required_requests=40,
    ),
    StakingContractInfo(
        name="Expert 4 Legacy (10k OLAS)",
        address=EthereumAddress("0xaD9d891134443B443D7F30013c7e14Fe27F2E029"),
        chain="gnosis",
        agent_id=25,
        marketplace=MarketplaceType.LEGACY,
        status=ContractStatus.ACTIVE,
        bond_olas=10000,
        required_requests=60,
    ),
    StakingContractInfo(
        name="Expert 5 Legacy (10k OLAS)",
        address=EthereumAddress("0xE56dF1E563De1B10715cB313D514af350D207212"),
        chain="gnosis",
        agent_id=25,
        marketplace=MarketplaceType.LEGACY,
        status=ContractStatus.ACTIVE,
        bond_olas=10000,
        required_requests=60,
    ),
    StakingContractInfo(
        name="Expert 6 Legacy (1k OLAS)",
        address=EthereumAddress("0x2546214aEE7eEa4bEE7689C81231017CA231Dc93"),
        chain="gnosis",
        agent_id=25,
        marketplace=MarketplaceType.LEGACY,
        status=ContractStatus.ACTIVE,
        bond_olas=1000,
        required_requests=40,
    ),
    StakingContractInfo(
        name="Expert 7 Legacy (10k OLAS)",
        address=EthereumAddress("0xD7A3C8b975f71030135f1a66E9e23164d54fF455"),
        chain="gnosis",
        agent_id=25,
        marketplace=MarketplaceType.LEGACY,
        status=ContractStatus.ACTIVE,
        bond_olas=10000,
        required_requests=60,
    ),
    StakingContractInfo(
        name="Expert 8 Legacy (2k OLAS)",
        address=EthereumAddress("0x356C108D49C5eebd21c84c04E9162de41933030c"),
        chain="gnosis",
        agent_id=25,
        marketplace=MarketplaceType.LEGACY,
        status=ContractStatus.ACTIVE,
        bond_olas=2000,
        required_requests=40,
    ),
    StakingContractInfo(
        name="Expert 9 Legacy (10k OLAS)",
        address=EthereumAddress("0x17dBAe44BC5618Cc254055B386A29576b4F87015"),
        chain="gnosis",
        agent_id=25,
        marketplace=MarketplaceType.LEGACY,
        status=ContractStatus.FULL,
        bond_olas=10000,
        required_requests=60,
    ),
    StakingContractInfo(
        name="Expert 10 Legacy (10k OLAS)",
        address=EthereumAddress("0xB0ef657b8302bd2c74B6E6D9B2b4b39145b19c6f"),
        chain="gnosis",
        agent_id=25,
        marketplace=MarketplaceType.LEGACY,
        status=ContractStatus.FULL,
        bond_olas=10000,
        required_requests=60,
    ),
    StakingContractInfo(
        name="Expert 11 Legacy (10k OLAS)",
        address=EthereumAddress("0x3112c1613eAC3dBAE3D4E38CeF023eb9E2C91CF7"),
        chain="gnosis",
        agent_id=25,
        marketplace=MarketplaceType.LEGACY,
        status=ContractStatus.FULL,
        bond_olas=10000,
        required_requests=60,
    ),
    StakingContractInfo(
        name="Expert 12 Legacy (10k OLAS)",
        address=EthereumAddress("0xF4a75F476801B3fBB2e7093aCDcc3576593Cc1fc"),
        chain="gnosis",
        agent_id=25,
        marketplace=MarketplaceType.LEGACY,
        status=ContractStatus.ACTIVE,
        bond_olas=10000,
        required_requests=60,
    ),
    # =====================================================================
    # GNOSIS — Agent ID 25 (Trader) — Marketplace V2
    # =====================================================================
    StakingContractInfo(
        name="Expert 3 MM v2 (1k OLAS)",
        address=EthereumAddress("0x75eeca6207be98cac3fde8a20ecd7b01e50b3472"),
        chain="gnosis",
        agent_id=25,
        marketplace=MarketplaceType.MM_V2,
        status=ContractStatus.ACTIVE,
        bond_olas=1000,
        required_requests=40,
    ),
    StakingContractInfo(
        name="Expert 4 MM v2 (2k OLAS)",
        address=EthereumAddress("0x9c7f6103e3a72e4d1805b9c683ea5b370ec1a99f"),
        chain="gnosis",
        agent_id=25,
        marketplace=MarketplaceType.MM_V2,
        status=ContractStatus.ACTIVE,
        bond_olas=2000,
        required_requests=40,
    ),
    StakingContractInfo(
        name="Expert 5 MM v2 (10k OLAS)",
        address=EthereumAddress("0xcdC603e0Ee55Aae92519f9770f214b2Be4967f7d"),
        chain="gnosis",
        agent_id=25,
        marketplace=MarketplaceType.MM_V2,
        status=ContractStatus.ACTIVE,
        bond_olas=10000,
        required_requests=60,
    ),
    StakingContractInfo(
        name="Expert 6 MM v2 (10k OLAS)",
        address=EthereumAddress("0x22d6cd3d587d8391c3aae83a783f26c67ab54a85"),
        chain="gnosis",
        agent_id=25,
        marketplace=MarketplaceType.MM_V2,
        status=ContractStatus.ACTIVE,
        bond_olas=10000,
        required_requests=60,
    ),
    StakingContractInfo(
        name="Expert 7 MM v2 (10k OLAS)",
        address=EthereumAddress("0xaaecdf4d0cbd6ca0622892ac6044472f3912a5f3"),
        chain="gnosis",
        agent_id=25,
        marketplace=MarketplaceType.MM_V2,
        status=ContractStatus.ACTIVE,
        bond_olas=10000,
        required_requests=60,
    ),
    StakingContractInfo(
        name="Expert 8 MM v2 (10k OLAS)",
        address=EthereumAddress("0x168aed532a0cd8868c22fc77937af78b363652b1"),
        chain="gnosis",
        agent_id=25,
        marketplace=MarketplaceType.MM_V2,
        status=ContractStatus.ACTIVE,
        bond_olas=10000,
        required_requests=60,
    ),
    StakingContractInfo(
        name="Expert 9 MM v2 (10k OLAS)",
        address=EthereumAddress("0xdda9cd214f12e7c2d58e871404a0a3b1177065c8"),
        chain="gnosis",
        agent_id=25,
        marketplace=MarketplaceType.MM_V2,
        status=ContractStatus.ACTIVE,
        bond_olas=10000,
        required_requests=60,
    ),
    StakingContractInfo(
        name="Expert 10 MM v2 (10k OLAS)",
        address=EthereumAddress("0x53a38655b4e659ef4c7f88a26fbf5c67932c7156"),
        chain="gnosis",
        agent_id=25,
        marketplace=MarketplaceType.MM_V2,
        status=ContractStatus.ACTIVE,
        bond_olas=10000,
        required_requests=60,
    ),
    StakingContractInfo(
        name="Expert 11 MM v2 (10k OLAS)",
        address=EthereumAddress("0x1eaDe40561C61fa7AcC5D816b1FC55a8d9B58519"),
        chain="gnosis",
        agent_id=25,
        marketplace=MarketplaceType.MM_V2,
        status=ContractStatus.ACTIVE,
        bond_olas=10000,
        required_requests=16,
    ),
    StakingContractInfo(
        name="Expert 12 MM v2 (10k OLAS)",
        address=EthereumAddress("0x99Fe6B5C9980Fc3A44b1Dc32A76Db6aDfcf4c75e"),
        chain="gnosis",
        agent_id=25,
        marketplace=MarketplaceType.MM_V2,
        status=ContractStatus.ACTIVE,
        bond_olas=10000,
        required_requests=16,
    ),
    StakingContractInfo(
        name="Expert 13 MM v2 (10k OLAS)",
        address=EthereumAddress("0x1F81cF353051dAA8919d1777c58b667025794dDc"),
        chain="gnosis",
        agent_id=25,
        marketplace=MarketplaceType.MM_V2,
        status=ContractStatus.ACTIVE,
        bond_olas=10000,
        required_requests=16,
    ),
    # =====================================================================
    # GNOSIS — Agent ID 25 (Trader) — MM v2 (new, large reward pools)
    # =====================================================================
    StakingContractInfo(
        name="QS Expert 1 MM v2 (10k OLAS)",
        address=EthereumAddress("0xdB9E2713c3dA3C403F2eA6E570eB978b00304e9E"),
        chain="gnosis",
        agent_id=25,
        marketplace=MarketplaceType.MM_V2,
        status=ContractStatus.ACTIVE,
        bond_olas=10000,
        required_requests=60,
    ),
    StakingContractInfo(
        name="QS Expert 2 MM v2 (10k OLAS)",
        address=EthereumAddress("0x1E90522b45c771DCF5f79645B9e96551d2ECaF62"),
        chain="gnosis",
        agent_id=25,
        marketplace=MarketplaceType.MM_V2,
        status=ContractStatus.ACTIVE,
        bond_olas=10000,
        required_requests=60,
    ),
    # =====================================================================
    # GNOSIS — Agent ID 25 — Pearl variants
    # =====================================================================
    StakingContractInfo(
        name="Pearl Beta (40 OLAS)",
        address=EthereumAddress("0xeF44Fb0842DDeF59D37f85D61A1eF492bbA6135d"),
        chain="gnosis",
        agent_id=25,
        marketplace=MarketplaceType.PEARL,
        status=ContractStatus.ACTIVE,
        bond_olas=40,
        required_requests=5,
    ),
    StakingContractInfo(
        name="Pearl Beta 2 (100 OLAS)",
        address=EthereumAddress("0x1c2F82413666d2a3fD8bC337b0268e62dDF67434"),
        chain="gnosis",
        agent_id=25,
        marketplace=MarketplaceType.PEARL,
        status=ContractStatus.ACTIVE,
        bond_olas=100,
        required_requests=5,
    ),
    StakingContractInfo(
        name="Pearl Beta 3 (100 OLAS)",
        address=EthereumAddress("0xBd59Ff0522aA773cB6074ce83cD1e4a05A457bc1"),
        chain="gnosis",
        agent_id=25,
        marketplace=MarketplaceType.PEARL,
        status=ContractStatus.ACTIVE,
        bond_olas=100,
        required_requests=5,
    ),
    StakingContractInfo(
        name="Pearl Beta 4 (100 OLAS)",
        address=EthereumAddress("0x3052451e1eAee78e62E169AfdF6288F8791F2918"),
        chain="gnosis",
        agent_id=25,
        marketplace=MarketplaceType.PEARL,
        status=ContractStatus.ACTIVE,
        bond_olas=100,
        required_requests=5,
    ),
    StakingContractInfo(
        name="Pearl Beta 5 (10 OLAS)",
        address=EthereumAddress("0x4Abe376Fda28c2F43b84884E5f822eA775DeA9F4"),
        chain="gnosis",
        agent_id=25,
        marketplace=MarketplaceType.PEARL,
        status=ContractStatus.ACTIVE,
        bond_olas=10,
        required_requests=5,
    ),
    StakingContractInfo(
        name="Pearl Beta 6 (5k OLAS)",
        address=EthereumAddress("0x6C6D01e8eA8f806eF0c22F0ef7ed81D868C1aB39"),
        chain="gnosis",
        agent_id=25,
        marketplace=MarketplaceType.PEARL,
        status=ContractStatus.FULL,
        bond_olas=5000,
        required_requests=7,
    ),
    StakingContractInfo(
        name="Pearl Beta MM (40 OLAS)",
        address=EthereumAddress("0xDaF34eC46298b53a3d24CBCb431E84eBd23927dA"),
        chain="gnosis",
        agent_id=25,
        marketplace=MarketplaceType.PEARL_MM,
        status=ContractStatus.ACTIVE,
        bond_olas=40,
        required_requests=5,
    ),
    StakingContractInfo(
        name="Pearl MM 1 (5k OLAS)",
        address=EthereumAddress("0xAb10188207Ea030555f53C8A84339A92f473aa5e"),
        chain="gnosis",
        agent_id=25,
        marketplace=MarketplaceType.PEARL_MM,
        status=ContractStatus.FULL,
        bond_olas=5000,
        required_requests=7,
    ),
    StakingContractInfo(
        name="Pearl MM 2 (5k OLAS)",
        address=EthereumAddress("0x8d7bE092d154b01d404f1aCCFA22Cef98C613B5D"),
        chain="gnosis",
        agent_id=25,
        marketplace=MarketplaceType.PEARL_MM,
        status=ContractStatus.ACTIVE,
        bond_olas=5000,
        required_requests=7,
    ),
    StakingContractInfo(
        name="Pearl MM 3 (40 OLAS)",
        address=EthereumAddress("0x9D00A0551F20979080d3762005C9B74D7Aa77b85"),
        chain="gnosis",
        agent_id=25,
        marketplace=MarketplaceType.PEARL_MM,
        status=ContractStatus.ACTIVE,
        bond_olas=40,
        required_requests=5,
    ),
    StakingContractInfo(
        name="Pearl MM 4 (100 OLAS)",
        address=EthereumAddress("0xE2f80659dB1069f3B6a08af1A62064190c119543"),
        chain="gnosis",
        agent_id=25,
        marketplace=MarketplaceType.PEARL_MM,
        status=ContractStatus.ACTIVE,
        bond_olas=100,
        required_requests=5,
    ),
    # =====================================================================
    # GNOSIS — Agent ID 14 (Pearl Alpha) — Depleted
    # =====================================================================
    StakingContractInfo(
        name="Pearl Alpha (20 OLAS)",
        address=EthereumAddress("0xEE9F19b5DF06c7E8Bfc7B28745dcf944C504198A"),
        chain="gnosis",
        agent_id=14,
        marketplace=MarketplaceType.PEARL,
        status=ContractStatus.DEPLETED,
        bond_olas=20,
        required_requests=5,
    ),
    # =====================================================================
    # GNOSIS — Supply/Demand marketplace contracts (no fixed agent_id)
    # =====================================================================
    StakingContractInfo(
        name="Marketplace Supply Alpha (10k OLAS)",
        address=EthereumAddress("0xCAbD0C941E54147D40644CF7DA7e36d70DF46f44"),
        chain="gnosis",
        agent_id=None,
        marketplace=MarketplaceType.SUPPLY,
        status=ContractStatus.ACTIVE,
        bond_olas=10000,
        required_requests=20,
    ),
    StakingContractInfo(
        name="Marketplace Demand Alpha 1 (100 OLAS)",
        address=EthereumAddress("0x9d6e7aB0B5B48aE5c146936147C639fEf4575231"),
        chain="gnosis",
        agent_id=None,
        marketplace=MarketplaceType.DEMAND,
        status=ContractStatus.ACTIVE,
        bond_olas=100,
        required_requests=5,
    ),
    StakingContractInfo(
        name="Marketplace Demand Alpha 2 (1k OLAS)",
        address=EthereumAddress("0x9fb17E549FefcCA630dd92Ea143703CeE4Ea4340"),
        chain="gnosis",
        agent_id=None,
        marketplace=MarketplaceType.DEMAND,
        status=ContractStatus.ACTIVE,
        bond_olas=1000,
        required_requests=5,
    ),
    # =====================================================================
    # GNOSIS — Agent ID 25 — MM v1 DEFUNCT (mech 975 retired 2026-03-17)
    # =====================================================================
    StakingContractInfo(
        name="Expert 15 MM v1 (10k OLAS)",
        address=EthereumAddress("0x88eB38FF79fBa8C19943C0e5Acfa67D5876AdCC1"),
        chain="gnosis",
        agent_id=25,
        marketplace=MarketplaceType.MM_V1_DEFUNCT,
        status=ContractStatus.DEPLETED,
        bond_olas=10000,
        required_requests=60,
    ),
    StakingContractInfo(
        name="Expert 16 MM v1 (10k OLAS)",
        address=EthereumAddress("0x6c65430515c70a3f5E62107CC301685B7D46f991"),
        chain="gnosis",
        agent_id=25,
        marketplace=MarketplaceType.MM_V1_DEFUNCT,
        status=ContractStatus.DEPLETED,
        bond_olas=10000,
        required_requests=60,
    ),
    StakingContractInfo(
        name="Expert 17 MM v1 (10k OLAS)",
        address=EthereumAddress("0x1430107A785C3A36a0C1FC0ee09B9631e2E72aFf"),
        chain="gnosis",
        agent_id=25,
        marketplace=MarketplaceType.MM_V1_DEFUNCT,
        status=ContractStatus.FULL,
        bond_olas=10000,
        required_requests=60,
    ),
    StakingContractInfo(
        name="Expert 18 MM v1 (10k OLAS)",
        address=EthereumAddress("0x041e679d04Fc0D4f75Eb937Dea729Df09a58e454"),
        chain="gnosis",
        agent_id=25,
        marketplace=MarketplaceType.MM_V1_DEFUNCT,
        status=ContractStatus.DEPLETED,
        bond_olas=10000,
        required_requests=60,
    ),
    # =====================================================================
    # BASE — Agent ID 43 (Meme)
    # =====================================================================
    StakingContractInfo(
        name="Meme Base Alpha 2 (100 OLAS)",
        address=EthereumAddress("0xc653622FD75026a020995a1d8c8651316cBBc4dA"),
        chain="base",
        agent_id=43,
        marketplace=MarketplaceType.UNKNOWN,
        status=ContractStatus.ACTIVE,
        bond_olas=100,
        required_requests=2,
    ),
    StakingContractInfo(
        name="Meme Base Beta 2 (1k OLAS)",
        address=EthereumAddress("0xfb7669c3AdF673b3A545Fa5acd987dbfdA805e22"),
        chain="base",
        agent_id=43,
        marketplace=MarketplaceType.UNKNOWN,
        status=ContractStatus.ACTIVE,
        bond_olas=1000,
        required_requests=2,
    ),
    # =====================================================================
    # BASE — Supply/Demand marketplace contracts
    # =====================================================================
    StakingContractInfo(
        name="Marketplace Supply Alpha Base (10k OLAS)",
        address=EthereumAddress("0xB14Cd66c6c601230EA79fa7Cc072E5E0C2F3A756"),
        chain="base",
        agent_id=None,
        marketplace=MarketplaceType.SUPPLY,
        status=ContractStatus.ACTIVE,
        bond_olas=10000,
        required_requests=20,
    ),
    StakingContractInfo(
        name="Marketplace Demand Alpha 1 Base (100 OLAS)",
        address=EthereumAddress("0x38Eb3838Dab06932E7E1E965c6F922aDfE494b88"),
        chain="base",
        agent_id=None,
        marketplace=MarketplaceType.DEMAND,
        status=ContractStatus.ACTIVE,
        bond_olas=100,
        required_requests=5,
    ),
]


# ---------------------------------------------------------------------------
# Query function
# ---------------------------------------------------------------------------
def get_staking_contracts(
    chain: Optional[str] = None,
    agent_id: Optional[int] = None,
    marketplace: Optional[MarketplaceType | Sequence[MarketplaceType]] = None,
    status: Optional[ContractStatus | Sequence[ContractStatus]] = None,
) -> List[StakingContractInfo]:
    """Filter staking contracts. All parameters are optional (AND logic)."""
    results = STAKING_CONTRACTS
    if chain is not None:
        results = [c for c in results if c.chain == chain]
    if agent_id is not None:
        results = [c for c in results if c.agent_id == agent_id]
    if marketplace is not None:
        if isinstance(marketplace, MarketplaceType):
            mp_set = {marketplace}
        else:
            mp_set = set(marketplace)
        results = [c for c in results if c.marketplace in mp_set]
    if status is not None:
        if isinstance(status, ContractStatus):
            st_set = {status}
        else:
            st_set = set(status)
        results = [c for c in results if c.status in st_set]
    return results


# ---------------------------------------------------------------------------
# Backward-compatibility shim
# ---------------------------------------------------------------------------
def _build_trader_staking_compat() -> Dict[str, Dict[str, EthereumAddress]]:
    """Build the legacy OLAS_TRADER_STAKING_CONTRACTS dict from the registry.

    Excludes contracts whose marketplace is defunct (MM_V1_DEFUNCT) — the
    contracts themselves may be active on-chain, but their mech dependency
    no longer exists so triton cannot use them.
    """
    result: Dict[str, Dict[str, EthereumAddress]] = {}
    for c in get_staking_contracts(agent_id=25):
        if c.marketplace == MarketplaceType.MM_V1_DEFUNCT:
            continue
        result.setdefault(c.chain, {})[c.name] = c.address
    return result


OLAS_TRADER_STAKING_CONTRACTS: Dict[str, Dict[str, EthereumAddress]] = (
    _build_trader_staking_compat()
)


# Mech Marketplace Payment Types (bytes32 hex strings, without 0x prefix)
# From mech-client/marketplace_interact.py
PAYMENT_TYPE_NATIVE = (
    "ba699a34be8fe0e7725e93dcbce1701b0211a8ca61330aaeb8a05bf2ec7abed1"
)
PAYMENT_TYPE_TOKEN = (
    "3679d66ef546e66ce9057c4a052f317b135bc8e8c509638f7966edfd4fcf45e9"
)
PAYMENT_TYPE_NATIVE_NVM = (
    "803dd08fe79d91027fc9024e254a0942372b92f3ccabc1bd19f4a5c2b251c316"
)
PAYMENT_TYPE_TOKEN_NVM_USDC = (
    "0d6fd99afa9c4c580fab5e341922c2a5c4b61d880da60506193d7bf88944dd14"
)

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

# Grace period after epoch end before calling checkpoint (seconds)
CHECKPOINT_GRACE_PERIOD = 0

TRADER_CONFIG_HASH = (
    "108e90795119d6015274ef03af1a669c6d13ab6acc9e2b2978be01ee9ea2ec93"
)
DEFAULT_DEPLOY_PAYLOAD = "0x0000000000000000000000000000000000000000{fallback_handler}000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"

# OLAS Token address on Gnosis chain
OLAS_TOKEN_ADDRESS_GNOSIS = EthereumAddress(
    "0xcE11e14225575945b8E6Dc0D4F2dD4C570f79d9f"
)

# OLAS Protocol Contracts categorized by chain
# See mech_reference.py for comprehensive documentation of the mech ecosystem
OLAS_CONTRACTS: Dict[str, Dict[str, EthereumAddress]] = {
    "gnosis": {
        "OLAS_SERVICE_REGISTRY": EthereumAddress(
            "0x9338b5153AE39BB89f50468E608eD9d764B755fD"
        ),
        "OLAS_SERVICE_REGISTRY_TOKEN_UTILITY": EthereumAddress(
            "0xa45E64d13A30a51b91ae0eb182e88a40e9b18eD8"
        ),
        "OLAS_SERVICE_MANAGER": EthereumAddress(
            "0x068a4f0946cF8c7f9C1B58a3b5243Ac8843bf473"
        ),
        "OLAS_MECH": EthereumAddress(
            "0x77af31De935740567Cf4fF1986D04B2c964A786a"
        ),
        "OLAS_MECH_MARKETPLACE_V2": EthereumAddress(
            "0x735FAAb1c4Ec41128c367AFb5c3baC73509f70bB"
        ),
        "OLAS_MECH_MARKETPLACE_PRIORITY": EthereumAddress(
            "0xC05e7412439bD7e91730a6880E18d5D5873F632C"
        ),
    },
    "ethereum": {
        "OLAS_SERVICE_REGISTRY": EthereumAddress(
            "0x48b6F34dDAf31f94086BFB45e69e0618DDe3677b"
        ),
        "OLAS_SERVICE_REGISTRY_TOKEN_UTILITY": EthereumAddress(
            "0x3Fb926116D454b95c669B6Bf2E7c3bad8d19affA"
        ),
        "OLAS_SERVICE_MANAGER": EthereumAddress(
            "0x4443ddD8EC67CbCf7E291ee3198f81dD0326b3A1"
        ),
        "OLAS_MECH_MARKETPLACE_V2": EthereumAddress(
            "0x3d6494CE09a9f40c0B5a92BdBD7c7A9b0e3912b1"
        ),
    },
    "base": {
        "OLAS_SERVICE_REGISTRY": EthereumAddress(
            "0x3C1fF68f5aa342D296d4DEe4Bb1cACCA912D95fE"
        ),
        "OLAS_SERVICE_REGISTRY_TOKEN_UTILITY": EthereumAddress(
            "0x34C895f302D0b5cf52ec0Edd3945321EB0f83dd5"
        ),
        "OLAS_SERVICE_MANAGER": EthereumAddress(
            "0x1eAccD29c86fFc52Bd7cC0117C03D089306Cbc29"
        ),
        "OLAS_MECH_MARKETPLACE_V2": EthereumAddress(
            "0xf24eE42edA0fc9b33B7D41B06Ee8ccD2Ef7C5020"
        ),
    },
    "polygon": {
        "OLAS_SERVICE_REGISTRY": EthereumAddress(
            "0xE3607b00E75f6405248323A9417ff6b39B244b50"
        ),
        "OLAS_SERVICE_REGISTRY_TOKEN_UTILITY": EthereumAddress(
            "0xa45E64d13A30a51b91ae0eb182e88a40e9b18eD8"
        ),
        "OLAS_SERVICE_MANAGER": EthereumAddress(
            "0xC720f1Ada2a882a4B375dCCd0aAc3F3B3e58bc84"
        ),
        "OLAS_MECH_MARKETPLACE_V2": EthereumAddress(
            "0x343F2B005cF6D70bA610CD9F1F1927049414B582"
        ),
    },
    "optimism": {
        "OLAS_SERVICE_REGISTRY": EthereumAddress(
            "0x3d77596beb0f130a4415df3D2D8232B3d3D31e44"
        ),
        "OLAS_SERVICE_REGISTRY_TOKEN_UTILITY": EthereumAddress(
            "0xBb7e1D6Cb6F243D6bdE81CE92a9f2aFF7Fbe7eac"
        ),
        "OLAS_SERVICE_MANAGER": EthereumAddress(
            "0xA749f605D93B3efcc207C54270d83C6E8fa70fF8"
        ),
        "OLAS_MECH_MARKETPLACE_V2": EthereumAddress(
            "0x46C0D07F55d4F9B5Eed2Fc9680B5953e5fd7b461"
        ),
    },
    "arbitrum": {
        "OLAS_SERVICE_REGISTRY": EthereumAddress(
            "0xE3607b00E75f6405248323A9417ff6b39B244b50"
        ),
        "OLAS_SERVICE_REGISTRY_TOKEN_UTILITY": EthereumAddress(
            "0x3d77596beb0f130a4415df3D2D8232B3d3D31e44"
        ),
        "OLAS_SERVICE_MANAGER": EthereumAddress(
            "0x1c80bDBeD23dBb4ACEdCA136382bEa0162550515"
        ),
        "OLAS_MECH_MARKETPLACE_V2": EthereumAddress(
            "0xf76953444C35F1FcE2F6CA1b167173357d3F5C17"
        ),
    },
    "celo": {
        "OLAS_SERVICE_REGISTRY": EthereumAddress(
            "0xE3607b00E75f6405248323A9417ff6b39B244b50"
        ),
        "OLAS_SERVICE_REGISTRY_TOKEN_UTILITY": EthereumAddress(
            "0x3d77596beb0f130a4415df3D2D8232B3d3D31e44"
        ),
        "OLAS_SERVICE_MANAGER": EthereumAddress(
            "0x46C0D07F55d4F9B5Eed2Fc9680B5953e5fd7b461"
        ),
        "OLAS_MECH_MARKETPLACE_V2": EthereumAddress(
            "0x17d96ba4532fe91809326092fE4D5606A7B7a0d8"
        ),
    },
}

# Per-chain mech marketplace contracts (marketplace proxy, factory native, supply staking)
# Sources: autonolas-marketplace/docs/configuration.json, govern.olas.network
MECH_CONTRACTS: Dict[str, Dict[str, str]] = {
    "gnosis": {
        "marketplace": "0x735FAAb1c4Ec41128c367AFb5c3baC73509f70bB",
        "factory": "0x8b299c20F87e3fcBfF0e1B86dC0acC06AB6993EF",
        "staking": "0xCAbD0C941E54147D40644CF7DA7e36d70DF46f44",
    },
    "base": {
        "marketplace": "0xf24eE42edA0fc9b33B7D41B06Ee8ccD2Ef7C5020",
        "factory": "0x2E008211f34b25A7d7c102403c6C2C3B665a1abe",
        "staking": "0xB14Cd66c6c601230EA79fa7Cc072E5E0C2F3A756",
    },
    "ethereum": {
        "marketplace": "0x3d6494CE09a9f40c0B5a92BdBD7c7A9b0e3912b1",
        "factory": "0x3515a36AF270070635Fa3E957e006aaF6078e658",
        "staking": "0x5A40e2661b3EE672e945445F885F975a51A6c461",
    },
    "polygon": {
        "marketplace": "0x343F2B005cF6D70bA610CD9F1F1927049414B582",
        "factory": "0x87f89F94033305791B6269AE2F9cF4e09983E56e",
        "staking": "0x3aE11e2dD9a055AF3DA61ae2E36515D1612d7D93",
    },
    "optimism": {
        "marketplace": "0x46C0D07F55d4F9B5Eed2Fc9680B5953e5fd7b461",
        "factory": "0xf76953444C35F1FcE2F6CA1b167173357d3F5C17",
        "staking": "0xBb375c8d8517e6956AF7044FE676f2100505624f",
    },
    "arbitrum": {
        "marketplace": "0xf76953444C35F1FcE2F6CA1b167173357d3F5C17",
        "factory": "0x4Cd816ce806FF1003ee459158A093F02AbF042a8",
        "staking": "0x646ECbe31dF12D17A949d65764187408F6BB095d",
    },
    "celo": {
        "marketplace": "0x17d96ba4532fe91809326092fE4D5606A7B7a0d8",
        "factory": "0xDd1252c5a75be568B5E6e50bA542680b38dbd68f",
        "staking": "0x6CC3A0D25e2Ac7D8ff119ef92D5523259c6Dc821",
    },
}

# ComplementaryServiceMetadata contract addresses per chain
# Source: valory-xyz/autonolas-registries globals_*_mainnet.json
COMPLEMENTARY_SERVICE_METADATA: Dict[str, str] = {
    "gnosis": "0x0598081D48FB80B0A7E52FAD2905AE9beCd6fC69",
    "base": "0x28C1edC7CEd549F7f80B732fDC19f0370160707d",
    "ethereum": "0x0561cE39A1ab785B02DE0D9903125702559993A1",
    "arbitrum": "0x02C26437B292D86c5F4F21bbCcE0771948274f84",
    "optimism": "0x11949cBC85d8793B360029E26b18ae759708e28b",
    "polygon": "0xDC175E77d11246c79B23D7088750eb59160DD6b7",
    "celo": "0xc096362fa6f4A4B1a9ea68b1043416f3381ce300",
}
