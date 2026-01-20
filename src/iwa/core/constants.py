"""Core constants"""

from pathlib import Path

from iwa.core.types import EthereumAddress

PROJECT_ROOT = Path(__file__).parent.parent.parent.parent

# Data directory for runtime files
DATA_DIR = Path("data")
CACHE_DIR = DATA_DIR / "cache"

# secrets.env is at project root (NOT in data/)
SECRETS_PATH = Path("secrets.env")
CONFIG_PATH = DATA_DIR / "config.yaml"
WALLET_PATH = DATA_DIR / "wallet.json"
BACKUP_DIR = DATA_DIR / "backup"
TENDERLY_CONFIG_PATH = Path("tenderly.yaml")

ABI_PATH = Path(__file__).parent / "contracts" / "abis"

# Standard Ethereum addresses
ZERO_ADDRESS = EthereumAddress("0x0000000000000000000000000000000000000000")
NATIVE_CURRENCY_ADDRESS = EthereumAddress("0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE")
DEFAULT_MECH_CONTRACT_ADDRESS = EthereumAddress("0x77af31De935740567Cf4FF1986D04B2c964A786a")


def get_tenderly_config_path(profile: int = 1) -> Path:
    """Get the path to a profile-specific Tenderly config file."""
    return Path(f"tenderly_{profile}.yaml")
