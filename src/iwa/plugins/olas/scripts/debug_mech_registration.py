#!/usr/bin/env python3
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from iwa.core.chain import ChainInterfaces
from iwa.plugins.olas.contracts.mech_marketplace import MechMarketplaceContract
from web3 import Web3

def main():
    import json

    chain = ChainInterfaces().gnosis
    mp_address = "0x735FAAb1c4Ec41128c367AFb5c3baC73509f70bB"

    abi_path = Path("/media/david/DATA/repos/iwa/src/iwa/plugins/olas/contracts/abis/mech_marketplace.json")
    with open(abi_path) as f:
        abi = json.load(f)

    contract = chain.web3.eth.contract(address=mp_address, abi=abi)

    candidates = [
        (Web3.to_checksum_address("0xf035cc0dd8f31af8db93ed7451788bf431859710"), "Agent Instance (0xf035)"),
        (Web3.to_checksum_address("0x552cEA7Bc33CbBEb9f1D90c1D11D2C6daefFd053"), "Triton Config (0x552c)"),
        (Web3.to_checksum_address("0x69C0669F3b5df0F2E2644F01098B4465f5652101"), "Service Multisig (0x69C0)"),
        (Web3.to_checksum_address("0xEB2A22b27C7Ad5eeE424Fd90b376c745E60f914E"), "Service Owner (0xEB2A)"),
    ]

    print(f"Marketplace: {mp_address}")

    print("--- Available Functions ---")
    fns = [f.fn_name for f in contract.all_functions()]
    print(fns)

    if "mapMechStaking" in fns:
        print("✅ mapMechStaking IS available.")
    else:
        print("❌ mapMechStaking is NOT available.")

    # Check mapMechStaking(mech) -> address
    # If returns 0, not registered.

    print("\n--- Checking mapMechStaking ---")
    for mech, desc in candidates:
        try:
            staking_instance = contract.functions.mapMechStaking(mech).call()
            print(f"{desc}: Staking Instance = {staking_instance}")
            if staking_instance != "0x0000000000000000000000000000000000000000":
                print(f"✅ FOUND REGISTERED MECH: {desc}")
        except Exception as e:
            print(f"❌ {desc} mapMechStaking FAILED: {str(e)[:100]}")

    # Check mapMechFactories(factory) just in case
    # ...

if __name__ == "__main__":
    main()
