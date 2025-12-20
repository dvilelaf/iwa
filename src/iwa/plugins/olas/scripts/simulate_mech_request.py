#!/usr/bin/env python3
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from iwa.core.chain import ChainInterfaces
from iwa.core.wallet import Wallet
from iwa.plugins.olas.service_manager import ServiceManager
from iwa.plugins.olas.contracts.mech_marketplace import MechMarketplaceContract
from iwa.plugins.olas.constants import OLAS_CONTRACTS

def main():
    wallet = Wallet()
    manager = ServiceManager(wallet)
    chain = ChainInterfaces().gnosis
    multisig_address = manager.service.multisig_address

    # Candidates
    from web3 import Web3
    candidates = [
        (Web3.to_checksum_address("0xf035cc0dd8f31af8db93ed7451788bf431859710"), "Agent Instance (0xf035)"),
        (Web3.to_checksum_address("0x552cEA7Bc33CbBEb9f1D90c1D11D2C6daefFd053"), "Triton Config (0x552c)"),
        (Web3.to_checksum_address("0x69C0669F3b5df0F2E2644F01098B4465f5652101"), "Service Multisig (0x69C0)"),
        (Web3.to_checksum_address("0xEB2A22b27C7Ad5eeE424Fd90b376c745E60f914E"), "Service Owner (0xEB2A)"),
    ]

    mp_address = "0x735FAAb1c4Ec41128c367AFb5c3baC73509f70bB"
    mp = MechMarketplaceContract(str(mp_address), chain_name="gnosis")

    priority_mech_staking = "0x998dEFafD094817EF329f6dc79c703f1CF18bC90"
    priority_mech_service_id = 975
    requester_staking = "0x389B46c259631Acd6a69Bde8B6cEe218230bAE8C" # From test log
    requester_service_id = 2593 # From test log

    data = b"dummy_data"
    value = 10_000_000_000_000_000 # 0.01

    for mech, desc in candidates:
        print(f"\n--- Simulating Candidate: {desc} ---")
        try:
            # New 6-arg signature
            tx_data = mp.prepare_request_tx(
                from_address=multisig_address,
                request_data=data,
                priority_mech=mech,
                response_timeout=300,
                max_delivery_rate=10_000,
                payment_type=b"\x00" * 32,
                payment_data=b"",
                value=value
            )

            if tx_data is None:
                print(f"❌ Failed: prepare_request_tx returned None. ABI mismatch or invalid args?")
                continue

            print(f"  Tx Data: {str(tx_data)[:50]}...")
            ret = chain.web3.eth.call(tx_data)
            print(f"✅ SUCCESS! Return: {ret.hex()}")
            return # Exit on first success

        except Exception as e:
            print(f"❌ Failed: {e}")

if __name__ == "__main__":
    main()
