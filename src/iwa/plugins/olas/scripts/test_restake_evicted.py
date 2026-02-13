#!/usr/bin/env python3
"""Test restaking an evicted service WITHOUT terminate.

Flow: EVICTED → unstake() → DEPLOYED/NOT_STAKED → stake() → STAKED

This script tests on a Tenderly fork that trader_gamma (service 1384)
can be restaked on the same staking contract after eviction, without
needing to terminate/recreate the service.

Prerequisites:
    - data/config.yaml with trader_gamma (gnosis:1384) active
    - data/wallet.json with the service owner keys
    - secrets.env with testing=true and Tenderly credentials
    - Run `uv run -m iwa.tools.reset_tenderly` first to get fresh fork state
"""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from iwa.core.contracts.cache import ContractCache
from iwa.core.wallet import Wallet
from iwa.plugins.olas.contracts.staking import StakingContract, StakingState
from iwa.plugins.olas.service_manager import ServiceManager


SERVICE_KEY = "gnosis:1384"
STAKING_CONTRACT_ADDRESS = "0xD7A3C8b975f71030135f1a66e9e23164d54fF455"


def main() -> bool:
    """Test restaking an evicted service."""
    print("=" * 60)
    print("  Restake Evicted Service Test (Tenderly)")
    print("  Service: trader_gamma (gnosis:1384)")
    print("  Contract: Expert 7 Legacy")
    print("=" * 60)

    # 1. Initialize
    print("\n1. Initializing Wallet and ServiceManager...")
    wallet = Wallet()
    manager = ServiceManager(wallet, service_key=SERVICE_KEY)

    if not manager.service:
        print(f"  FAIL: Service {SERVICE_KEY} not found in config")
        return False

    print(f"  Service: {manager.service.service_name}")
    print(f"  Service ID: {manager.service.service_id}")
    print(f"  Owner EOA: {manager.service.service_owner_eoa_address}")
    print(f"  Multisig: {manager.service.multisig_address}")
    print(f"  Chain: {manager.chain_name}")

    # Check Tenderly connection
    if manager.chain_interface.is_tenderly:
        print("  OK: Connected to Tenderly fork")
    else:
        print("  WARNING: NOT connected to Tenderly! This will run on MAINNET!")
        confirm = input("  Continue anyway? [y/N] ").lower()
        if confirm != "y":
            print("  Aborted.")
            return False

    # 2. Load staking contract
    print("\n2. Loading staking contract...")
    staking_contract = ContractCache().get_contract(
        StakingContract,
        STAKING_CONTRACT_ADDRESS,
        chain_name=manager.chain_name,
    )
    print(f"  Contract: {staking_contract.address}")

    # 3. Check current staking state
    print("\n3. Checking current staking state...")
    staking_state = staking_contract.get_staking_state(manager.service.service_id)
    print(f"  Staking state: {staking_state.name}")

    if staking_state == StakingState.STAKED:
        print("  Service is already STAKED. Nothing to do.")
        return True

    if staking_state == StakingState.NOT_STAKED:
        print("  Service is NOT_STAKED. Skipping unstake, going straight to stake.")
    elif staking_state == StakingState.EVICTED:
        print("  OK: Service is EVICTED. Proceeding with unstake...")
    else:
        print(f"  FAIL: Unexpected state: {staking_state}")
        return False

    # 4. Check service registry state
    print("\n4. Checking service registry state...")
    service_state = manager.get_service_state(force_refresh=True)
    print(f"  Service state: {service_state}")

    # 5. Unstake (if EVICTED)
    if staking_state == StakingState.EVICTED:
        print("\n5. Unstaking evicted service...")
        success = manager.unstake(staking_contract)
        if not success:
            print("  FAIL: Unstake failed")
            return False
        print("  OK: Unstake successful")

        # Verify state after unstake
        new_staking_state = staking_contract.get_staking_state(manager.service.service_id)
        print(f"  New staking state: {new_staking_state.name}")

        new_service_state = manager.get_service_state(force_refresh=True)
        print(f"  New service state: {new_service_state}")
    else:
        print("\n5. Skipping unstake (already NOT_STAKED)")

    # 6. Stake on the same contract
    print("\n6. Staking on the same contract...")
    success = manager.stake(staking_contract)
    if not success:
        print("  FAIL: Stake failed")
        return False
    print("  OK: Stake successful")

    # 7. Final verification
    print("\n7. Final verification...")
    final_state = staking_contract.get_staking_state(manager.service.service_id)
    print(f"  Final staking state: {final_state.name}")

    final_service_state = manager.get_service_state(force_refresh=True)
    print(f"  Final service state: {final_service_state}")

    if final_state == StakingState.STAKED:
        print("\n" + "=" * 60)
        print("  SUCCESS! Service restaked without terminate!")
        print("=" * 60)
        return True
    else:
        print(f"\n  FAIL: Expected STAKED but got {final_state.name}")
        return False


if __name__ == "__main__":
    try:
        success = main()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
