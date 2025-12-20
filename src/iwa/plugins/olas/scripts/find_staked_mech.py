#!/usr/bin/env python3
"""Find staked services on Gnosis fork."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from iwa.core.chain import ChainInterfaces
from iwa.plugins.olas.constants import OLAS_CONTRACTS, OLAS_TRADER_STAKING_CONTRACTS
from iwa.plugins.olas.contracts.staking import StakingContract
from iwa.plugins.olas.contracts.service import ServiceRegistryContract

def main():
    chain_name = "gnosis"
    chain = ChainInterfaces().gnosis
    contracts = OLAS_CONTRACTS.get(chain_name, {})
    registry_address = contracts.get("OLAS_SERVICE_REGISTRY")
    registry = ServiceRegistryContract(str(registry_address), chain_name=chain_name)

    known_mech = contracts.get("OLAS_MECH")
    print(f"Known Legacy Mech: {known_mech}")

    for name, address in OLAS_TRADER_STAKING_CONTRACTS["gnosis"].items():
        print(f"\nChecking Staking Contract: {name} ({address})")
        staking = StakingContract(str(address))

        try:
            service_ids = staking.get_service_ids()
            print(f"  Staked Service IDs: {service_ids}")

            for sid in service_ids:
                # Get service info
                info = registry.get_service(sid)
                if not info:
                    continue

                multisig = info["multisig"]

                from iwa.plugins.olas.contracts.mech_marketplace import MechMarketplaceContract
                mp_address = contracts.get("OLAS_MECH_MARKETPLACE")
                marketplace = MechMarketplaceContract(str(mp_address), chain_name=chain_name)

                try:
                    is_mech = marketplace.call("checkMech", str(multisig))
                    print(f"    Service {sid}: Multisig {multisig} | Market Registered: {is_mech}")

                    if is_mech:
                        print(f"    🌟 FOUND REGISTERED MECH! Service ID: {sid} in {name}")
                        print(f"       Multisig: {multisig}")
                        print(f"       Staking Contract: {address}")
                        return

                except Exception as e:
                     print(f"    Error checking mech status: {e}")

                if str(multisig).lower() == str(known_mech).lower():
                    print(f"    🌟 FOUND KNOWN MECH STAKED! Service ID: {sid} in {name}")
                    return

                # Maybe check if multisig is a contract code that looks like a Mech?
                # Hard to do quickly, but we can list them.

        except Exception as e:
            print(f"  Error checking {name}: {e}")

if __name__ == "__main__":
    main()
