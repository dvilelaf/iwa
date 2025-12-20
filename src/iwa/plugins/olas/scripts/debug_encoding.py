
from web3 import Web3
from iwa.core.settings import settings
from iwa.plugins.olas.contracts.service import ServiceManagerContract
from iwa.plugins.olas.constants import OLAS_CONTRACTS, TRADER_CONFIG_HASH
from iwa.core.constants import NATIVE_CURRENCY_ADDRESS
import json

def debug_encoding():
    chain_name = "gnosis"
    manager_address = OLAS_CONTRACTS[chain_name]["OLAS_SERVICE_MANAGER"]
    manager = ServiceManagerContract(manager_address, chain_name=chain_name)

    token_address = "0xcE11e14225575945b8E6Dc0D4F2dD4C570f79d9f"
    bond_amount = 50000000000000000000
    agent_params = [{"slots": 1, "bond": bond_amount}]

    print(f"Token: {token_address}")
    print(f"Bond: {bond_amount}")
    print(f"Agent Params: {agent_params}")

    tx = manager.prepare_create_tx(
        from_address="0xC99C41526a016704Da8EA1183684F3cb6A7A1d31",
        service_owner="0xC99C41526a016704Da8EA1183684F3cb6A7A1d31",
        token_address=token_address,
        config_hash=bytes.fromhex(TRADER_CONFIG_HASH),
        agent_ids=[25],
        agent_params=agent_params,
        threshold=1,
    )

    data = tx['data']
    print(f"\nEncoded Data: {data}")

    # Decode
    decoded = manager.contract.decode_function_input(data)
    print("\nDecoded:")
    print(decoded)

if __name__ == "__main__":
    debug_encoding()
