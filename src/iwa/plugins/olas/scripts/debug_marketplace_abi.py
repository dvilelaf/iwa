#!/usr/bin/env python3
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from iwa.core.chain import ChainInterfaces
from web3 import Web3
import json

def main():
    chain = ChainInterfaces().gnosis
    mp_address = "0x735FAAb1c4Ec41128c367AFb5c3baC73509f70bB"

    # 1-arg checkMech ABI
    abi = [
        {
            "inputs": [{"internalType": "address", "name": "mech", "type": "address"}],
            "name": "checkMech",
            "outputs": [{"internalType": "address", "name": "multisig", "type": "address"}],
            "stateMutability": "view",
            "type": "function"
        }
    ]

    contract = chain.web3.eth.contract(address=mp_address, abi=abi)

    mech = Web3.to_checksum_address("0xf035cc0dd8f31af8db93ed7451788bf431859710")

    print(f"Testing checkMech({mech}) on {mp_address}...")
    try:
        res = contract.functions.checkMech(mech).call()
        print(f"✅ checkMech(1 arg) PASSED! Multisig: {res}")
    except Exception as e:
        print(f"❌ checkMech(1 arg) FAILED: {e}")

if __name__ == "__main__":
    main()
