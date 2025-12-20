#!/usr/bin/env python3
from web3 import Web3

def main():
    selector = "0x4b6c6927"
    candidates = [
        "MarketplaceOnly(address)",
        "OnlyMarketplace(address)",
        "Unauthorized(address)",
        "NotMarketplace(address)"
    ]

    print(f"Selector: {selector}")
    for c in candidates:
        h = Web3.keccak(text=c)[:4].hex()
        # print(f"  {c} -> {h}")
        if h == selector:
            print(f"✅ Match Found: {c}")
            return

    print("❌ No match found in candidates.")

if __name__ == "__main__":
    main()
