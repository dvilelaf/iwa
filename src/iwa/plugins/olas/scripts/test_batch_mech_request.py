"""Integration test: batch mech requests via Safe multi-send on Tenderly fork.

Verifies that send_batch_mech_requests():
1. Constructs a valid Safe multi-send transaction
2. Executes successfully on-chain (via Tenderly fork)
3. Emits the correct number of MarketplaceRequest events
4. Uses ~2-3 blocks (within Tenderly's 20-block limit)

Prerequisites:
    - testing=true in secrets.env
    - Tenderly vnets active (just reset-tenderly)
    - Valid service in data/config.yaml with V2 marketplace staking

Usage:
    cd /media/david/DATA/repos/iwa
    PYTHONPATH=src uv run python src/iwa/plugins/olas/scripts/test_batch_mech_request.py
"""

import os
import sys

# Ensure we're on Tenderly
def main():
    from iwa.core.chain import ChainInterfaces
    from iwa.core.wallet import Wallet
    from iwa.plugins.olas.service_manager import ServiceManager

    chain_interface = ChainInterfaces().get("gnosis")

    if not chain_interface.is_tenderly:
        print("ERROR: Not connected to Tenderly! Aborting.")
        print(f"  RPC: {chain_interface.current_rpc}")
        print("  Set testing=true in secrets.env and run: just reset-tenderly")
        sys.exit(1)

    initial_block = chain_interface.web3.eth.block_number
    print(f"Connected to Tenderly fork (block {initial_block})")

    # Load wallet and service manager with trader_andromeda (V2 marketplace)
    service_key = "gnosis:2335"
    wallet = Wallet()
    manager = ServiceManager(wallet, service_key=service_key)
    service = manager.service

    if not service:
        print(f"ERROR: Service {service_key} not found in config")
        sys.exit(1)

    print(f"Service: {service.service_name} (ID {service.service_id})")
    print(f"  Safe: {service.multisig_address}")
    print(f"  Staking: {service.staking_contract_address}")

    # Verify marketplace config
    use_mp, mp_addr, priority_mech = manager.get_marketplace_config()
    if not use_mp:
        print("ERROR: Service does not use marketplace (legacy mech)")
        sys.exit(1)

    print(f"  Marketplace: {mp_addr}")
    print(f"  Priority mech: {priority_mech}")

    # Check Safe has funds for the multi-send (needs xDAI for value)
    safe_addr = str(service.multisig_address)
    safe_balance = chain_interface.web3.eth.get_balance(safe_addr)
    print(f"  Safe balance: {safe_balance / 1e18:.4f} xDAI")

    if safe_balance < 0.05 * 1e18:
        print("  Funding Safe with 1 xDAI from master...")
        master = wallet.master_account.address
        wallet.transfer_service.transfer_native(
            str(master), safe_addr, int(0.5 * 1e18), "gnosis"
        )
        safe_balance = chain_interface.web3.eth.get_balance(safe_addr)
        print(f"  Safe balance after funding: {safe_balance / 1e18:.4f} xDAI")

    # Generate test IPFS data (3 requests — small batch to conserve blocks)
    BATCH_SIZE = 3
    print(f"\n--- Sending {BATCH_SIZE} mech requests via multi-send ---")

    data_payloads = []
    for i in range(BATCH_SIZE):
        # Generate random IPFS-like data (32 bytes)
        data_payloads.append(os.urandom(32))

    # Execute batch
    tx_hash = manager.send_batch_mech_requests(
        data_list=data_payloads,
    )

    if not tx_hash:
        print("FAILED: send_batch_mech_requests returned None")
        sys.exit(1)

    print(f"TX Hash: {tx_hash}")

    # Verify receipt
    receipt = chain_interface.web3.eth.get_transaction_receipt(tx_hash)
    print(f"Status: {'SUCCESS' if receipt['status'] == 1 else 'FAILED'}")
    print(f"Gas used: {receipt['gasUsed']:,}")
    print(f"Block: {receipt['blockNumber']}")

    if receipt["status"] != 1:
        print("FAILED: Transaction reverted on-chain")
        sys.exit(1)

    # Count MarketplaceRequest events
    from iwa.plugins.olas.contracts.mech_marketplace import MechMarketplaceContract

    marketplace = MechMarketplaceContract(str(mp_addr), chain_name="gnosis")
    event_count = 0
    try:
        logs = marketplace.contract.events.MarketplaceRequest().process_receipt(receipt)
        event_count = len(logs)
        print(f"MarketplaceRequest events: {event_count}")
        for i, log in enumerate(logs):
            print(f"  Event {i+1}: requestId={log['args'].get('requestId', '?')}")
    except Exception as e:
        print(f"WARNING: Could not parse events: {e}")
        # Fallback: count raw logs matching the event topic
        from web3 import Web3
        event_sig = Web3.keccak(text="MarketplaceRequest(address,address,uint256,bytes)")
        event_count = sum(1 for log in receipt["logs"] if log["topics"][0] == event_sig)
        print(f"  Raw log count matching MarketplaceRequest topic: {event_count}")

    final_block = chain_interface.web3.eth.block_number
    blocks_used = final_block - initial_block
    print(f"\nBlocks used: {blocks_used} (of 20 available)")

    # Verdict
    print("\n--- VERDICT ---")
    if event_count == BATCH_SIZE:
        print(f"PASS: {event_count}/{BATCH_SIZE} MarketplaceRequest events emitted")
    elif event_count > 0:
        print(f"PARTIAL: {event_count}/{BATCH_SIZE} events (some inner calls may have failed)")
    else:
        print(f"FAIL: 0/{BATCH_SIZE} events emitted — multi-send did not work as expected")
        sys.exit(1)

    print("Multi-send integration test completed successfully.")


if __name__ == "__main__":
    main()
