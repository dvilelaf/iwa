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


def init_manager():
    """Initialize Wallet and ServiceManager."""
    wallet = Wallet()
    manager = ServiceManager(wallet, service_key=SERVICE_KEY)
    if not manager.service:
        print(f"  FAIL: Service {SERVICE_KEY} not found in config")
        return None
    print(f"  Service: {manager.service.service_name} (id={manager.service.service_id})")
    print(f"  Chain: {manager.chain_name}")
    if not manager.chain_interface.is_tenderly:
        print("  WARNING: NOT connected to Tenderly! This will run on MAINNET!")
        if input("  Continue anyway? [y/N] ").lower() != "y":
            return None
    else:
        print("  OK: Connected to Tenderly fork")
    return manager


def do_unstake(manager, staking_contract):
    """Unstake if EVICTED, skip if NOT_STAKED, abort otherwise."""
    state = staking_contract.get_staking_state(manager.service.service_id)
    print(f"  Staking state: {state.name}")
    if state == StakingState.STAKED:
        print("  Already STAKED. Nothing to do.")
        return True
    if state == StakingState.EVICTED:
        print("  Unstaking evicted service...")
        if not manager.unstake(staking_contract):
            print("  FAIL: Unstake failed")
            return False
        print("  OK: Unstake successful")
        return None  # proceed to stake
    if state == StakingState.NOT_STAKED:
        print("  Already NOT_STAKED, skipping unstake.")
        return None  # proceed to stake
    print(f"  FAIL: Unexpected state: {state}")
    return False


def main() -> bool:
    """Test restaking an evicted service."""
    print("=" * 60)
    print("  Restake Evicted Service Test (Tenderly)")
    print("=" * 60)

    print("\n1. Initializing...")
    manager = init_manager()
    if not manager:
        return False

    print("\n2. Loading staking contract...")
    staking_contract = ContractCache().get_contract(
        StakingContract, STAKING_CONTRACT_ADDRESS, chain_name=manager.chain_name,
    )

    print("\n3. Checking state & unstaking if needed...")
    result = do_unstake(manager, staking_contract)
    if result is True:
        return True
    if result is False:
        return False

    print("\n4. Staking on the same contract...")
    if not manager.stake(staking_contract):
        print("  FAIL: Stake failed")
        return False

    final = staking_contract.get_staking_state(manager.service.service_id)
    print(f"\n  Final state: {final.name}")
    if final == StakingState.STAKED:
        print("  SUCCESS! Service restaked without terminate!")
        return True
    print(f"  FAIL: Expected STAKED but got {final.name}")
    return False


if __name__ == "__main__":
    try:
        sys.exit(0 if main() else 1)
    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
