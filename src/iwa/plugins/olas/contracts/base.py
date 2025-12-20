"""Base contract class."""

from pathlib import Path

from iwa.core.contracts.contract import ContractInstance

# OLAS plugin-specific ABI path
OLAS_ABI_PATH = Path(__file__).parent / "abis"

__all__ = ["ContractInstance", "OLAS_ABI_PATH"]
