#!/usr/bin/env python3
import sys
import json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from iwa.core.chain import ChainInterfaces
from iwa.core.wallet import Wallet
from iwa.plugins.olas.service_manager import ServiceManager
from iwa.plugins.olas.contracts.service import ServiceRegistryContract
from iwa.plugins.olas.constants import OLAS_CONTRACTS
from web3 import Web3
from eth_abi import encode

def main():
    chain = ChainInterfaces().gnosis
    registry_address = str(OLAS_CONTRACTS["gnosis"]["OLAS_SERVICE_REGISTRY"])

    # getService(uint256 serviceId)
    # Returns:
    # state (uint8), securityDeposit (uint96), multisig (address), agentIds (uint32[]), agentParams (uint256[][]), threshold (uint32)
    # wait, getService returns a struct.
    # ServiceInfo:
    # securityDeposit, multisig, configHash, threshold, maxNumAgentInstances, numAgentInstances, state, agentIds[]

    # Actually, we need getAgentInstances(serviceId) if available.
    # Or navigate the struct.

    # Let's try getService(975).
    # selector: 0x... I don't know selector offhand.
    # But usually standard.

    # Or getAgentInstances(uint256 serviceId) -> address[]
    # Let's try that.

    print(f"Registry: {registry_address}")

    # Define minimal ABI for getService
    # tuple matches the ABI file:
    # (uint8 securityDeposit, uint96 ... wait, let's use the file if possible, or manual struct)
    # The file says:
    # outputs: tuple(uint8 state, address securityDepositToken, uint96 securityDeposit, uint32 threshold, uint32 maxNumAgentInstances, uint32 numAgentInstances, address multisig, address owner, bytes32 configHash, uint256[] agentIds, tuple[] agentParams, uint32 serviceId)
    # Actually the struct is flattened in some versions, or tuple in others.
    # Iwa's ABI should be correct.

    registry = ServiceRegistryContract(str(registry_address), chain_name="gnosis")

    service_id = 975
    print(f"--- Fetching Service ID {service_id} ---")
    try:
        # getService(uint256) -> Service info
        service_info = registry.contract.functions.getService(service_id).call()
        print(f"Service Info Raw: {service_info}")

        # Parse fields based on struct
        # Based on typical Olas Registry:
        # 0: state
        # 1: securityDepositToken
        # 2: securityDeposit
        # 3: threshold
        # 4: maxNumAgentInstances
        # 5: numAgentInstances
        # 6: multisig <--- THIS IS WHAT WE WANT
        # 7: owner

        multisig = service_info[6]
        print(f"✅ Found Multisig: {multisig}")

    except Exception as e:
        print(f"❌ Failed to get service info: {e}")

    # Try getAgentInstances selector?
    # Or just use raw call with manual encoding if I don't have ABI.
    # I don't have ServiceRegistry ABI in iwa/plugins/olas/contracts/abis/ ??
    # I can try to copy it from triton if it exists.
    pass

    # Better: Use manual ABI for getAgentInstances if it exists.
    # function getAgentInstances(uint256 serviceId) external view returns (address[] memory numAgentInstances)

    # Selector for getAgentInstances(uint256): keccak("getAgentInstances(uint256)")[:4]

    fn_sig = "getAgentInstances(uint256)"
    selector = Web3.keccak(text=fn_sig)[:4].hex()
    calldata = selector + encode(['uint256'], [975]).hex()

    try:
        ret = chain.web3.eth.call({
            "to": registry_address,
            "data": calldata
        })
        print(f"getAgentInstances(975) raw: {ret.hex()}")
        # Decode address[]
        from eth_abi import decode
        instances = decode(['address[]'], ret)[0]
        print(f"Agent Instances: {instances}")
    except Exception as e:
        print(f"Error calling getAgentInstances: {e}")

if __name__ == "__main__":
    main()
