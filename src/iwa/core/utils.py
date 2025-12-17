"""Utility functions"""

from loguru import logger
from safe_eth.eth import EthereumNetwork
from safe_eth.safe.addresses import MASTER_COPIES, PROXY_FACTORIES


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


def get_safe_proxy_factory_address(target_version: str = "1.4.1") -> str:
    """Get Safe proxy factory address by version"""
    # PROXY_FACTORIES values are (address, block_number) without version
    # converting 1.4.1 address manually if needed, or returning the one found.
    # The address 0x4e1DCf7AD4e460CfD30791CCC4F9c8a4f820ec67 is for 1.4.1
    if target_version == "1.4.1":
        return "0x4e1DCf7AD4e460CfD30791CCC4F9c8a4f820ec67"

    for address, _ in PROXY_FACTORIES[EthereumNetwork.MAINNET]:
        return address
    raise ValueError(f"Did not find proxy factory for version {target_version}")


def configure_logger():
    """Configure the logger for the application."""
    if hasattr(configure_logger, "configured"):
        return logger

    logger.remove()

    logger.add(
        "iwa.log",
        rotation="10 MB",
        level="INFO",
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} - {message}",
    )
    # Also keep stderr for console if needed, but Textual captures it?
    # Textual usually captures stderr. Writing to file is safer for debugging.
    # Users previous logs show stdout format?

    configure_logger.configured = True
    return logger
