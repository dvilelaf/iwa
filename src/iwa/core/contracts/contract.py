import json
import warnings
from pathlib import Path
from typing import Any, Dict, List, Optional

from eth_abi import decode
from loguru import logger
from web3 import Web3
from web3.contract import Contract
from web3.exceptions import ContractCustomError
from eth_abi import decode
from iwa.core.chain import ChainInterfaces


class ContractInstance:
    """Class to interact with smart contracts."""

    name: str = None
    abi_path: Path = None

    def __init__(self, address: str, chain_name: str = "gnosis"):
        self.address = address
        self.abi = None
        self.chain_interface = ChainInterfaces().get(chain_name)

        with open(self.abi_path, "r", encoding="utf-8") as abi_file:
            contract_abi = json.load(abi_file)

            if isinstance(contract_abi, dict) and "abi" in contract_abi:
                self.abi = contract_abi.get("abi")
            else:
                self.abi = contract_abi

        self.contract: Contract = self.chain_interface.web3.eth.contract(
            address=self.address, abi=self.abi
        )
        self.error_selectors = self.load_error_selectors()

    def load_error_selectors(self) -> Dict[str, Any]:
        """Load error selectors from the contract ABI."""
        selectors = {}
        for entry in self.abi:
            if entry.get("type") == "error":
                name = entry["name"]
                inputs = entry.get("inputs", [])
                types = ",".join(i["type"] for i in inputs)
                signature = f"{name}({types})"
                selector = Web3.keccak(text=signature)[:4].hex()
                selectors[f"0x{selector}"] = (
                    name,
                    [i["type"] for i in inputs],
                    [i["name"] for i in inputs],
                )
        return selectors

    def call(self, method_name: str, *args) -> Any:
        """Call a function in the contract without sending a transaction."""
        method = getattr(self.contract.functions, method_name)
        return method(*args).call()

    def prepare_transaction(
        self, method_name: str, method_kwargs: Dict, tx_params: Dict
    ) -> Optional[dict]:
        """Prepare a transaction"""
        method = getattr(self.contract.functions, method_name)
        built_method = method(*method_kwargs.values())

        try:
            tx_params = self.chain_interface.calculate_transaction_params(built_method, tx_params)
            transaction = built_method.build_transaction(tx_params)
            return transaction

        except ContractCustomError as e:
            data = e.args[0]
            selector = data[:10]
            encoded_args = data[10:]
            if selector in self.error_selectors:
                error_name, types, names = self.error_selectors[selector]
                decoded = decode(types, bytes.fromhex(encoded_args))
                error_str = ", ".join(f"{name}={value}" for name, value in zip(names, decoded))
                raise Exception(
                    f"CustomError in '{self.name}' contract[{self.address}]\n{error_name}({error_str})"
                )
            else:
                raise Exception(f"Unknown custom error (selector={selector})")

        except Exception as e:
            data = getattr(e, "args", [None])[1]
            selector = "0x08c379a0"
            if isinstance(data, str) and data.startswith(selector):
                encoded_args = bytes.fromhex(data[len(selector) :])
                decoded_tuple = decode(["string"], encoded_args)
                error_message = decoded_tuple[0]
                logger.error(f"Error preparing transaction: {error_message}")
            else:
                logger.error(f"Error preparing transaction: {e}")
            return None

    def extract_events(self, receipt) -> List[Dict]:
        """Extract events from a transaction receipt."""
        all_events = []

        for event_abi in self.contract.abi:
            # Skip non events
            if event_abi.get("type") != "event":
                continue

            try:
                event = self.contract.events[event_abi["name"]]
            except KeyError:
                continue

            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                try:
                    decoded_logs = event().process_receipt(receipt)

                    if not decoded_logs:
                        continue

                    for log in decoded_logs:
                        all_events.append({"name": log["event"], "args": dict(log.args)})
                except Exception:
                    continue

        return all_events
