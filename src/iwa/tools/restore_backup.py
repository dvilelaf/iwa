#!/usr/bin/env python3
"""Validate and restore wallet backup."""

import json
import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
WALLET_PATH = DATA_DIR / "wallet.json"
BACKUP_DIR = DATA_DIR / "backup"


def validate_wallet_backup(backup_path: Path) -> tuple[bool, str, int]:
    """Validate that backup file is a valid wallet using Pydantic models.

    Returns:
        Tuple of (is_valid, message, account_count)

    """
    from iwa.core.keys import EncryptedAccount, StoredSafeAccount
    from iwa.core.models import EthereumAddress

    try:
        with open(backup_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        return False, f"Invalid JSON: {e}", 0

    if not isinstance(data, dict) or "accounts" not in data:
        return False, "Missing 'accounts' key", 0

    accounts = data.get("accounts", {})
    if not isinstance(accounts, dict):
        return False, "'accounts' must be a dictionary", 0

    # Validate each account using Pydantic models
    for address, account_data in accounts.items():
        try:
            # Validate address
            EthereumAddress(address)

            # Validate account structure
            if "signers" in account_data:
                StoredSafeAccount(**account_data)
            else:
                EncryptedAccount(**account_data)
        except Exception as e:
            return False, f"Invalid account {address[:10]}...: {e}", 0

    return True, "Valid wallet structure", len(accounts)


def restore_backup(backup_name: str) -> int:
    """Restore wallet from backup with validation."""
    backup_path = BACKUP_DIR / backup_name

    if not backup_path.exists():
        print(f"Error: Backup file not found: {backup_path}")
        return 1

    is_valid, message, num_accounts = validate_wallet_backup(backup_path)
    if not is_valid:
        print(f"Error: {message}")
        return 1

    print(f"Backup validated: {num_accounts} account(s) found")

    # Restore
    shutil.copy2(backup_path, WALLET_PATH)
    print(f"Restored wallet from {backup_name}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: restore_backup.py <backup_filename>")
        print("Example: restore_backup.py wallet.json.20260102_101400.bkp")
        sys.exit(1)

    sys.exit(restore_backup(sys.argv[1]))
