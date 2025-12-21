"""Core constants"""

from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent.parent

SECRETS_PATH = PROJECT_ROOT / "secrets.env"
CONFIG_PATH = PROJECT_ROOT / "config.yaml"
WALLET_PATH = PROJECT_ROOT / "wallet.json"
TENDERLY_CONFIG_PATH = PROJECT_ROOT / "tenderly.yaml"

ABI_PATH = PROJECT_ROOT / "src" / "iwa" / "core" / "contracts" / "abis"

NATIVE_CURRENCY_ADDRESS = "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE"
DEFAULT_MECH_CONTRACT_ADDRESS = "0x77af31De935740567Cf4FF1986D04B2c964A786a"


def get_tenderly_config_path(profile: int = 1) -> Path:
    """Get the path to a profile-specific Tenderly config file."""
    return PROJECT_ROOT / f"tenderly_{profile}.yaml"
