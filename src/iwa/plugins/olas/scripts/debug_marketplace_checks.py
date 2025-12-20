#!/usr/bin/env python3
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from iwa.core.chain import ChainInterfaces
from iwa.core.wallet import Wallet
from iwa.plugins.olas.service_manager import ServiceManager
from iwa.plugins.olas.contracts.mech_marketplace import MechMarketplaceContract
from web3 import Web3

def main():
    wallet = Wallet()
    manager = ServiceManager(wallet)
    chain = ChainInterfaces().gnosis
    multisig_address = manager.service.multisig_address

    mp_address = "0x735FAAb1c4Ec41128c367AFb5c3baC73509f70bB"
    mp = MechMarketplaceContract(str(mp_address), chain_name="gnosis")

    # Priority Mech Params
    mech = Web3.to_checksum_address("0xf035cc0dd8f31af8db93ed7451788bf431859710")
    mech_staking = "0x998dEFafD094817EF329f6dc79c703f1CF18bC90"
    mech_service_id = 975

    # Requester Params (My Service)
    # Using values from previous logs/ServiceManager state
    # Wait, ServiceManager might have dynamic values.
    # But for now use what was in simulation.
    requester_staking = "0x389B46c259631Acd6a69Bde8B6cEe218230bAE8C"
    requester_service_id = 2593
    requester_multisig = multisig_address # 0xf31...

    print(f"Marketplace: {mp_address}")

    print("\n--- Checking Mech Validity (checkMech) ---")
    try:
        # checkMech(address mech, address mechStakingInstance, uint256 mechServiceId)
        # It's a view function.
        # Construct call manually or use contract args if bound?
        # Using web3 raw call to be sure.
        # Function selector: checkMech(address,address,uint256) -> 0x...
        # But let's use the ABI if available. mp.contract has it.

        # Note: abi "checkMech" might be missing if I didn't update the contract instance?
        # But I updated mech_marketplace.json on disk.
        # MechMarketplaceContract loads it from disk.

        res = mp.contract.functions.checkMech(mech, mech_staking, mech_service_id).call()
        print(f"✅ checkMech PASSED! Result: {res}")
    except Exception as e:
        print(f"❌ checkMech FAILED: {e}")

    print("\n--- Checking Requester Validity (checkRequester) ---")
    try:
        # checkRequester(address requester, address requesterStakingInstance, uint256 requesterServiceId)
        # It IS a view function in the ABI I saw.
        res = mp.contract.functions.checkRequester(requester_multisig, requester_staking, requester_service_id).call()
        print(f"✅ checkRequester PASSED! Result: {res}")
    except Exception as e:
        print(f"❌ checkRequester FAILED: {e}")

if __name__ == "__main__":
    main()
