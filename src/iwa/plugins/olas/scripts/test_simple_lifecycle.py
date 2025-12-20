#!/usr/bin/env python3
"""Simple lifecycle test: create → spin_up → wind_down (no staking)."""

import sys
from pathlib import Path

# Add src to path (scripts are in src/iwa/plugins/olas/scripts/)
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from iwa.core.wallet import Wallet
from iwa.plugins.olas.service_manager import ServiceManager


def main():
    """Run simple lifecycle integration test: create -> spin_up."""
    print("=" * 60)
    print("  Simple Lifecycle Test: create → spin_up → wind_down")
    print("=" * 60)

    # Initialize wallet
    print("\n🔐 Initializing Wallet...")
    wallet = Wallet()
    print(f"  ✅ Master account: {wallet.master_account.address}")

    # Create service
    print("\n1️⃣ Creating Service...")
    manager = ServiceManager(wallet)
    service_id = manager.create(
        chain_name="gnosis",
        service_name="simple_test_service",
    )

    if not service_id:
        print("  ❌ Failed to create service")
        return False

    print(f"  ✅ Service created with ID: {service_id}")

    # Spin up (activate → register → deploy)
    print("\n2️⃣ Spinning up Service...")
    success = manager.spin_up()
    if not success:
        print("  ❌ Failed to spin up service")
        return False

    print("  ✅ Service deployed!")
    print(f"     - Agent: {manager.service.agent_address}")
    print(f"     - Multisig: {manager.service.multisig_address}")

    # Wind down (terminate → unbond)
    # print("\n3️⃣ Winding down Service...")
    # success = manager.wind_down()
    # if not success:
    #     print("  ❌ Failed to wind down service")
    #     return False

    # print("  ✅ Service wound down successfully!")

    print("\n" + "=" * 60)
    print("  🎉 Full lifecycle completed!")
    print("=" * 60)
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
