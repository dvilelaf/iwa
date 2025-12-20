
from web3 import Web3
from iwa.core.settings import settings
from iwa.core.wallet import Wallet
from iwa.plugins.olas.contracts.service import ServiceRegistryContract
from iwa.plugins.olas.constants import OLAS_CONTRACTS, TRADER_CONFIG_HASH
from iwa.core.constants import NATIVE_CURRENCY_ADDRESS
import json

def test_direct_create():
    wallet = Wallet()
    chain_name = "gnosis"

    registry_address = OLAS_CONTRACTS[chain_name]["OLAS_SERVICE_REGISTRY"]
    registry = ServiceRegistryContract(registry_address, chain_name=chain_name)

    token_address = "0xcE11e14225575945b8E6Dc0D4F2dD4C570f79d9f"
    bond_amount = 50000000000000000000
    agent_params = [{"slots": 1, "bond": bond_amount}]
    service_owner = wallet.master_account.address

    print(f"Direct Create on Registry: {registry_address}")
    print(f"Token: {token_address}")
    print(f"Bond: {bond_amount}")

    # Prepare tx directly for Registry
    # create(serviceOwner, token, configHash, agentIds, agentParams, threshold)
    tx = registry.prepare_transaction(
        method_name="create",
        method_kwargs={
            "serviceOwner": service_owner,
            "token": token_address,
            "configHash": bytes.fromhex(TRADER_CONFIG_HASH),
            "agentIds": [25],
            "agentParams": agent_params,
            "threshold": 1,
        },
        tx_params={"from": service_owner},
    )

    print(f"Encoded Data: {tx['data']}")

    # Send
    success, receipt = wallet.sign_and_send_transaction(
        transaction=tx,
        signer_address_or_tag=service_owner,
        chain_name=chain_name
    )

    if not success:
        print("Failed to create service")
        return

    print("Transaction sent successfully")
    events = registry.extract_events(receipt)
    for event in events:
        if event["name"] == "CreateService":
            service_id = event["args"]["serviceId"]
            print(f"Service created with ID: {service_id}")

            # Inspect immediately
            service = registry.get_service(service_id)
            print("Service Data:")
            print(json.dumps(service, indent=2, default=str))

if __name__ == "__main__":
    test_direct_create()
