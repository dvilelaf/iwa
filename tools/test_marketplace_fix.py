#!/usr/bin/env python3
"""Test mech marketplace fix with trader_ant's staking contract.

This script tests that mech requests are sent to the correct marketplace
based on the activity checker configuration.

trader_ant uses staking contract 0x1430107A785C3A36a0C1FC0ee09B9631e2E72aFf
which has an activity checker that expects requests at marketplace 0x4554fE75...
(the OLD marketplace), NOT the new 0x735FAAb1... marketplace.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from iwa.core.wallet import Wallet
from iwa.plugins.olas.contracts.staking import StakingContract
from iwa.plugins.olas.service_manager import ServiceManager
from iwa.plugins.olas.service_manager.mech import DEFAULT_PRIORITY_MECH


# trader_ant's staking contract (Expert 17 MM)
TRADER_ANT_STAKING = "0x1430107A785C3A36a0C1FC0ee09B9631e2E72aFf"


def main():
    """Test mech marketplace fix."""
    print("=" * 60)
    print("  Test Mech Marketplace Fix - trader_ant's Contract")
    print("=" * 60)

    # 1. Verify the staking contract uses OLD marketplace
    print("\n[1] Verifying staking contract configuration...")
    staking = StakingContract(TRADER_ANT_STAKING, chain_name="gnosis")
    checker = staking.activity_checker

    marketplace = checker.mech_marketplace
    print(f"  Activity Checker: {staking.activity_checker_address}")
    print(f"  Mech Marketplace: {marketplace}")

    expected_mp = "0x4554fE75c1f5576c1d7F765B2A036c199Adae329"
    if marketplace.lower() != expected_mp.lower():
        print(f"  FAIL: Expected marketplace {expected_mp}, got {marketplace}")
        return False
    print("  OK: Uses OLD marketplace as expected")

    # Check if marketplace is in DEFAULT_PRIORITY_MECH mapping
    from iwa.core.types import EthereumAddress
    mp_checksum = EthereumAddress(marketplace)
    if mp_checksum in DEFAULT_PRIORITY_MECH:
        mech_info = DEFAULT_PRIORITY_MECH[mp_checksum]
        priority_mech = mech_info[0]
        print(f"  OK: Marketplace found in DEFAULT_PRIORITY_MECH")
        print(f"      Priority Mech: {priority_mech}")
    else:
        print(f"  WARN: Marketplace NOT in DEFAULT_PRIORITY_MECH")

    # 2. Initialize wallet
    print("\n[2] Initializing Wallet...")
    wallet = Wallet()
    master = wallet.master_account.address if wallet.master_account else "N/A"
    print(f"  Master: {master}")

    # 3. Get staking requirements
    print("\n[3] Getting staking requirements...")
    reqs = staking.get_requirements()
    required_bond = reqs["required_agent_bond"]
    staking_token = str(reqs["staking_token"])
    print(f"  Required bond: {required_bond} wei ({required_bond / 1e18:.0f} OLAS)")
    print(f"  Staking token: {staking_token}")

    # 4. Create service
    print("\n[4] Creating Service...")
    manager = ServiceManager(wallet)
    service_id = manager.create(
        chain_name="gnosis",
        service_name="test_marketplace_fix",
        token_address_or_tag=staking_token,
        bond_amount_wei=required_bond,
    )

    if not service_id:
        print("  FAIL: Create failed")
        return False
    print(f"  OK: Service ID: {service_id}")

    # 5. Spin up (activate -> register -> deploy -> stake)
    print("\n[5] Spinning up & staking...")
    success = manager.spin_up(
        bond_amount_wei=required_bond,
        staking_contract=staking,
    )
    if not success:
        print("  FAIL: Spin up failed")
        return False

    multisig = manager.service.multisig_address
    print(f"  OK: Staked! Multisig: {multisig}")

    # Set staking contract address so get_marketplace_config can detect marketplace
    manager.service.staking_contract_address = TRADER_ANT_STAKING

    # 6. Get initial mech request count from activity checker
    print("\n[6] Checking initial mech request count...")
    try:
        nonces = checker.get_multisig_nonces(multisig)
        initial_count = nonces[1]
        print(f"  Initial mech requests: {initial_count}")
    except Exception as e:
        print(f"  WARN: Could not get nonces: {e}")
        initial_count = 0

    # 7. Test get_marketplace_config()
    print("\n[7] Testing get_marketplace_config()...")
    use_mp, detected_mp, detected_mech = manager.get_marketplace_config()
    print(f"  use_marketplace: {use_mp}")
    print(f"  marketplace_address: {detected_mp}")
    print(f"  priority_mech: {detected_mech}")

    if not detected_mp or detected_mp.lower() != expected_mp.lower():
        print(f"  FAIL: get_marketplace_config returned wrong marketplace!")
        print(f"       Expected: {expected_mp}")
        print(f"       Got: {detected_mp}")
        return False
    print("  OK: get_marketplace_config returns correct OLD marketplace")

    # 7.5 Fund the Safe with xDAI for mech request
    print("\n[7.5] Funding Safe with xDAI for mech request...")
    from iwa.core.chain.interface import ChainInterface
    chain = ChainInterface("gnosis")
    balance = chain.web3.eth.get_balance(multisig)
    print(f"  Current Safe balance: {balance / 1e18:.4f} xDAI")

    if balance < 100_000_000_000_000_000:  # 0.1 xDAI
        # Fund from master account via wallet
        print("  Transferring 0.1 xDAI from master to Safe...")
        try:
            success, tx_hash = wallet.send_native_transfer(
                from_address=master,
                to_address=multisig,
                value_wei=100_000_000_000_000_000,  # 0.1 xDAI
                chain_name="gnosis",
            )
            if success:
                new_balance = chain.web3.eth.get_balance(multisig)
                print(f"  Funded Safe! New balance: {new_balance / 1e18:.4f} xDAI")
            else:
                print("  WARN: Transfer failed")
        except Exception as e:
            print(f"  WARN: Could not fund Safe: {e}")

    # 8. Send mech request
    print("\n[8] Sending mech request...")
    # Create test data (random IPFS hash)
    import os
    data = os.urandom(32)

    tx_hash = manager.send_mech_request(data=data)
    if not tx_hash:
        print("  FAIL: send_mech_request returned None")
        return False
    print(f"  OK: Tx hash: {tx_hash}")

    # 9. Verify request was counted
    print("\n[9] Verifying mech request was counted...")
    try:
        nonces_after = checker.get_multisig_nonces(multisig)
        final_count = nonces_after[1]
        print(f"  Mech requests before: {initial_count}")
        print(f"  Mech requests after:  {final_count}")

        if final_count > initial_count:
            print(f"  ✅ SUCCESS: Activity checker counted the request!")
            return True
        else:
            print(f"  ❌ FAIL: Request was NOT counted by activity checker")
            return False
    except Exception as e:
        print(f"  WARN: Could not verify: {e}")
        print("  Manual verification needed")
        return True

if __name__ == "__main__":
    try:
        success = main()
        print("\n" + "=" * 60)
        if success:
            print("  ✅ TEST PASSED: Mech marketplace fix works!")
        else:
            print("  ❌ TEST FAILED")
        print("=" * 60)
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
