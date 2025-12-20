#!/usr/bin/env python3
import sys
import json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from iwa.core.chain import ChainInterfaces
from web3 import Web3

def main():
    chain = ChainInterfaces().gnosis
    staking_address = "0x998dEFafD094817EF329f6dc79c703f1CF18bC90"

    # Load ABI
    abi_path = Path(__file__).parent.parent / "contracts" / "abis" / "staking_token.json"
    with open(abi_path, 'r') as f:
        abi = json.load(f)
        if "abi" in abi:
            abi = abi["abi"]

    print(f"Checking Staking Contract: {staking_address}")
    contract = chain.web3.eth.contract(address=staking_address, abi=abi)

    try:
        # Check basic views
        ids = contract.functions.getServiceIds().call()
        print(f"Service IDs on {staking_address}: {ids}")

        staked_service = None

        if 975 in ids:
            print("✅ Service 975 FOUND.")
            info = contract.functions.getServiceInfo(975).call()
            print(f"Service 975 Info: {info}")
            state = contract.functions.getStakingState(975).call()
            print(f"Staking State 975 (1=Staked): {state}")
            if state == 1:
                staked_service = 975
        else:
            print("❌ Service 975 NOT FOUND.")

        # If 975 is not staked, find one that is
        if not staked_service:
            print("Scanning for STAKED services...")
            for sid in ids:
                state = contract.functions.getStakingState(sid).call()
                if state == 1:
                    print(f"  >>> FOUND STAKED SERVICE: {sid}")
                    staked_service = sid
                    info = contract.functions.getServiceInfo(sid).call()
                    print(f"  Info: {info}")
                    break

        if staked_service:
            print(f"\nTargeting Staked Service ID: {staked_service}")
            # Get multisig from info[0] or info[1] based on debug output
            # Previous output: ('0x69C0...'(owner?), '0xEB2A...'(multisig?))
             # ABI: getServiceInfo -> (multisig, owner, ...)
             # So info[0] = multisig!
            multisig_addr = contract.functions.getServiceInfo(staked_service).call()[0]
            print(f"Multisig Address: {multisig_addr}")

    except Exception as e:
        print(f"Error calling staking contract: {e}")

if __name__ == "__main__":
    main()
