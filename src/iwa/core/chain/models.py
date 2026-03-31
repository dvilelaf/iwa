"""Chain model definitions."""

from typing import Dict, List, Optional

from pydantic import BaseModel

from iwa.core.models import EthereumAddress
from iwa.core.secrets import secrets
from iwa.core.utils import singleton


class SupportedChain(BaseModel):
    """SupportedChain"""

    name: str
    rpcs: List[str]
    chain_id: int
    native_currency: str
    tokens: Dict[str, EthereumAddress] = {}
    contracts: Dict[str, EthereumAddress] = {}

    @property
    def rpc(self) -> str:
        """Get the primary RPC URL."""
        return self.rpcs[0] if self.rpcs else ""

    def get_token_address(self, token_address_or_name: str) -> Optional[EthereumAddress]:
        """Get token address"""
        if not token_address_or_name:
            return None

        try:
            address = EthereumAddress(token_address_or_name)
        except Exception:
            address = None

        if address and address in self.tokens.values():
            return address

        if address is None:
            # Try direct lookup
            token_addr = self.tokens.get(token_address_or_name, None)
            if token_addr:
                return token_addr

            # Try case-insensitive lookup
            target_lower = token_address_or_name.lower()
            for name, addr in self.tokens.items():
                if name.lower() == target_lower:
                    return addr

            return None

    def get_token_name(self, token_address: str) -> Optional[str]:
        """Get token name from address."""
        addr_lower = token_address.lower()
        for name, addr in self.tokens.items():
            if addr.lower() == addr_lower:
                return name
        return None


@singleton
class Gnosis(SupportedChain):
    """Gnosis Chain"""

    name: str = "Gnosis"
    rpcs: List[str] = []  # Set dynamically in __init__
    chain_id: int = 100
    native_currency: str = "xDAI"
    tokens: Dict[str, EthereumAddress] = {
        "OLAS": EthereumAddress("0xcE11e14225575945b8E6Dc0D4F2dD4C570f79d9f"),
        "WXDAI": EthereumAddress("0xe91D153E0b41518A2Ce8Dd3D7944Fa863463a97d"),
        "USDC": EthereumAddress("0x2a22f9c3b484c3629090FeED35F17Ff8F88f76F0"),
        "SDAI": EthereumAddress("0xaf204776c7245bF4147c2612BF6e5972Ee483701"),
        "EURE": EthereumAddress("0xcB444e90D8198415266c6a2724b7900fb12FC56E"),
    }
    contracts: Dict[str, EthereumAddress] = {
        "GNOSIS_SAFE_MULTISIG_IMPLEMENTATION": EthereumAddress(
            "0x3C1fF68f5aa342D296d4DEe4Bb1cACCA912D95fE"
        ),
        "GNOSIS_SAFE_FALLBACK_HANDLER": EthereumAddress(
            "0xf48f2b2d2a534e402487b3ee7c18c33aec0fe5e4"
        ),
    }

    def __init__(self, **data):
        """Initialize with RPCs from settings (after testing override is applied)."""
        super().__init__(**data)
        if not self.rpcs and secrets.gnosis_rpc:
            self.rpcs = secrets.gnosis_rpc.get_secret_value().split(",")

        # Defensive: ensure no comma-separated strings and NO quotes in list
        new_rpcs = []
        for rpc in self.rpcs:
            parts = [r.strip().strip("'\"") for r in rpc.split(",") if r.strip()]
            new_rpcs.extend(parts)
        self.rpcs = new_rpcs


@singleton
class Ethereum(SupportedChain):
    """Ethereum Mainnet"""

    name: str = "Ethereum"
    rpcs: List[str] = []  # Set dynamically in __init__
    chain_id: int = 1
    native_currency: str = "ETH"
    tokens: Dict[str, EthereumAddress] = {
        "OLAS": EthereumAddress("0x0001A500A6B18995B03f44bb040A5fFc28E45CB0"),
    }
    contracts: Dict[str, EthereumAddress] = {
        "GNOSIS_SAFE_MULTISIG_IMPLEMENTATION": EthereumAddress(
            "0x46C0D07F55d4F9B5Eed2Fc9680B5953e5fd7b461"
        ),
        "GNOSIS_SAFE_FALLBACK_HANDLER": EthereumAddress(
            "0xf48f2B2d2a534e402487b3ee7C18c33Aec0Fe5e4"
        ),
    }

    def __init__(self, **data):
        """Initialize with RPCs from settings (after testing override is applied)."""
        super().__init__(**data)
        if not self.rpcs and secrets.ethereum_rpc:
            self.rpcs = secrets.ethereum_rpc.get_secret_value().split(",")

        # Defensive: ensure no comma-separated strings and NO quotes in list
        new_rpcs = []
        for rpc in self.rpcs:
            parts = [r.strip().strip("'\"") for r in rpc.split(",") if r.strip()]
            new_rpcs.extend(parts)
        self.rpcs = new_rpcs


@singleton
class Base(SupportedChain):
    """Base"""

    name: str = "Base"
    rpcs: List[str] = []  # Set dynamically in __init__
    chain_id: int = 8453
    native_currency: str = "ETH"
    tokens: Dict[str, EthereumAddress] = {
        "OLAS": EthereumAddress("0x54330d28ca3357F294334BDC454a032e7f353416"),
    }
    contracts: Dict[str, EthereumAddress] = {
        "GNOSIS_SAFE_MULTISIG_IMPLEMENTATION": EthereumAddress(
            "0x22bE6fDcd3e29851B29b512F714C328A00A96B83"
        ),
        "GNOSIS_SAFE_FALLBACK_HANDLER": EthereumAddress(
            "0xf48f2B2d2a534e402487b3ee7C18c33Aec0Fe5e4"
        ),
    }

    def __init__(self, **data):
        """Initialize with RPCs from settings (after testing override is applied)."""
        super().__init__(**data)
        if not self.rpcs and secrets.base_rpc:
            self.rpcs = secrets.base_rpc.get_secret_value().split(",")

        # Defensive: ensure no comma-separated strings and NO quotes in list
        new_rpcs = []
        for rpc in self.rpcs:
            parts = [r.strip().strip("'\"") for r in rpc.split(",") if r.strip()]
            new_rpcs.extend(parts)
        self.rpcs = new_rpcs


@singleton
class Polygon(SupportedChain):
    """Polygon POS"""

    name: str = "Polygon"
    rpcs: List[str] = []
    chain_id: int = 137
    native_currency: str = "POL"
    tokens: Dict[str, EthereumAddress] = {
        "OLAS": EthereumAddress("0xFEF5d947472e72Efbb2E388c730B7428406F2F95"),
    }
    contracts: Dict[str, EthereumAddress] = {
        "GNOSIS_SAFE_MULTISIG_IMPLEMENTATION": EthereumAddress(
            "0x3d77596beb0f130a4415df3D2D8232B3d3D31e44"
        ),
        "GNOSIS_SAFE_FALLBACK_HANDLER": EthereumAddress(
            "0xf48f2B2d2a534e402487b3ee7C18c33Aec0Fe5e4"
        ),
    }

    def __init__(self, **data):
        super().__init__(**data)
        if not self.rpcs and secrets.polygon_rpc:
            self.rpcs = secrets.polygon_rpc.get_secret_value().split(",")
        new_rpcs = []
        for rpc in self.rpcs:
            parts = [r.strip().strip("'\"") for r in rpc.split(",") if r.strip()]
            new_rpcs.extend(parts)
        self.rpcs = new_rpcs


@singleton
class Optimism(SupportedChain):
    """Optimism"""

    name: str = "Optimism"
    rpcs: List[str] = []
    chain_id: int = 10
    native_currency: str = "ETH"
    tokens: Dict[str, EthereumAddress] = {
        "OLAS": EthereumAddress("0xFC2E6e6BCbd49ccf3A5f029c79984372DcBFE527"),
    }
    contracts: Dict[str, EthereumAddress] = {
        "GNOSIS_SAFE_MULTISIG_IMPLEMENTATION": EthereumAddress(
            "0x5953f21495BD9aF1D78e87bb42AcCAA55C1e896C"
        ),
        "GNOSIS_SAFE_FALLBACK_HANDLER": EthereumAddress(
            "0xf48f2B2d2a534e402487b3ee7C18c33Aec0Fe5e4"
        ),
    }

    def __init__(self, **data):
        super().__init__(**data)
        if not self.rpcs and secrets.optimism_rpc:
            self.rpcs = secrets.optimism_rpc.get_secret_value().split(",")
        new_rpcs = []
        for rpc in self.rpcs:
            parts = [r.strip().strip("'\"") for r in rpc.split(",") if r.strip()]
            new_rpcs.extend(parts)
        self.rpcs = new_rpcs


@singleton
class Arbitrum(SupportedChain):
    """Arbitrum One"""

    name: str = "Arbitrum"
    rpcs: List[str] = []
    chain_id: int = 42161
    native_currency: str = "ETH"
    tokens: Dict[str, EthereumAddress] = {
        "OLAS": EthereumAddress("0x064F8B858C2A603e1b106a2039f5446D32DC81C1"),
    }
    contracts: Dict[str, EthereumAddress] = {
        "GNOSIS_SAFE_MULTISIG_IMPLEMENTATION": EthereumAddress(
            "0x63e66d7ad413C01A7b49C7FF4e3Bb765C4E4bd1b"
        ),
        "GNOSIS_SAFE_FALLBACK_HANDLER": EthereumAddress(
            "0xf48f2B2d2a534e402487b3ee7C18c33Aec0Fe5e4"
        ),
    }

    def __init__(self, **data):
        super().__init__(**data)
        if not self.rpcs and secrets.arbitrum_rpc:
            self.rpcs = secrets.arbitrum_rpc.get_secret_value().split(",")
        new_rpcs = []
        for rpc in self.rpcs:
            parts = [r.strip().strip("'\"") for r in rpc.split(",") if r.strip()]
            new_rpcs.extend(parts)
        self.rpcs = new_rpcs


@singleton
class Celo(SupportedChain):
    """Celo"""

    name: str = "Celo"
    rpcs: List[str] = []
    chain_id: int = 42220
    native_currency: str = "CELO"
    tokens: Dict[str, EthereumAddress] = {
        "OLAS": EthereumAddress("0xaCFfAe8e57Ec6E394Eb1b41939A8CF7892DbDc51"),
    }
    contracts: Dict[str, EthereumAddress] = {
        "GNOSIS_SAFE_MULTISIG_IMPLEMENTATION": EthereumAddress(
            "0x63e66d7ad413C01A7b49C7FF4e3Bb765C4E4bd1b"
        ),
        "GNOSIS_SAFE_FALLBACK_HANDLER": EthereumAddress(
            "0xf48f2B2d2a534e402487b3ee7C18c33Aec0Fe5e4"
        ),
    }

    def __init__(self, **data):
        super().__init__(**data)
        if not self.rpcs and secrets.celo_rpc:
            self.rpcs = secrets.celo_rpc.get_secret_value().split(",")
        new_rpcs = []
        for rpc in self.rpcs:
            parts = [r.strip().strip("'\"") for r in rpc.split(",") if r.strip()]
            new_rpcs.extend(parts)
        self.rpcs = new_rpcs


@singleton
class SupportedChains:
    """SupportedChains"""

    gnosis: SupportedChain = Gnosis()
    ethereum: SupportedChain = Ethereum()
    base: SupportedChain = Base()
    polygon: SupportedChain = Polygon()
    optimism: SupportedChain = Optimism()
    arbitrum: SupportedChain = Arbitrum()
    celo: SupportedChain = Celo()
