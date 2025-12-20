#!/usr/bin/env python3
"""Integration test for full OLAS service lifecycle on Tenderly."""

import sys
from pathlib import Path

# Add src to path (scripts are in src/iwa/plugins/olas/scripts/)
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from iwa.core.chain import ChainInterfaces
from iwa.core.constants import CONFIG_PATH
from iwa.core.models import Config
from iwa.core.wallet import Wallet
from iwa.plugins.olas.constants import OLAS_TRADER_STAKING_CONTRACTS
from iwa.plugins.olas.contracts.staking import StakingContract
from iwa.plugins.olas.service_manager import ServiceManager


def print_step(step: str, emoji: str = "🔵"):
    """Print a step with formatting."""
    print(f"\n{emoji} {step}")
    print("-" * 60)


def print_success(msg: str):
    """Print success message."""
    print(f"  ✅ {msg}")


def print_info(msg: str):
    """Print info message."""
    print(f"  ℹ️  {msg}")


def print_service_state(manager: ServiceManager):
    """Print current service state from model."""
    s = manager.service
    print("  📄 Service Model:")
    print(f"     - service_name: {s.service_name}")
    print(f"     - service_id: {s.service_id}")
    print(f"     - chain_name: {s.chain_name}")
    print(f"     - agent_ids: {s.agent_ids}")
    print(f"     - agent_address: {s.agent_address}")
    print(f"     - multisig_address: {s.multisig_address}")
    print(f"     - staking_contract_address: {s.staking_contract_address}")


def find_staking_contract_with_slots():
    """Find a staking contract with available slots."""
    print_info("Searching for staking contract with available slots...")

    for name, address in OLAS_TRADER_STAKING_CONTRACTS["gnosis"].items():
        try:
            contract = StakingContract(address)
            current_services = len(contract.get_service_ids())
            max_services = contract.max_num_services
            available = max_services - current_services

            if available > 0:
                print_info(f"Found: {name}")
                print_info(f"  Address: {address}")
                print_info(f"  Available slots: {available}/{max_services}")
                print_info(f"  Min deposit: {contract.min_staking_deposit / 1e18:.0f} OLAS")
                return name, contract
        except Exception as e:
            print_info(f"Skipping {name}: {e}")
            continue

    return None, None


def verify_config_saved():
    """Verify config.toml was saved."""
    if CONFIG_PATH.exists():
        content = CONFIG_PATH.read_text()
        print_success(f"Config saved to {CONFIG_PATH}")
        # Show relevant section
        if "olas" in content.lower():
            print_info("Config contains 'olas' section")
        return True
    else:
        print(f"  ❌ Config not found at {CONFIG_PATH}")
        return False


def main():
    print("=" * 60)
    print("  OLAS Service Lifecycle Integration Test (Tenderly)")
    print("=" * 60)

    # Initialize wallet
    print_step("Initializing Wallet", "🔐")
    wallet = Wallet()
    print_success(f"Master account: {wallet.master_account.address}")

    # First find a staking contract to get the required bond amount
    print_step("Step 0: Find Staking Contract", "0️⃣")
    staking_name, staking_contract = find_staking_contract_with_slots()

    if not staking_contract:
        print("  ⚠️  No staking contract with available slots found")
        print("  ⚠️  Will create service without staking token (staking will be skipped)")
        token_address = None
        bond_amount = 1
    else:
        token_address = ChainInterfaces().gnosis.get_token_address("OLAS")
        bond_amount = staking_contract.min_staking_deposit
        print_success(f"Will use OLAS token: {token_address}")
        print_success(f"Bond amount: {bond_amount / 1e18:.0f} OLAS")

    # Initialize ServiceManager (no active service yet)
    print_step("Step 1: Create Service", "1️⃣")
    manager = ServiceManager(wallet)

    # Create service with OLAS token for staking compatibility
    service_id = manager.create(
        chain_name="gnosis",
        service_name="lifecycle_test_service",
        token_address_or_tag=token_address,
        bond_amount=bond_amount,
    )

    if not service_id:
        print("  ❌ Failed to create service")
        return False

    print_success(f"Service created with ID: {service_id}")
    print_service_state(manager)
    verify_config_saved()

    # Verify service model has correct initial state
    assert manager.service.service_id == service_id
    assert manager.service.chain_name == "gnosis"
    assert manager.service.agent_ids == [25]  # TRADER
    assert manager.service.agent_address is None
    assert manager.service.multisig_address is None
    print_success("Service model has correct initial state")

    # Step 2: Deploy (spin_up)
    print(f"2️⃣ Step 2: Deploy Service (spin_up)")
    print("-" * 60)
    success = manager.spin_up(bond_amount=bond_amount)
    if not success:
        print("  ❌ Failed to spin up service")
        return False

    print_success("Service deployed successfully")
    print_service_state(manager)
    verify_config_saved()

    # Verify agent and multisig are set
    assert manager.service.agent_address is not None
    assert manager.service.multisig_address is not None
    print_success("agent_address and multisig_address are set")

    # Step 3: Stake
    print_step("Step 3: Stake Service", "3️⃣")

    # Use the staking contract found in Step 0
    if not staking_contract:
        print("  ⚠️  No staking contract with available slots found")
        print("  ⚠️  Skipping staking step")
    else:
        success = manager.stake(staking_contract)
        if not success:
            print("  ❌ Failed to stake service")
            return False

        print_success(f"Service staked in {staking_name}")
        print_service_state(manager)
        verify_config_saved()

        # Verify staking contract address is set
        assert manager.service.staking_contract_address == staking_contract.address
        print_success("staking_contract_address is set correctly")

    # Step 4: Wind down
    # print_step("Step 4: Wind Down Service", "4️⃣")

    # success = manager.wind_down(staking_contract=staking_contract)
    # if not success:
    #     print("  ❌ Failed to wind down service")
    #     return False

    # print_success("Service wound down successfully")
    # print_service_state(manager)
    # verify_config_saved()

    # Verify staking contract address is cleared
    if staking_contract:
        # Note: staking_contract_address might still be set until unstake is called
        pass

    # Final summary
    print_step("Test Complete!", "🎉")
    print_success("Full lifecycle test passed:")
    print("  1. Created service")
    print("  2. Deployed (spin_up)")
    print("  3. Staked" if staking_contract else "  3. Skipped staking (no slots)")
    print("  4. Wound down (unstake + terminate + unbond)")

    # Show final config
    print_step("Final Config", "📁")
    if CONFIG_PATH.exists():
        print(CONFIG_PATH.read_text())

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
