#!/usr/bin/env python3
"""Inspect Mech Marketplace parameters."""

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
    mp_address = contracts.get("OLAS_MECH_MARKETPLACE")

    print(f"Marketplace Address: {mp_address}")

    mp = MechMarketplaceContract(str(mp_address), chain_name=chain_name)

    try:
        print("Available functions:")
        for func in mp.contract.all_functions():
             print(f" - {func.fn_name}")

        price = mp.call("price")
        print(f"Price: {price} wei ({price/1e18} xDAI)")
    except Exception as e:
        print(f"Error fetching price: {e}")

    try:
        min_timeout = mp.call("minResponseTimeout")
        print(f"Min Response Timeout: {min_timeout}")
    except Exception as e:
        print(f"Error fetching min timeout: {e}")

    try:
        max_timeout = mp.call("maxResponseTimeout")
        print(f"Max Response Timeout: {max_timeout}")
    except Exception as e:
        print(f"Error fetching max timeout: {e}")

if __name__ == "__main__":
    main()
