#!/usr/bin/env python3
"""Tool to reset the full environment.

1. Resets Tenderly networks (based on active profile).
2. Clears Olas services from config.yaml.
3. Clears all accounts from wallet.json except 'master'.
"""

import json
import subprocess  # nosec B404
import sys

import yaml

from iwa.core.constants import CONFIG_PATH, WALLET_PATH
from iwa.core.settings import settings


def _reset_tenderly(profile: int) -> None:
    """Reset Tenderly networks using just command."""
    cmd = ["just", "reset-tenderly", str(profile)]
    print(f"Running: {' '.join(cmd)}")
    try:
        subprocess.check_call(cmd)  # nosec B603
    except subprocess.CalledProcessError as e:
        print(f"Error running reset-tenderly: {e}")
        sys.exit(1)


def _clean_olas_services() -> None:
    """Remove all Olas services from config.yaml."""
    if not CONFIG_PATH.exists():
        return

    try:
        with open(CONFIG_PATH, "r") as f:
            config = yaml.safe_load(f) or {}

        if "plugins" not in config or "olas" not in config["plugins"]:
            return

        if "services" not in config["plugins"]["olas"]:
            return

        services = config["plugins"]["olas"]["services"]
        if not services:
            print("No Olas services found in config.yaml.")
            return

        print(f"Removing {len(services)} Olas services from config.yaml...")
        config["plugins"]["olas"]["services"] = {}
        with open(CONFIG_PATH, "w") as f:
            yaml.dump(config, f)
    except Exception as e:
        print(f"Error cleaning config.yaml: {e}")


def _clean_wallet_accounts() -> None:
    """Remove all accounts from wallet.json except master."""
    if not WALLET_PATH.exists():
        return

    try:
        with open(WALLET_PATH, "r") as f:
            data = json.load(f)

        accounts = data.get("accounts", {})

        # Find master account
        master_addr = None
        master_acct = None
        for addr, acct in accounts.items():
            if acct.get("tag") == "master":
                master_addr = addr
                master_acct = acct
                break

        if not master_addr:
            print(
                "Warning: Master account not found in wallet.json! Skipping cleanup to avoid data loss."
            )
            return

        if len(accounts) <= 1:
            print("Only master account exists in wallet.json.")
            return

        print(
            f"Preserving master account ({master_addr}), removing {len(accounts) - 1} other accounts..."
        )
        data["accounts"] = {master_addr: master_acct}
        with open(WALLET_PATH, "w") as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        print(f"Error cleaning wallet.json: {e}")


def main():
    """Reset the environment by clearing networks, services, and accounts."""
    profile = settings.tenderly_profile
    print(f"Detected Tenderly profile: {profile}")

    _reset_tenderly(profile)
    _clean_olas_services()
    _clean_wallet_accounts()

    print("Environment reset complete.")


if __name__ == "__main__":
    main()
