#!/usr/bin/env python3
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from iwa.core.chain import ChainInterfaces
from iwa.core.wallet import Wallet
from iwa.plugins.olas.service_manager import ServiceManager
from iwa.plugins.olas.contracts.mech import MechContract

def main():
    wallet = Wallet()
    manager = ServiceManager(wallet)
    chain = ChainInterfaces().gnosis

    multisig_address = manager.service.multisig_address

    # User suggested Mech (ID 9)
    mech_address = "0x552cEA7Bc33CbBEb9f1D90c1D11D2C6daefFd053"

    print(f"Direct Legacy Request to: {mech_address}")

    mech = MechContract(mech_address, chain_name="gnosis")

    data = b"dummy_data"
    value = 10_000_000_000_000_000 # 0.01

    tx_data = mech.prepare_request_tx(
        from_address=multisig_address,
        data=data,
        value=value
    )

    print("Simulating call...")
    try:
        ret = chain.web3.eth.call({
            "to": str(mech_address),
            "from": str(multisig_address),
            "data": tx_data["data"],
            "value": value
        })
        print(f"Call success! Return: {ret.hex()}")
    except Exception as e:
        print(f"Call failed: {e}")

if __name__ == "__main__":
    main()
