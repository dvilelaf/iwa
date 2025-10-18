"""Utility functions"""

from safe_eth.safe.addresses import MASTER_COPIES
from safe_eth.eth import EthereumNetwork


def singleton(cls):
    """Singleton decorator to ensure a class has only one instance."""
    instances = {}

    def get_instance(*args, **kwargs):
        if cls not in instances:
            instances[cls] = cls(*args, **kwargs)
        return instances[cls]

    return get_instance


def get_safe_master_copy_address(target_version: str = "1.4.1") -> str:
    """Get Safe master copy address by version"""

    for address, _, version in MASTER_COPIES[EthereumNetwork.MAINNET]:
        if version == target_version:
            return address
    raise ValueError(f"Did not find master copy for version {target_version}")
