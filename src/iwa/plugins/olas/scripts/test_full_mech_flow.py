#!/usr/bin/env python3
"""Integration test: Create service, send legacy mech request, send marketplace mech request.

This script tests the full mech request flow on a Tenderly fork:
1. Creates a new OLAS service (or uses existing one)
2. Spins up the service
3. Sends a legacy mech request and verifies the Request event
4. Sends a marketplace mech request and verifies the MarketplaceRequest event
"""

import sys
from pathlib import Path

# Add src to path (scripts are in src/iwa/plugins/olas/scripts/)
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from iwa.core.chain import ChainInterfaces
from iwa.core.wallet import Wallet
from iwa.plugins.olas.constants import OLAS_CONTRACTS
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


def print_error(msg: str):
    """Print error message."""
    print(f"  ❌ {msg}")


def verify_mech_event(chain, tx_hash, contract, expected_event_name, multisig_address):
    """Verify mech request event in transaction receipt."""
    print_info("Fetching transaction receipt...")
    receipt = chain.web3.eth.wait_for_transaction_receipt(tx_hash)

    print_info(f"Extracting events (expecting '{expected_event_name}')...")
    events = contract.extract_events(receipt)

    request_event = next((e for e in events if e["name"] == expected_event_name), None)

    if request_event:
        print_success(f"Found '{expected_event_name}' event!")
        print_info(f"Event Args: {request_event['args']}")
        args = request_event["args"]

        # Verify requester/sender matches multisig
        requester_key = "requester" if expected_event_name == "MarketplaceRequest" else "sender"
        event_requester = args.get(requester_key)
        if event_requester and event_requester.lower() == multisig_address.lower():
            print_success(f"Event {requester_key} matches multisig address")
        else:
            print_error(
                f"Event {requester_key} ({event_requester}) does not match multisig ({multisig_address})"
            )
            return False
        return True
    else:
        print_error(f"'{expected_event_name}' event not found in transaction logs")
        print_info(f"Found events: {[e['name'] for e in events]}")
        return False


def main():  # noqa: C901
    """Run full mech flow integration test: create -> spin_up -> legacy request -> marketplace request."""
    print("=" * 60)
    print("  OLAS Mech Request Integration Test")
    print("=" * 60)

    # Initialize wallet
    print_step("Initializing Wallet", "🔐")
    wallet = Wallet()
    print_success(f"Master account: {wallet.master_account.address}")

    chain = ChainInterfaces().gnosis

    # Check master balance
    master_balance = chain.get_native_balance_eth(wallet.master_account.address)
    print_info(f"Master xDAI Balance: {master_balance}")

    # Step 1: Create/Load Service
    print_step("Step 1: Create Service", "1️⃣")
    manager = ServiceManager(wallet)

    # Check if service already exists
    if manager.service and manager.service.multisig_address:
        print_info(f"Using existing service ID: {manager.service.service_id}")
        print_info(f"Multisig: {manager.service.multisig_address}")
    else:
        service_id = manager.create(
            chain_name="gnosis",
            service_name="mech_test_service",
        )

        if not service_id:
            print_error("Failed to create service")
            return False

        print_success(f"Service created with ID: {service_id}")

        # Step 2: Spin up Service
        print_step("Step 2: Spin up Service", "2️⃣")
        success = manager.spin_up()
        if not success:
            print_error("Failed to spin up service")
            return False

        print_success("Service deployed!")

    print_info(f"Service ID: {manager.service.service_id}")
    print_info(f"Agent: {manager.service.agent_address}")
    print_info(f"Multisig: {manager.service.multisig_address}")

    multisig_address = manager.service.multisig_address
    agent_address = manager.service.agent_address

    # Fund multisig and agent if needed
    multisig_balance = chain.get_native_balance_eth(multisig_address)
    agent_balance = chain.get_native_balance_eth(agent_address)
    print_info(f"Multisig xDAI Balance: {multisig_balance}")
    print_info(f"Agent xDAI Balance: {agent_balance}")

    required_payment = 0.05
    if float(multisig_balance) < required_payment:
        print_step("Funding Multisig", "💰")
        success, tx = chain.send_native_transfer(
            from_address=wallet.master_account.address,
            to_address=multisig_address,
            value_wei=int(required_payment * 2 * 1e18),
            sign_callback=lambda tx: wallet.key_storage.sign_transaction(
                tx, wallet.master_account.address
            ),
        )
        if success:
            print_success(f"Funded multisig: {tx}")
        else:
            print_error("Failed to fund multisig")
            return False

    required_gas = 0.1
    if float(agent_balance) < required_gas:
        print_step("Funding Agent", "⛽")
        success, tx = chain.send_native_transfer(
            from_address=wallet.master_account.address,
            to_address=agent_address,
            value_wei=int(required_gas * 1e18),
            sign_callback=lambda tx: wallet.key_storage.sign_transaction(
                tx, wallet.master_account.address
            ),
        )
        if success:
            print_success(f"Funded agent: {tx}")
        else:
            print_error("Failed to fund agent")
            return False

    # Dummy request data
    dummy_data = b"test_request_data_12345"
    payment_wei = int(0.01 * 1e18)

    # Get contract addresses
    protocol_contracts = OLAS_CONTRACTS.get("gnosis", {})
    legacy_mech_address = protocol_contracts.get("OLAS_MECH")
    marketplace_address = protocol_contracts.get("OLAS_MECH_MARKETPLACE")

    # Step 3: Send Legacy Mech Request
    print_step("Step 3: Send Legacy Mech Request", "3️⃣")
    from iwa.plugins.olas.contracts.mech import MechContract

    tx_hash_legacy = manager.send_mech_request(
        data=dummy_data,
        value=payment_wei,
        use_marketplace=False,
        mech_address=str(legacy_mech_address),
    )

    if not tx_hash_legacy:
        print_error("Failed to send legacy mech request")
        return False

    print_success(f"Legacy mech request sent: {tx_hash_legacy}")

    # Verify legacy event
    print_step("Step 3b: Verify Legacy Mech Event", "✅")
    legacy_mech = MechContract(str(legacy_mech_address), chain_name="gnosis")
    if not verify_mech_event(chain, tx_hash_legacy, legacy_mech, "Request", multisig_address):
        print_error("Legacy mech event verification failed")
        return False

    print_success("Legacy mech request verified!")

    # Step 4: Send Marketplace Mech Request
    print_step("Step 4: Send Marketplace Mech Request", "4️⃣")
    from iwa.plugins.olas.contracts.mech_marketplace import MechMarketplaceContract

    # Known registered mech on Gnosis marketplace
    priority_mech = "0x601024E27f1C67B28209E24272CED8A31fc8151F"

    # API uses smart defaults:
    # - max_delivery_rate defaults to value
    # - payment_type defaults to NATIVE
    tx_hash_marketplace = manager.send_mech_request(
        data=dummy_data,
        value=payment_wei,
        use_marketplace=True,
        priority_mech=priority_mech,
    )

    if not tx_hash_marketplace:
        print_error("Failed to send marketplace mech request")
        return False

    print_success(f"Marketplace mech request sent: {tx_hash_marketplace}")

    # Verify marketplace event
    print_step("Step 4b: Verify Marketplace Mech Event", "✅")
    marketplace = MechMarketplaceContract(str(marketplace_address), chain_name="gnosis")
    if not verify_mech_event(
        chain, tx_hash_marketplace, marketplace, "MarketplaceRequest", multisig_address
    ):
        print_error("Marketplace mech event verification failed")
        return False

    print_success("Marketplace mech request verified!")

    # Summary
    print("\n" + "=" * 60)
    print("  🎉 All Mech Requests Completed Successfully!")
    print("=" * 60)
    print(f"  Service ID: {manager.service.service_id}")
    print(f"  Legacy Mech Tx: {tx_hash_legacy}")
    print(f"  Marketplace Mech Tx: {tx_hash_marketplace}")
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
