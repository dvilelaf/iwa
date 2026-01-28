"""Global error decoder for Ethereum contracts."""

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

from eth_abi import decode
from loguru import logger
from web3 import Web3

# Standard error selectors (copied from contract.py for consistency)
ERROR_SELECTOR = "0x08c379a0"  # Error(string)
PANIC_SELECTOR = "0x4e487b71"  # Panic(uint256)

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


class ErrorDecoder:
    """Global registry of error selectors from all project ABIs."""

    _instance = None
    _selectors: Dict[str, List[Dict[str, Any]]] = {}  # selector -> list of possible decodings
    _initialized = False

    def __new__(cls):
        """Singleton pattern."""
        if cls._instance is None:
            cls._instance = super(ErrorDecoder, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        """Initialize and load all ABIs once."""
        if self._initialized:
            return
        self.load_all_abis()
        self._initialized = True

    def load_all_abis(self):
        """Find and load all ABI files in the project."""
        # Find the root of the source tree
        # Assuming we are in src/iwa/core/contracts/decoder.py
        current_file = Path(__file__).resolve()
        src_root = current_file.parents[3]  # Go up to 'src'

        abi_files = list(src_root.glob("**/contracts/abis/*.json"))

        # Also check core ABIs if they are in a different place
        core_abi_path = src_root / "iwa" / "core" / "contracts" / "abis"
        if core_abi_path.exists() and core_abi_path not in [f.parent for f in abi_files]:
            abi_files.extend(list(core_abi_path.glob("*.json")))

        logger.debug(f"Found {len(abi_files)} ABI files for error decoding.")

        for abi_path in abi_files:
            try:
                with open(abi_path, "r", encoding="utf-8") as f:
                    content = json.load(f)
                    abi = (
                        content.get("abi")
                        if isinstance(content, dict) and "abi" in content
                        else content
                    )
                    if isinstance(abi, list):
                        self._process_abi(abi, abi_path.name)
            except Exception as e:
                logger.warning(f"Failed to load ABI {abi_path}: {e}")

    def _process_abi(self, abi: List[Dict], source_name: str):
        """Extract error selectors from an ABI."""
        for entry in abi:
            if entry.get("type") == "error":
                name = entry["name"]
                inputs = entry.get("inputs", [])
                types = [i["type"] for i in inputs]
                names = [i["name"] for i in inputs]

                # Signature: Name(type1,type2,...)
                types_str = ",".join(types)
                signature = f"{name}({types_str})"
                selector = "0x" + Web3.keccak(text=signature)[:4].hex()

                decoding = {
                    "name": name,
                    "types": types,
                    "arg_names": names,
                    "source": source_name,
                    "signature": signature,
                }

                if selector not in self._selectors:
                    self._selectors[selector] = []

                # Avoid duplicates
                if decoding not in self._selectors[selector]:
                    self._selectors[selector].append(decoding)

    def decode(self, error_data: str) -> List[Tuple[str, str, str]]:  # noqa: C901
        """Decode hex error data.

        Returns:
            List of (error_name, formatted_message, source_abi)

        """
        if not error_data:
            return []

        if not error_data.startswith("0x"):
            error_data = "0x" + error_data

        if len(error_data) < 10:
            return []

        selector = error_data[:10].lower()
        encoded_args = error_data[10:]

        results = []

        # 1. Check Standard Error(string)
        if selector == ERROR_SELECTOR:
            try:
                decoded = decode(["string"], bytes.fromhex(encoded_args))
                results.append(("Error", f"Error: {decoded[0]}", "Built-in"))
            except Exception:
                pass

        # 2. Check Panic(uint256)
        if selector == PANIC_SELECTOR:
            try:
                decoded = decode(["uint256"], bytes.fromhex(encoded_args))
                code = decoded[0]
                msg = PANIC_CODES.get(code, f"Unknown panic code {code}")
                results.append(("Panic", f"Panic: {msg}", "Built-in"))
            except Exception:
                pass

        # 3. Check Custom Errors
        if selector in self._selectors:
            for d in self._selectors[selector]:
                try:
                    decoded = decode(d["types"], bytes.fromhex(encoded_args))
                    args_str = ", ".join(
                        f"{n}={v}" for n, v in zip(d["arg_names"], decoded, strict=False)
                    )
                    results.append((d["name"], f"{d['name']}({args_str})", d["source"]))
                except Exception:
                    # Try next possible decoding for this selector
                    continue

        return results
