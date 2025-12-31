#!/usr/bin/env python3
"""
Tool to reset the full environment:
1. Resets Tenderly networks (based on active profile).
2. Clears Olas services from config.yaml.
3. Clears all accounts from wallet.json except 'master'.
"""

import json
import subprocess
import sys
import yaml
from iwa.core.constants import CONFIG_PATH, WALLET_PATH
from iwa.core.settings import settings


def main():
    # 1. Get profile from settings
    profile = settings.tenderly_profile
    print(f"Detected Tenderly profile: {profile}")

    # 2. Call reset-tenderly
    cmd = ["just", "reset-tenderly", str(profile)]
    print(f"Running: {' '.join(cmd)}")
    try:
        subprocess.check_call(cmd)
    except subprocess.CalledProcessError as e:
        print(f"Error running reset-tenderly: {e}")
        sys.exit(1)

    # 3. Clean config.yaml
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r") as f:
                config = yaml.safe_load(f) or {}

            # Remove olas services
            if "plugins" in config and "olas" in config["plugins"]:
                if "services" in config["plugins"]["olas"]:
                    services = config["plugins"]["olas"]["services"]
                    if services:
                        print(f"Removing {len(services)} Olas services from config.yaml...")
                        config["plugins"]["olas"]["services"] = {}
                        with open(CONFIG_PATH, "w") as f:
                            yaml.dump(config, f)
                    else:
                        print("No Olas services found in config.yaml.")
        except Exception as e:
            print(f"Error cleaning config.yaml: {e}")

    # 4. Clean wallet.json
    if WALLET_PATH.exists():
        try:
            with open(WALLET_PATH, "r") as f:
                data = json.load(f)

            accounts = data.get("accounts", {})
            master_acct = None
            master_addr = None

            # Find master account
            for addr, acct in accounts.items():
                if acct.get("tag") == "master":
                    master_addr = addr
                    master_acct = acct
                    break

            if master_addr:
                if len(accounts) > 1:
                    print(f"Preserving master account ({master_addr}), removing {len(accounts) - 1} other accounts...")
                    data["accounts"] = {master_addr: master_acct}
                    with open(WALLET_PATH, "w") as f:
                        json.dump(data, f, indent=4)
                else:
                    print("Only master account exists in wallet.json.")
            else:
                print("Warning: Master account not found in wallet.json! Skipping cleanup to avoid data loss.")
        except Exception as e:
            print(f"Error cleaning wallet.json: {e}")

    print("Environment reset complete.")


if __name__ == "__main__":
    main()
