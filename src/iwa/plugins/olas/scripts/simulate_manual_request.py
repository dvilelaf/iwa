#!/usr/bin/env python3
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from iwa.core.chain import ChainInterfaces
from iwa.core.wallet import Wallet
from iwa.plugins.olas.service_manager import ServiceManager
from web3 import Web3
from eth_abi import encode

def main():
    wallet = Wallet()
    manager = ServiceManager(wallet)
    chain = ChainInterfaces().gnosis
    multisig_address = manager.service.multisig_address

    # OLD Marketplace
    mp_address = "0x4554fE75c1f5576c1d7F765B2A036c199Adae329"

    # Priority Mech (User Provided)
    priority_mech = "0x552cEA7Bc33CbBEb9f1D90c1D11D2C6daefFd053"

    data = b"dummy_data"
    max_delivery_rate = 50_000_000_000_000_000
    response_timeout = 300
    payment_data = b""
    value = 10_000_000_000_000_000 # 0.01

    # Hypothesis: v1.0 Signature
    # request(bytes,uint256,address,uint256,bytes)
    # requestData, maxDeliveryRate, priorityMech, responseTimeout, paymentData

    signature = "request(bytes,uint256,address,uint256,bytes)"
    selector = Web3.keccak(text=signature)[:4].hex()

    print(f"Testing Signature: {signature}")
    print(f"Selector: {selector}")

    encoded_args = encode(
        ['bytes', 'uint256', 'address', 'uint256', 'bytes'],
        [data, max_delivery_rate, priority_mech, response_timeout, payment_data]
    )

    calldata = selector + encoded_args.hex()

    print("Simulating call...")
    try:
        ret = chain.web3.eth.call({
            "to": mp_address,
            "from": multisig_address,
            "data": calldata,
            "value": value
        })
        print(f"Call success! Return: {ret.hex()}")
    except Exception as e:
        print(f"Call failed: {e}")

if __name__ == "__main__":
    main()
