"""Chain model definitions."""

from typing import Dict, List, Optional

from pydantic import BaseModel

from iwa.core.models import EthereumAddress
from iwa.core.settings import settings
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
        try:
            address = EthereumAddress(token_address_or_name)
        except Exception:
            address = None

        if address and address in self.tokens.values():
            return address

        if address is None:
            return self.tokens.get(token_address_or_name, None)

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
        if not self.rpcs and settings.gnosis_rpc:
            self.rpcs = settings.gnosis_rpc.get_secret_value().split(",")


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
    contracts: Dict[str, EthereumAddress] = {}

    def __init__(self, **data):
        """Initialize with RPCs from settings (after testing override is applied)."""
        super().__init__(**data)
        if not self.rpcs and settings.ethereum_rpc:
            self.rpcs = settings.ethereum_rpc.get_secret_value().split(",")


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
    contracts: Dict[str, EthereumAddress] = {}

    def __init__(self, **data):
        """Initialize with RPCs from settings (after testing override is applied)."""
        super().__init__(**data)
        if not self.rpcs and settings.base_rpc:
            self.rpcs = settings.base_rpc.get_secret_value().split(",")


@singleton
class SupportedChains:
    """SupportedChains"""

    gnosis: SupportedChain = Gnosis()
    ethereum: SupportedChain = Ethereum()
    base: SupportedChain = Base()
