#!/usr/bin/env python3
"""Tool to check the active Tenderly profile."""

import requests

from iwa.core.settings import settings


def check_rpc_status(rpc_url):
    """Check the status of an RPC endpoint."""
    if not rpc_url:
        print(" [!] No RPC URL found in secrets.env for this profile.")
        return

    print(f" Checking RPC: {rpc_url}")

    headers = {"Content-Type": "application/json"}
    # Include access key if present
    if settings.tenderly_access_key:
        headers["X-Access-Key"] = settings.tenderly_access_key.get_secret_value()

    payload = {"jsonrpc": "2.0", "method": "eth_blockNumber", "params": [], "id": 1}

    try:
        response = requests.post(rpc_url, json=payload, headers=headers, timeout=5)

        # Check for HTTP errors (like 403)
        if response.status_code != 200:
            print(f" [X] HTTP ERROR: {response.status_code}")
            try:
                err = response.json()
                if "error" in err:
                    print(f"     Details: {err['error']}")
            except Exception:
                print(f"     Response text: {response.text}")

            if response.status_code == 403:
                print("     => LIKELY QUOTA EXCEEDED (Rate Limit).")
            return

        # Check for JSON-RPC errors (like -32004)
        data = response.json()
        if "error" in data:
            code = data["error"].get("code")
            msg = data["error"].get("message")
            print(f" [X] JSON-RPC ERROR: {code} - {msg}")
            if code == -32004:
                print("     => QUOTA LIMIT REACHED.")
        else:
            block = int(data["result"], 16)
            print(f" [OK] API Operational. Block: {block}")

    except Exception as e:
        print(f" [!] Exception checking RPC: {e}")


def main():
    """Check and display the active Tenderly profile status."""
    print(f"Active Tenderly Profile: {settings.tenderly_profile}")

    # Check Gnosis RPC as primary indicator
    rpc = settings.gnosis_rpc.get_secret_value() if settings.gnosis_rpc else None
    check_rpc_status(rpc)


if __name__ == "__main__":
    main()
