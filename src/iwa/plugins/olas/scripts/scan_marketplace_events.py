#!/usr/bin/env python3
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from iwa.core.chain import ChainInterfaces
from iwa.plugins.olas.constants import OLAS_CONTRACTS
from web3 import Web3

def main():
    chain = ChainInterfaces().gnosis
    w3 = chain.web3

    mp_address = "0x735FAAb1c4Ec41128c367AFb5c3baC73509f70bB" # Updated constant

    # Calculate topic
    # Event: MarketplaceRequest(address priorityMech, address requester, uint256 numRequests, bytes32[] requestIds, bytes[] requestDatas)
    # The arrays might make the signature tricky if not exact.
    # Actually, verify with what I saw in ABI earlier (Step 2732):
    # event MarketplaceRequest(address indexed priorityMech, address indexed requester, uint256 numRequests, bytes32[] requestIds, bytes[] requestDatas)

    signature = "MarketplaceRequest(address,address,uint256,bytes32[],bytes[])"
    topic = w3.keccak(text=signature).hex()
    print(f"Topic: {topic}")

    latest_block = w3.eth.block_number
    print(f"Latest Block: {latest_block}")

    # Scan last 10k blocks to avoid RPC limits
    from_block = max(0, latest_block - 10_000)

    print(f"Scanning from {from_block} to {latest_block}...")

    filter_params = {
        "fromBlock": hex(from_block),
        "toBlock": hex(latest_block),
        "address": mp_address,
        "topics": [topic]
    }

    logs = w3.eth.get_logs(filter_params)
    print(f"Found {len(logs)} events.")

    if logs:
        # Decode the first one's priorityMech (indexed param 1)
        # Topics[0] = signature
        # Topics[1] = priorityMech (address)
        # Topics[2] = requester (address)

        seen_mechs = set()
        for log in logs:
            if len(log['topics']) > 1:
                # Decode address from topic (pad 23 to 20 bytes)
                # Hex Topic: 0x0000...address
                mech_hex = log['topics'][1].hex()
                mech_address = "0x" + mech_hex[-40:]
                mech_address = w3.to_checksum_address(mech_address)
                seen_mechs.add(mech_address)

        print("\nActive Priority Mechs found:")
        for m in seen_mechs:
            print(f"  - {m}")

    else:
        print("No events found in range.")

if __name__ == "__main__":
    main()
