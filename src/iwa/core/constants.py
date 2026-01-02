"""Core constants"""

from pathlib import Path

from iwa.core.types import EthereumAddress

PROJECT_ROOT = Path(__file__).parent.parent.parent.parent

# Data directory for sensitive/runtime files
DATA_DIR = PROJECT_ROOT / "data"

SECRETS_PATH = DATA_DIR / "secrets.env"
CONFIG_PATH = DATA_DIR / "config.yaml"
WALLET_PATH = DATA_DIR / "wallet.json"
BACKUP_DIR = DATA_DIR / "backup"
TENDERLY_CONFIG_PATH = PROJECT_ROOT / "tenderly.yaml"

ABI_PATH = PROJECT_ROOT / "src" / "iwa" / "core" / "contracts" / "abis"

# Standard Ethereum addresses
ZERO_ADDRESS = EthereumAddress("0x0000000000000000000000000000000000000000")
NATIVE_CURRENCY_ADDRESS = EthereumAddress("0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE")
DEFAULT_MECH_CONTRACT_ADDRESS = EthereumAddress("0x77af31De935740567Cf4FF1986D04B2c964A786a")


def get_tenderly_config_path(profile: int = 1) -> Path:
    """Get the path to a profile-specific Tenderly config file."""
    return PROJECT_ROOT / f"tenderly_{profile}.yaml"
