#!/usr/bin/env python3
"""Integration test for sending a Mech request from a Safe on Tenderly."""

import sys
from pathlib import Path

# Add src to path (scripts are in src/iwa/plugins/olas/scripts/)
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from iwa.core.chain import ChainInterfaces
from iwa.core.wallet import Wallet
from iwa.core.services.account import AccountService
from iwa.plugins.olas.service_manager import ServiceManager
from iwa.plugins.olas.constants import OLAS_CONTRACTS


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


def main():
    print("=" * 60)
    print("  OLAS Mech Request Integration Test (Tenderly)")
    print("=" * 60)

    # Initialize wallet
    print_step("Initializing Wallet", "🔐")
    wallet = Wallet()
    print_success(f"Master account: {wallet.master_account.address}")

    # Initialize ServiceManager (will load existing service config if available)
    print_step("Step 0: Load Service Manager", "0️⃣")
    manager = ServiceManager(wallet)

    if not manager.service or not manager.service.multisig_address:
        print("  ❌ No active service with multisig found. Run test_lifecycle_staked.py first.")
        return False

    service_id = manager.service.service_id
    multisig_address = manager.service.multisig_address
    agent_address = manager.service.agent_address

    print_info(f"Loaded Service ID: {service_id}")
    print_info(f"Multisig Address: {multisig_address}")
    print_info(f"Agent Address: {agent_address}")

    if not agent_address:
         print("  ❌ No agent address found in service config.")
         return False

    chain = ChainInterfaces().gnosis

    # Check XDAI balance of Multisig
    multisig_balance = chain.get_native_balance_eth(multisig_address)
    print_info(f"Multisig xDAI Balance: {multisig_balance}")

    # Check XDAI balance of Agent (Signer)
    agent_balance = chain.get_native_balance_eth(agent_address)
    print_info(f"Agent xDAI Balance: {agent_balance}")

    # Fund Multisig if needed (for payment)
    required_payment = 0.01
    if float(multisig_balance) < required_payment:
        print_step("Funding Multisig", "💰")
        print_info(f"Funding multisig with {required_payment:.4f} xDAI...")
        success, tx = chain.send_native_transfer(
            from_address=wallet.master_account.address,
            to_address=multisig_address,
            value_wei=int(required_payment * 1e18 * 2), # Fund a bit more
            sign_callback=lambda tx: wallet.key_storage.sign_transaction(tx, wallet.master_account.address)
        )
        if success:
             print_success(f"Funded multisig. Tx: {tx}")
        else:
             print("  ❌ Failed to fund multisig")
             return False

    # Fund Agent if needed (for gas)
    required_gas = 0.1
    if float(agent_balance) < required_gas:
        print_step("Funding Agent", "⛽")
        print_info(f"Funding agent with {required_gas:.4f} xDAI...")
        success, tx = chain.send_native_transfer(
             from_address=wallet.master_account.address,
             to_address=agent_address,
             value_wei=int(required_gas * 1e18),
             sign_callback=lambda tx: wallet.key_storage.sign_transaction(tx, wallet.master_account.address)
        )
        if success:
             print_success(f"Funded agent. Tx: {tx}")
        else:
             print("  ❌ Failed to fund agent")
             return False

    # Send Mech Request
    print_step("Step 1: Send Mech Request", "1️⃣")

    # Dummy IPFS hash (CID) for "Hello World"
    # bafybeigdyrzt5sfp7udm7hu76uh7y26nf3efuylqabf3oclgtqy55fbzdi
    # We use a bytes payload usually, but let's see what ServiceManager expects.
    # It expects 'data' bytes.
    dummy_data = b"dummy_ipfs_hash_or_request_data"

    # payment amount
    payment_wei = int(0.01 * 1e18)

    # User suggested Mech (ID 9)
    # 0x552cEA7Bc33CbBEb9f1D90c1D11D2C6daefFd053
    custom_priority_mech = "0x552cEA7Bc33CbBEb9f1D90c1D11D2C6daefFd053"

    tx_hash = manager.send_mech_request(
        data=dummy_data,
        value=payment_wei,
        use_marketplace=True,
        priority_mech=custom_priority_mech,
        # response_timeout=300
    )

    if not tx_hash:
        print("  ❌ Failed to send Mech request")

        # Try Debugging: Check if multisig is owner of itself? No.
        # Check if agent is owner of multisig.
        safe_service = wallet.safe_service
        owners = safe_service.get_owners(multisig_address, "gnosis")
        print_info(f"Multisig Owners: {owners}")
        if agent_address not in owners:
             print("  ❌ Agent is NOT an owner of the multisig!")
        else:
             print_success("Agent IS an owner of the multisig.")

        return False

    print_success(f"Mech request sent successfully! Tx Hash: {tx_hash}")

    # Verify event
    print_step("Step 2: Verify Mech Request Event", "2️⃣")
    try:
        from iwa.plugins.olas.contracts.mech import MechContract
        from iwa.plugins.olas.contracts.mech_marketplace import MechMarketplaceContract

        # We need the mech address used.
        protocol_contracts = OLAS_CONTRACTS.get(manager.service.chain_name, {})

        # Determine contract and event based on mode
        use_marketplace = True

        if use_marketplace:
            mp_address = protocol_contracts.get("OLAS_MECH_MARKETPLACE")
            contract = MechMarketplaceContract(str(mp_address), chain_name=manager.service.chain_name)
            expected_event_name = "MarketplaceRequest"
        else:
            mech_address = protocol_contracts.get("OLAS_MECH")
            contract = MechContract(str(mech_address), chain_name=manager.service.chain_name)
            expected_event_name = "Request"

        # Get receipt
        print_info("Fetching transaction receipt...")
        receipt = chain.web3.eth.wait_for_transaction_receipt(tx_hash)

        # Extract events
        print_info(f"Extracting events (expecting {expected_event_name})...")
        events = contract.extract_events(receipt)

        request_event = next((e for e in events if e["name"] == expected_event_name), None)

        if request_event:
            print_success(f"Found '{expected_event_name}' event!")
            print_info(f"Event Args: {request_event['args']}")

            args = request_event['args']

            if use_marketplace:
                # Verify requester
                event_requester = args.get('requester')
                if event_requester and event_requester.lower() == multisig_address.lower():
                     print_success("Event requester matches multisig address")
                else:
                     print(f"  ❌ Event requester ({event_requester}) does not match multisig ({multisig_address})")

                # Verify priorityMech
                expected_priority_mech = custom_priority_mech
                event_priority_mech = args.get('priorityMech')
                if event_priority_mech and str(event_priority_mech).lower() == str(expected_priority_mech).lower():
                    print_success(f"Event priorityMech matches expected ({expected_priority_mech})")
                else:
                    print(f"  ⚠️ Event priorityMech ({event_priority_mech}) differs from expected ({expected_priority_mech})")

            else:
                # Verify sender matches multisig
                event_sender = args.get('sender')
                if event_sender.lower() == multisig_address.lower():
                     print_success("Event sender matches multisig address")
                else:
                     print(f"  ❌ Event sender ({event_sender}) does not match multisig ({multisig_address})")

                # Verify data matches (if possible, it might be hashed or raw)
                event_data = args.get('data')
                if event_data == dummy_data:
                    print_success("Event data matches request data")
                else:
                    print_info(f"Event data: {event_data}")
        else:
            print(f"  ❌ '{expected_event_name}' event not found in transaction logs")
            print_info(f"All found events: {[e['name'] for e in events]}")
            return False

    except Exception as e:
        print(f"  ❌ Failed to verify event: {e}")
        import traceback
        traceback.print_exc()
        return False

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
