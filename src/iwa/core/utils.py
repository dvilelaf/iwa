"""Utility functions"""

from safe_eth.safe.addresses import MASTER_COPIES
from safe_eth.eth import EthereumNetwork
from loguru import logger
import sys


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


def configure_logger():
    """Configure the logger for the application."""
    logger.remove()

    logger.add(
        sys.stderr,
        level="INFO",
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level}</level> | {message}",
        colorize=True,
    )

    logger.add(
        sys.stderr,
        level="WARNING",
        format="<yellow>{time:YYYY-MM-DD HH:mm:ss}</yellow> | <level>{level}</level> | {module}:{function}:{line} | {message}",
        colorize=True,
    )

    return logger
