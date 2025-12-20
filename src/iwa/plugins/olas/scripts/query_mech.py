import json
from pathlib import Path
from web3 import Web3

from iwa.core.settings import settings
RPC = settings.gnosis_rpc.get_secret_value()
w3 = Web3(Web3.HTTPProvider(RPC))

MECH_ADDRESS = Web3.to_checksum_address("0x552cEA7Bc33CbBEb9f1D90c1D11D2C6daefFd053")
ABI_PATH = Path("/media/david/DATA/repos/iwa/src/iwa/plugins/olas/contracts/abis/mech.json")

with open(ABI_PATH, "r") as f:
    abi = json.load(f)

contract = w3.eth.contract(address=MECH_ADDRESS, abi=abi)

print(f"Checking Mech at {MECH_ADDRESS}")
try:
    price = contract.functions.price().call()
    print(f"Price: {price}")
except Exception as e:
    print(f"Failed to get price: {e}")
