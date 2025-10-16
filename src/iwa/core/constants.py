"""Core constants"""

from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
SECRETS_PATH = PROJECT_ROOT / "secrets.env"
CONFIG_PATH = PROJECT_ROOT / "config.toml"
WALLET_PATH = PROJECT_ROOT / "wallets.json"
