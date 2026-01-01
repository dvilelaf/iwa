"""Contract interaction helpers."""

import json
import warnings
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from eth_abi import decode
from web3 import Web3
from web3.contract import Contract
from web3.exceptions import ContractCustomError

from iwa.core.chain import ChainInterfaces
from iwa.core.utils import configure_logger

logger = configure_logger()

# Standard error selectors
ERROR_SELECTOR = "0x08c379a0"  # Error(string)
PANIC_SELECTOR = "0x4e487b71"  # Panic(uint256)

# Panic codes (from Solidity)
PANIC_CODES = {
    0x00: "Generic compiler inserted panic",
    0x01: "Assert failed",
    0x11: "Arithmetic overflow/underflow",
    0x12: "Division by zero",
    0x21: "Invalid enum value",
    0x22: "Storage byte array incorrectly encoded",
    0x31: "Pop on empty array",
    0x32: "Array index out of bounds",
    0x41: "Too much memory allocated",
    0x51: "Invalid internal function call",
}


class ContractInstance:
    """Class to interact with smart contracts."""

    name: str = None
    abi_path: Path = None

    def __init__(self, address: str, chain_name: str = "gnosis"):
        """Initialize contract instance."""
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

    def decode_error(self, error_data: str) -> Optional[Tuple[str, str]]:
        """Decode error data from a failed transaction or call.

        Handles:
        - Custom errors defined in the contract ABI
        - Standard Error(string) reverts
        - Panic(uint256) errors

        Args:
            error_data: The hex-encoded error data (with or without 0x prefix).

        Returns:
            Tuple of (error_name, formatted_message) or None if decoding fails.

        """
        if not error_data:
            return None

        # Normalize data
        if not error_data.startswith("0x"):
            error_data = f"0x{error_data}"

        if len(error_data) < 10:
            return None

        selector = error_data[:10]
        encoded_args = error_data[10:]

        # Check for custom errors from ABI
        if selector in self.error_selectors:
            error_name, types, names = self.error_selectors[selector]
            try:
                decoded = decode(types, bytes.fromhex(encoded_args))
                error_str = ", ".join(
                    f"{name}={value}" for name, value in zip(names, decoded, strict=True)
                )
                return (error_name, f"{error_name}({error_str})")
            except Exception as e:
                logger.debug(f"Failed to decode custom error args: {e}")
                return (error_name, f"{error_name}(decoding failed)")

        # Check for standard Error(string)
        if selector == ERROR_SELECTOR:
            try:
                decoded = decode(["string"], bytes.fromhex(encoded_args))
                return ("Error", decoded[0])
            except Exception as e:
                logger.debug(f"Failed to decode Error(string): {e}")
                return ("Error", "Failed to decode error message")

        # Check for Panic(uint256)
        if selector == PANIC_SELECTOR:
            try:
                decoded = decode(["uint256"], bytes.fromhex(encoded_args))
                panic_code = decoded[0]
                panic_msg = PANIC_CODES.get(panic_code, f"Unknown panic code: {panic_code}")
                return ("Panic", panic_msg)
            except Exception as e:
                logger.debug(f"Failed to decode Panic(uint256): {e}")
                return ("Panic", "Failed to decode panic code")

        return None

    def _extract_error_data(self, exception: Exception) -> Optional[str]:
        """Extract error data from various exception formats.

        Different RPC providers and web3 versions format errors differently.
        This method tries to extract the error data from common formats.
        """
        # ContractCustomError has data directly
        if isinstance(exception, ContractCustomError) and exception.args:
            return exception.args[0] if isinstance(exception.args[0], str) else None

        # Check exception args for hex data
        args = getattr(exception, "args", ())
        for arg in args:
            if isinstance(arg, str) and arg.startswith("0x"):
                return arg
            if isinstance(arg, dict):
                # Some providers return {"data": "0x..."}
                data = arg.get("data")
                if isinstance(data, str) and data.startswith("0x"):
                    return data

        # Check for 'data' attribute
        data = getattr(exception, "data", None)
        if isinstance(data, str) and data.startswith("0x"):
            return data

        return None

    def call(self, method_name: str, *args) -> Any:
        """Call a function in the contract without sending a transaction.

        Args:
            method_name: The name of the contract function to call.
            *args: Arguments to pass to the function.

        Returns:
            The return value of the contract function.

        Raises:
            Exception: If the call fails, with decoded error information.

        """
        method = getattr(self.contract.functions, method_name)
        try:
            return method(*args).call()
        except Exception as e:
            error_data = self._extract_error_data(e)
            if error_data:
                decoded = self.decode_error(error_data)
                if decoded:
                    error_name, error_msg = decoded
                    logger.error(
                        f"Contract call '{method_name}' on {self.name}[{self.address}] "
                        f"failed: {error_name}: {error_msg}"
                    )
            raise

    def _sanitize_for_web3(self, value: Any) -> Any:
        """Convert EthereumAddress subclass to pure str for eth_abi encoding.

        eth_abi encoder cannot handle custom str subclasses; this ensures
        all address strings are pure str instances.
        """
        if isinstance(value, str) and type(value) is not str:
            # It's a str subclass (like EthereumAddress), convert to pure str
            return str.__str__(value)
        if isinstance(value, dict):
            return {k: self._sanitize_for_web3(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return type(value)(self._sanitize_for_web3(v) for v in value)
        return value

    def prepare_transaction(
        self, method_name: str, method_kwargs: Dict, tx_params: Dict
    ) -> Optional[dict]:
        """Prepare a transaction.

        Args:
            method_name: The name of the contract function to call.
            method_kwargs: Dictionary of keyword arguments for the function.
            tx_params: Transaction parameters (from, gas, etc.).

        Returns:
            The prepared transaction dict, or None if preparation failed.

        """
        # Sanitize kwargs and params to convert EthereumAddress to pure str
        method_kwargs = self._sanitize_for_web3(method_kwargs)
        tx_params = self._sanitize_for_web3(tx_params)

        method = getattr(self.contract.functions, method_name)
        built_method = method(*method_kwargs.values())

        try:
            tx_params = self.chain_interface.calculate_transaction_params(built_method, tx_params)
            transaction = built_method.build_transaction(tx_params)
            return transaction

        except Exception as e:
            error_data = self._extract_error_data(e)
            if error_data:
                decoded = self.decode_error(error_data)
                if decoded:
                    error_name, error_msg = decoded
                    logger.error(
                        f"Failed to prepare '{method_name}' on {self.name}[{self.address}]: "
                        f"{error_name}: {error_msg}"
                    )
                    return None

            # Fallback: log the raw exception
            logger.error(f"Failed to prepare '{method_name}': {e}")
            return None

    def extract_events(self, receipt) -> List[Dict]:
        """Extract events from a transaction receipt.

        Args:
            receipt: The transaction receipt.

        Returns:
            List of event dictionaries with 'name' and 'args' keys.

        """
        all_events = []

        if not receipt:
            return all_events

        for event_abi in self.contract.abi:
            # Skip non events
            if event_abi.get("type") != "event":
                continue

            event_name = event_abi.get("name", "Unknown")
            try:
                event = self.contract.events[event_name]
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
                except Exception as e:
                    # Log at debug level to avoid noise, but capture the issue
                    logger.debug(f"Failed to decode event '{event_name}' from {self.name}: {e}")
                    continue

        return all_events
