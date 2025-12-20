
from web3 import Web3
from iwa.core.settings import settings
from iwa.plugins.olas.contracts.service import ServiceRegistryContract
from iwa.plugins.olas.constants import OLAS_CONTRACTS
import json

def inspect_service(service_id):
    RPC = settings.gnosis_rpc.get_secret_value()
    # w3 = Web3(Web3.HTTPProvider(RPC))

    # Use chain interface
    from iwa.core.chain import ChainInterfaces
    chain_interface = ChainInterfaces().get("gnosis")

    registry_address = OLAS_CONTRACTS["gnosis"]["OLAS_SERVICE_REGISTRY"]
    registry = ServiceRegistryContract(registry_address, chain_name="gnosis")

    print(f"Inspecting Service {service_id} on {registry_address}")

    try:
        service = registry.get_service(service_id)
        # Manually query token function
        # Note: I need to ensure ServiceRegistryContract has get_token method or do manual call
        # Assuming get_token was added to wrapper or I can use call directly

        # Check if get_token exists on wrapper
        if hasattr(registry, "get_token"):
             token = registry.get_token(service_id)
        else:
             # Manual call for token(uint256) -> address
             func_sig = w3.keccak(text="token(uint256)")[:4].hex()
             data = func_sig + hex(service_id)[2:].zfill(64)
             res = w3.eth.call({"to": str(registry_address), "data": data})
             token = "0x" + res.hex()[-40:]

        print("\nService Data (Python decode):")
        service["token"] = token
        print(json.dumps(service, indent=2, default=str))
    except Exception as e:
        print(f"ServiceRegistry wrapper failed: {e}")

    # Manual call
    w3 = chain_interface.web3
    data = w3.keccak(text="getService(uint256)")[:4].hex() + hex(service_id)[2:].zfill(64)
    res = w3.eth.call({"to": str(registry_address), "data": data})
    print(f"\nRaw Result: {res.hex()}")

if __name__ == "__main__":
    inspect_service(2603)
