import sys
import os
from pathlib import Path
from web3 import Web3
import json

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from iwa.core.wallet import Wallet
from iwa.plugins.olas.service_manager import ServiceManager
from iwa.core.settings import settings

def main():
    wallet = Wallet()
    rpc = settings.gnosis_rpc.get_secret_value()
    w3 = Web3(Web3.HTTPProvider(rpc))

    mech_addr = Web3.to_checksum_address("0x552cEA7Bc33CbBEb9f1D90c1D11D2C6daefFd053")
    abi_path = Path("src/iwa/plugins/olas/contracts/abis/mech.json")

    with open(abi_path, "r") as f:
        abi = json.load(f)

    contract = w3.eth.contract(address=mech_addr, abi=abi)

    price = contract.functions.price().call()
    print(f"Contract Price: {price}")

    # Get active service to get Safe address
    manager = ServiceManager(wallet)
    service = manager.olas_config.get_active_service()
    safe_addr = Web3.to_checksum_address(service.multisig_address)
    print(f"Safe address: {safe_addr}")

    ipfs_data = bytes.fromhex("ba39655f4d1e25d0c83a73df658c8b8e0a293344665566778899aabbccddeeff")
    call_data = contract.functions.request(ipfs_data)._encode_transaction_data()

    print(f"\nSimulation from Master EOA ({wallet.master_account.address}):")
    try:
        res = w3.eth.call({
            'from': wallet.master_account.address,
            'to': mech_addr,
            'value': price,
            'data': call_data
        })
        print(f"  ✅ Call success!")
    except Exception as e:
        print(f"  ❌ Call failed: {e}")

    print(f"\nSimulation from Safe ({safe_addr}) [Marketplace]:")
    market_addr = Web3.to_checksum_address("0x4554fE75c1f5576c1d7F765B2A036c199Adae329")
    market_abi_path = Path("src/iwa/plugins/olas/contracts/abis/mech_marketplace.json")
    with open(market_abi_path, "r") as f:
        market_abi = json.load(f)
    market_contract = w3.eth.contract(address=market_addr, abi=market_abi)

    from iwa.plugins.olas.constants import OLAS_TRADER_STAKING_CONTRACTS
    staking_map = OLAS_TRADER_STAKING_CONTRACTS.get("gnosis", {})
    staking_inst = list(staking_map.values())[0]

    market_call_data = market_contract.functions.request(
        ipfs_data,
        mech_addr,
        Web3.to_checksum_address("0x0000000000000000000000000000000000000000"), # priorityMechStakingInstance
        0, # priorityMechServiceId
        staking_inst, # requesterStakingInstance
        service.service_id, # requesterServiceId
        1000 # response_timeout
    )._encode_transaction_data()

    try:
        res = w3.eth.call({
            'from': safe_addr,
            'to': market_addr,
            'value': price,
            'data': market_call_data
        })
        print(f"  ✅ Call success!")
    except Exception as e:
        print(f"  ❌ Call failed: {e}")

if __name__ == "__main__":
    main()
