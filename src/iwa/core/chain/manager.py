"""ChainInterfaces manager singleton."""

from typing import Dict

from iwa.core.chain.interface import ChainInterface
from iwa.core.chain.models import Base, Ethereum, Gnosis
from iwa.core.utils import singleton


@singleton
class ChainInterfaces:
    """ChainInterfaces"""

    gnosis: ChainInterface = ChainInterface(Gnosis())
    ethereum: ChainInterface = ChainInterface(Ethereum())
    base: ChainInterface = ChainInterface(Base())

    def get(self, chain_name: str) -> ChainInterface:
        """Get ChainInterface by chain name"""
        chain_name = chain_name.strip().lower()

        if not hasattr(self, chain_name):
            raise ValueError(f"Unsupported chain: {chain_name}")

        return getattr(self, chain_name)

    def items(self):
        """Iterate over all chain interfaces."""
        yield "gnosis", self.gnosis
        yield "ethereum", self.ethereum
        yield "base", self.base

    def check_all_rpcs(self) -> Dict[str, bool]:
        """Check health of all chain RPCs."""
        results = {}
        for name, interface in self.items():
            results[name] = interface.check_rpc_health()
        return results
