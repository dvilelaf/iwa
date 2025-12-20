#!/usr/bin/env python3
from web3 import Web3

def main():
    import json
    from pathlib import Path

    abi_path = Path("/media/david/DATA/repos/iwa/src/iwa/plugins/olas/contracts/abis/mech_marketplace.json")
    with open(abi_path) as f:
        abi = json.load(f)

    target = "0x7c946ed7"
    print(f"Target: {target}")

    for item in abi:
        if item["type"] == "error":
            name = item["name"]
            inputs = ",".join([i["type"] for i in item.get("inputs", [])])
            sig = f"{name}({inputs})"
            sel = Web3.keccak(text=sig)[:4].hex()
            # print(f"{sig} -> {sel}")
            if sel == target:
                print(f"✅ MATCH FOUND: {sig}")
                return

    print("❌ No match found in ABI.")

if __name__ == "__main__":
    main()
