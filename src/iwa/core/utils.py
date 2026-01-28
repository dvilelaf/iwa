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


def get_tx_hash(receipt: dict) -> str:
    """Safely extract transaction hash from receipt (handles bytes/str/None)."""
    if not receipt:
        return "unknown"

    tx_hash = receipt.get("transactionHash", "")
    if hasattr(tx_hash, "hex"):
        return tx_hash.hex()
    return str(tx_hash) if tx_hash else "unknown"


def configure_logger():
    """Configure the logger for the application."""
    if hasattr(configure_logger, "configured"):
        return logger

    import logging

    from iwa.core.constants import DATA_DIR

    # Silence noisy third-party loggers (these use stdlib logging, not loguru)
    logging.getLogger("apscheduler.scheduler").setLevel(logging.WARNING)
    logging.getLogger("apscheduler.executors.default").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    logger.remove()

    # Ensure data directory exists
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    import sys

    logger.add(
        DATA_DIR / "iwa.log",
        rotation="10 MB",
        level="INFO",
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} - {message}",
    )
    # Restore console logging (stderr) so logs are visible in docker/systemd/frontend streams
    logger.add(sys.stderr, level="INFO")
    # Also keep stderr for console if needed, but Textual captures it?
    # Textual usually captures stderr. Writing to file is safer for debugging.
    # Users previous logs show stdout format?

    configure_logger.configured = True
    return logger


def get_version(package_name: str) -> str:
    """Get package version."""
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version(package_name)
    except PackageNotFoundError:
        return "unknown"


def print_banner(service_name: str, service_version: str, extra_versions: dict = None) -> None:
    """Print startup banner."""
    try:
        from rich.console import Console
        from rich.panel import Panel
        from rich.text import Text

        console = Console(stderr=True)

        # Build content
        text = Text()
        text.append(f"🚀 {service_name.upper()} ", style="bold cyan")
        text.append(f"v{service_version}", style="bold yellow")

        if extra_versions:
            for name, ver in extra_versions.items():
                text.append(f"\n📦 {name.upper()}: ", style="bold green")
                text.append(f"v{ver}", style="bold yellow")

        console.print(Panel(text, title="Startup", border_style="blue"))

    except ImportError:
        # Fallback if rich is not available
        print(f"--- {service_name.upper()} v{service_version} ---")
        if extra_versions:
            for name, ver in extra_versions.items():
                print(f"    {name.upper()}: v{ver}")
        print("-------------------------------")
