#!/usr/bin/env python3
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from iwa.core.chain import ChainInterfaces
from web3 import Web3
from iwa.plugins.olas.contracts.mech_marketplace import MechMarketplaceContract

def main():
    chain = ChainInterfaces().gnosis
    mp_address = "0x735FAAb1c4Ec41128c367AFb5c3baC73509f70bB"

    # Reload ABI from disk (now updated)
    mp = MechMarketplaceContract(str(mp_address), chain_name="gnosis")

    candidates = [
        (Web3.to_checksum_address("0xf035cc0dd8f31af8db93ed7451788bf431859710"), "Agent Instance (0xf035)"),
        (Web3.to_checksum_address("0x552cEA7Bc33CbBEb9f1D90c1D11D2C6daefFd053"), "Triton Config (0x552c)"),
        (Web3.to_checksum_address("0x69C0669F3b5df0F2E2644F01098B4465f5652101"), "Service Multisig (0x69C0)"),
        (Web3.to_checksum_address("0xEB2A22b27C7Ad5eeE424Fd90b376c745E60f914E"), "Service Owner (0xEB2A)"),
    ]

    print(f"Marketplace: {mp_address}")
    print("Testing checkMech(address)...")

    for mech, desc in candidates:
        try:
            # New ABI should have checkMech(address)
            res = mp.contract.functions.checkMech(mech).call()
            print(f"✅ {desc} PASSED! Multisig: {res}")
        except Exception as e:
            # Check if selector matches checkMech(address) = 32b2baa3
            try:
                sel = Web3.keccak(text="checkMech(address)")[:4].hex()
                # print(f"Selector checkMech(address): {sel}")
                pass
            except: pass

            print(f"❌ {desc} FAILED: {str(e)[:100]}...")

if __name__ == "__main__":
    main()
