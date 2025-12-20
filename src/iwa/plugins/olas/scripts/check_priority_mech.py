#!/usr/bin/env python3
"""Check priority mech registration."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from iwa.core.chain import ChainInterfaces
from iwa.plugins.olas.constants import OLAS_CONTRACTS
from iwa.plugins.olas.contracts.mech_marketplace import MechMarketplaceContract

def main():
    chain_name = "gnosis"
    chain = ChainInterfaces().gnosis

    contracts = OLAS_CONTRACTS.get(chain_name, {})
    # Marketplace v1.1.0
    mp_address = "0x735FAAb1c4Ec41128c367AFb5c3baC73509f70bB"
    print(f"Marketplace: {mp_address}")
    mp = MechMarketplaceContract(str(mp_address), chain_name=chain_name)

    # We only care about checking the specific Triton/Priority Mech config now
    mech_addr = "0x552cEA7Bc33CbBEb9f1D90c1D11D2C6daefFd053"
    mech_staking = "0x998dEFafD094817EF329f6dc79c703f1CF18bC90"
    mech_service_id = 975

    print(f"\nChecking Staking: {mech_staking}")

    # Check Code Size
    code = chain.web3.eth.get_code(mech_staking)
    print(f"Code Size: {len(code)} bytes")

    if len(code) == 0:
        print("❌ Staking contract has NO CODE. It does not exist on this fork.")
        return

    # Candidates from getServiceInfo(975)
    from web3 import Web3
    candidates = [
        Web3.to_checksum_address("0xf035cc0dd8f31af8db93ed7451788bf431859710"), # Agent Instance (Found via Registry)
        Web3.to_checksum_address("0x552cEA7Bc33CbBEb9f1D90c1D11D2C6daefFd053"), # Original
        Web3.to_checksum_address("0x69C0669F3b5df0F2E2644F01098B4465f5652101"), # Candidate 1 (Owner?)
        Web3.to_checksum_address("0xEB2A22b27C7Ad5eeE424Fd90b376c745E60f914E"), # Candidate 2 (Multisig?)
    ]

    for mech_addr in candidates:
        print(f"\nChecking Candidate: {mech_addr}")
        try:
            result = mp.call("checkMech", mech_addr, mech_staking, mech_service_id)
            print(f"  Result: {result}")

            if result != "0x0000000000000000000000000000000000000000":
                 print("  ✅ VALID VALID VALID!")
                 print(f"  >>> Use this Mech: {mech_addr}")
                 break
            else:
                 print("  ❌ Zero Address.")

        except Exception as e:
            print(f"  Error: {e}")
    print(f"  Staking: {mech_staking}")
    print(f"  Service ID: {mech_service_id}")

    try:
        # checkMech(address mech, address mechStakingInstance, uint256 mechServiceId)
        # We need to pass args positionally or verify `call` handles kwargs?
        # MechMarketplaceContract.call usually expects method name and *args.

        result = mp.call("checkMech", mech_addr, mech_staking, mech_service_id)
        print(f"  checkMech Result (Multisig): {result}")

        if result == "0x0000000000000000000000000000000000000000":
             print("  ❌ Mech is NOT valid with these params.")
        else:
             print("  ✅ Mech IS valid.")

    except Exception as e:
        print(f"  Error checking mech: {e}")

if __name__ == "__main__":
    main()
