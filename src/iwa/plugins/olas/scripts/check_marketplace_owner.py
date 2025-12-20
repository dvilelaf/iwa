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
    contracts = OLAS_CONTRACTS.get(chain_name, {})
    mp_address = contracts.get("OLAS_MECH_MARKETPLACE")

    # Try owner()
    try:
        # Manually using web3 call as MechMarketplaceContract might not have owner() in ABI explicitly loaded if I didn't add it?
        # But I copied the ABI, it has owner().

        # Or I can use raw call
        # owner() selector: 0x8da5cb5b
        ret = chain.web3.eth.call({
            "to": str(mp_address),
            "data": "0x8da5cb5b"
        })
        owner = "0x" + ret.hex()[-40:]
        print(f"Owner: {chain.web3.to_checksum_address(owner)}")

    except Exception as e:
        print(f"Failed to get owner: {e}")

if __name__ == "__main__":
    main()
