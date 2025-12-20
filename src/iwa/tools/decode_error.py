"""Decode Ethereum error data."""

from eth_abi import decode
from hexbytes import HexBytes

error_data = "0x08c379a0000000000000000000000000000000000000000000000000000000000000002000000000000000000000000000000000000000000000000000000000000000054753303133000000000000000000000000000000000000000000000000000000"

# Remove selector
data = HexBytes(error_data[10:])

try:
    decoded = decode(["string"], data)
    print(f"Decoded error: {decoded[0]}")
except Exception as e:
    print(f"Failed to decode: {e}")
    # Try manual ascii
    try:
        print(f"Raw bytes: {data}")
        print(f"Ascii: {data.decode('utf-8', errors='ignore')}")
    except Exception:
        pass
