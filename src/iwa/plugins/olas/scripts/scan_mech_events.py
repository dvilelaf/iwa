#!/usr/bin/env python3
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from iwa.core.chain import ChainInterfaces
from iwa.plugins.olas.contracts.mech_marketplace import MechMarketplaceContract
from web3 import Web3

def main():
    chain = ChainInterfaces().gnosis
    mp_address = "0x735FAAb1c4Ec41128c367AFb5c3baC73509f70bB"
    mp = MechMarketplaceContract(str(mp_address), chain_name="gnosis")

    # Event CreateMech(indexed mech, indexed serviceId, indexed mechFactory)
    # topic0 = keccak("CreateMech(address,uint256,address)")
    # topic1 = mech (any)
    # topic2 = serviceId (975)

    event_sig = "CreateMech(address,uint256,address)"
    topic0 = Web3.keccak(text=event_sig).hex()
    topic2 = Web3.to_hex(Web3.to_bytes(975).rjust(32, b'\0'))

    print(f"Scanning for CreateMech events for Service 975 on {mp_address}...")
    print(f"Topic0: {topic0}")
    print(f"Topic2: {topic2}")

    current_block = chain.web3.eth.block_number
    print(f"Current block: {current_block}")

    # helper to scan range
    def scan_range(start, end):
        print(f"Scanning {start} to {end}...")
        try:
            logs = chain.web3.eth.get_logs({
                "fromBlock": start,
                "toBlock": end,
                "address": mp_address,
                "topics": [topic0] # Scan ALL CreateMech events, not just for 975. I need ANY valid mech first.
            })
            return logs
        except Exception as e:
            print(f"Error: {e}")
            return []

    # Scan last 1M blocks in 10k chunks
    chunk_size = 10000
    found_mech = None

    for i in range(50): # Try 50 chunks = 500k blocks
        end = current_block - (i * chunk_size)
        start = max(0, end - chunk_size)

        logs = scan_range(start, end)
        if logs:
            for log in logs:
                mech_topic = log["topics"][1].hex()
                mech_addr = Web3.to_checksum_address("0x" + mech_topic[-40:])
                print(f"✅ FOUND REGISTERED MECH: {mech_addr}")

                # Check validation
                # checkMech is view
                try:
                    res = mp.contract.functions.checkMech(mech_addr).call()
                    print(f"   Assertion: checkMech passed! Multisig: {res}")
                    found_mech = mech_addr
                    break
                except Exception as e:
                    print(f"   checkMech failed for this mech: {e}")

        if found_mech:
            break

    if not found_mech:
        print("❌ No valid Mechs found in recent history.")

if __name__ == "__main__":
    main()
