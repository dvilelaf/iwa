#!/usr/bin/env python3
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from iwa.core.chain import ChainInterfaces
from iwa.plugins.olas.constants import OLAS_CONTRACTS
from iwa.plugins.olas.contracts.mech_marketplace import MechMarketplaceContract

def main():
    chain_name = "gnosis"
    chain = ChainInterfaces().gnosis
    # Check both addresses
    addresses = {
        "New (0x735F)": "0x735FAAb1c4Ec41128c367AFb5c3baC73509f70bB",
        "Old (0x4554)": "0x4554fE75c1f5576c1d7F765B2A036c199Adae329"
    }

    for label, mp_address in addresses.items():
        print(f"\n--- Checking {label}: {mp_address} ---")

        # Check code
        code = chain.web3.eth.get_code(mp_address)
        if len(code) <= 2:
            print("  ❌ No code at this address!")
            continue
        else:
            print(f"  ✅ Code found ({len(code)} bytes)")

        mp = MechMarketplaceContract(str(mp_address), chain_name=chain_name)

        try:
            print("  Checking VERSION()...")
            version = mp.call("VERSION")
            print(f"  VERSION: {version}")
        except Exception as e:
            print(f"  VERSION failed: {e}")

        try:
            print("  Checking chainId()...")
            cid = mp.call("chainId")
            print(f"  chainId: {cid}")
        except Exception as e:
            print(f"  chainId failed: {e}")

if __name__ == "__main__":
    main()
