#!/usr/bin/env python3
"""Test all 3 mech request flows: Legacy, MM v1, MM v2.

This script verifies that mech requests are correctly counted by the
activity checker for each type of staking contract.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from iwa.core.types import EthereumAddress
from iwa.core.wallet import Wallet
from iwa.plugins.olas.contracts.staking import StakingContract
from iwa.plugins.olas.service_manager import ServiceManager


# Test contracts - one of each type
TEST_CONTRACTS = {
    "legacy": {
        "name": "Expert 2 Legacy",
        "address": "0xb964e44c126410df341ae04B13aB10A985fE3513",
        "expected_marketplace": None,
    },
    "mm_v1": {
        "name": "Expert 17 MM v1 (trader_ant)",
        "address": "0x1430107A785C3A36a0C1FC0ee09B9631e2E72aFf",
        "expected_marketplace": "0x4554fE75c1f5576c1d7F765B2A036c199Adae329",
    },
    "mm_v2": {
        "name": "Expert 5 MM v2",
        "address": "0xcdC603e0Ee55Aae92519f9770f214b2Be4967f7d",
        "expected_marketplace": "0x735FAAb1c4Ec41128c367AFb5c3baC73509f70bB",
    },
}


def test_staking_contract(contract_type: str, wallet: Wallet) -> bool:
    """Test a single staking contract type."""
    config = TEST_CONTRACTS[contract_type]
    staking_addr = config["address"]

    print(f"\n{'='*70}")
    print(f"  Testing: {config['name']}")
    print(f"  Type: {contract_type.upper()}")
    print(f"  Address: {staking_addr}")
    print(f"{'='*70}")

    # 1. Get staking contract info
    print("\n[1] Loading staking contract...")
    staking = StakingContract(staking_addr, chain_name="gnosis")
    checker = staking.activity_checker

    marketplace = checker.mech_marketplace if hasattr(checker, 'mech_marketplace') else None
    if marketplace:
        marketplace = EthereumAddress(marketplace)

    expected = config["expected_marketplace"]
    if expected:
        expected = EthereumAddress(expected)

    if marketplace and expected:
        if marketplace.lower() != expected.lower():
            print(f"  ❌ FAIL: Marketplace mismatch!")
            print(f"     Expected: {expected}")
            print(f"     Got: {marketplace}")
            return False
        print(f"  ✅ Marketplace: {marketplace[:20]}... (as expected)")
    elif not marketplace and not expected:
        print(f"  ✅ No marketplace (Legacy mech)")
    else:
        print(f"  ❌ FAIL: Marketplace expectation mismatch")
        return False

    # 2. Get requirements
    print("\n[2] Getting staking requirements...")
    reqs = staking.get_requirements()
    required_bond = reqs["required_agent_bond"]
    staking_token = str(reqs["staking_token"])
    print(f"  Bond: {required_bond / 1e18:.0f} OLAS")

    # 3. Create service
    print("\n[3] Creating service...")
    manager = ServiceManager(wallet)
    service_id = manager.create(
        chain_name="gnosis",
        service_name=f"test_{contract_type}",
        token_address_or_tag=staking_token,
        bond_amount_wei=required_bond,
    )
    if not service_id:
        print("  ❌ FAIL: Create failed")
        return False
    print(f"  ✅ Service ID: {service_id}")

    # 4. Spin up & stake
    print("\n[4] Spinning up & staking...")
    success = manager.spin_up(
        bond_amount_wei=required_bond,
        staking_contract=staking,
    )
    if not success:
        print("  ❌ FAIL: Spin up failed")
        return False

    multisig = manager.service.multisig_address
    print(f"  ✅ Staked! Multisig: {multisig}")

    # Set staking contract address for get_marketplace_config
    manager.service.staking_contract_address = staking_addr

    # 5. Get initial count
    print("\n[5] Getting initial mech request count...")
    try:
        if contract_type == "legacy":
            # Legacy uses agentMech.getRequestsCount
            from iwa.plugins.olas.contracts.mech import MechContract
            mech = MechContract(
                "0x77af31De935740567Cf4fF1986D04B2c964A786a",
                chain_name="gnosis"
            )
            initial_count = mech.call("getRequestsCount", multisig)
        else:
            # MM uses activity checker's getMultisigNonces
            nonces = checker.get_multisig_nonces(multisig)
            initial_count = nonces[1]  # mech requests count
        print(f"  Initial count: {initial_count}")
    except Exception as e:
        print(f"  ⚠️ Could not get initial count: {e}")
        initial_count = 0

    # 6. Fund the Safe
    print("\n[6] Funding Safe with xDAI...")
    from iwa.core.chain.interface import ChainInterface
    chain = ChainInterface("gnosis")

    master = wallet.master_account.address
    success, tx_hash = wallet.send_native_transfer(
        from_address=master,
        to_address=multisig,
        value_wei=100_000_000_000_000_000,  # 0.1 xDAI
        chain_name="gnosis",
    )
    if success:
        balance = chain.web3.eth.get_balance(multisig)
        print(f"  ✅ Funded! Balance: {balance / 1e18:.4f} xDAI")
    else:
        print("  ⚠️ Could not fund Safe, continuing anyway...")

    # 7. Send mech request
    print("\n[7] Sending mech request...")
    import os
    data = os.urandom(32)

    tx_hash = manager.send_mech_request(data=data)
    if not tx_hash:
        print("  ❌ FAIL: send_mech_request returned None")
        return False
    print(f"  ✅ Tx hash: {tx_hash}")

    # 8. Verify count increased
    print("\n[8] Verifying mech request was counted...")
    try:
        if contract_type == "legacy":
            final_count = mech.call("getRequestsCount", multisig)
        else:
            nonces = checker.get_multisig_nonces(multisig)
            final_count = nonces[1]

        print(f"  Before: {initial_count}")
        print(f"  After:  {final_count}")

        if final_count > initial_count:
            print(f"  ✅ SUCCESS: Activity checker counted the request!")
            return True
        else:
            print(f"  ❌ FAIL: Request was NOT counted")
            return False
    except Exception as e:
        print(f"  ⚠️ Could not verify: {e}")
        return False


def main():
    """Run tests for all 3 contract types."""
    print("=" * 70)
    print("  COMPREHENSIVE MECH REQUEST TEST")
    print("  Testing: Legacy, MM v1, MM v2")
    print("=" * 70)

    # Initialize wallet once
    print("\nInitializing wallet...")
    wallet = Wallet()
    print(f"  Master: {wallet.master_account.address}")

    results = {}

    for contract_type in ["legacy", "mm_v1", "mm_v2"]:
        try:
            results[contract_type] = test_staking_contract(contract_type, wallet)
        except Exception as e:
            print(f"\n❌ Error testing {contract_type}: {e}")
            import traceback
            traceback.print_exc()
            results[contract_type] = False

    # Summary
    print("\n" + "=" * 70)
    print("  SUMMARY")
    print("=" * 70)

    all_passed = True
    for ct, passed in results.items():
        status = "✅ PASSED" if passed else "❌ FAILED"
        print(f"  {ct.upper():10} : {status}")
        if not passed:
            all_passed = False

    print("=" * 70)
    if all_passed:
        print("  🎉 ALL TESTS PASSED!")
    else:
        print("  ⚠️ SOME TESTS FAILED")
    print("=" * 70)

    return all_passed


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
