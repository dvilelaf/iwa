#!/usr/bin/env python3
"""Create a service with correct bond and stake it in Expert 7 MM contract.

This script demonstrates the minimum steps to:
1. Get the required bond amount from the staking contract
2. Create a service with that bond (NOT 1 wei)
3. Spin up the service (activate → register → deploy)
4. Stake the service in the staking contract

IMPORTANT: The service MUST be created with the correct bond amount
specified by the staking contract. Creating with bond=1 wei will
cause staking to fail because the on-chain bond won't match requirements.
"""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from iwa.core.wallet import Wallet
from iwa.plugins.olas.constants import OLAS_TRADER_STAKING_CONTRACTS
from iwa.plugins.olas.contracts.staking import StakingContract
from iwa.plugins.olas.service_manager import ServiceManager


def main():
    """Create and stake a service in Expert 7 MM contract."""
    print("=" * 60)
    print("  Create & Stake Service - Expert 7 MM (10k OLAS)")
    print("=" * 60)

    # 1. Initialize wallet
    print("\n[1] Initializing Wallet...")
    wallet = Wallet()
    master_address = wallet.master_account.address if wallet.master_account else "N/A"
    print(f"  OK: Master account: {master_address}")

    # 2. Get the staking contract
    print("\n[2] Loading staking contract...")
    staking_address = OLAS_TRADER_STAKING_CONTRACTS["gnosis"]["Expert 7 MM (10k OLAS)"]
    staking_contract = StakingContract(staking_address, chain_name="gnosis")
    print(f"  OK: Staking contract: {staking_address}")

    # 3. Get the required bond amount from the staking contract
    print("\n[3] Getting staking requirements...")
    requirements = staking_contract.get_requirements()
    required_bond = requirements["required_agent_bond"]
    min_deposit = requirements["min_staking_deposit"]
    staking_token = str(requirements["staking_token"])
    print(f"  - Required agent bond: {required_bond} wei")
    print(f"  - Min staking deposit: {min_deposit} wei")
    print(f"  - Staking token: {staking_token}")

    # 4. Create service with the correct bond amount
    print("\n[4] Creating Service with correct bond...")
    manager = ServiceManager(wallet)
    service_id = manager.create(
        chain_name="gnosis",
        service_name="staked_service_7mm",
        token_address_or_tag=staking_token,  # Use OLAS token
        bond_amount_wei=required_bond,  # THIS IS THE KEY: use required bond, not 1 wei
    )

    if not service_id:
        print("  FAIL: Failed to create service")
        return False

    print(f"  OK: Service created with ID: {service_id}")

    # 5. Spin up the service (activate -> register -> deploy -> stake)
    print("\n[5] Spinning up and staking Service...")
    success = manager.spin_up(
        bond_amount_wei=required_bond,
        staking_contract=staking_contract,  # spin_up handles staking automatically
    )
    if not success:
        print("  FAIL: Failed to spin up/stake service")
        return False

    print("  OK: Service deployed and staked!")
    print(f"     - Agent: {manager.service.agent_address}")
    print(f"     - Multisig: {manager.service.multisig_address}")

    print("\n" + "=" * 60)
    print("  SUCCESS: Service created and staked!")
    print("=" * 60)
    print(f"\nService ID: {service_id}")
    print("Staking Contract: Expert 7 MM (10k OLAS)")
    print(f"Contract Address: {staking_address}")
    return True


if __name__ == "__main__":
    try:
        success = main()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
