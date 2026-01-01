"""Core type definitions."""

import re

import yaml
from pydantic_core import core_schema
from web3 import Web3

ETHEREUM_ADDRESS_REGEX = r"0x[0-9a-fA-F]{40}"


class EthereumAddress(str):
    """EthereumAddress - a checksummed Ethereum address that behaves as a plain str.

    When passed to web3.py functions, this behaves exactly like a str.
    The class validates and checksums addresses on creation.
    """

    def __new__(cls, value: str):
        """Create a new EthereumAddress instance."""
        if not re.fullmatch(ETHEREUM_ADDRESS_REGEX, value):
            raise ValueError(f"Invalid Ethereum address: {value}")
        checksummed = Web3.to_checksum_address(value)
        instance = str.__new__(cls, checksummed)
        return instance

    def __repr__(self) -> str:
        """Return string representation for debugging."""
        return str.__str__(self)

    def __str__(self) -> str:
        """Return as plain string - critical for web3.py compatibility."""
        return str.__str__(self)

    @classmethod
    def __get_pydantic_core_schema__(cls, _source, _handler):
        """Get the Pydantic core schema for EthereumAddress."""
        return core_schema.with_info_after_validator_function(
            cls.validate,
            core_schema.str_schema(),
        )

    @classmethod
    def validate(cls, value: str, _info) -> "EthereumAddress":
        """Validate that the value is a valid Ethereum address."""
        if not re.fullmatch(ETHEREUM_ADDRESS_REGEX, value):
            raise ValueError(f"Invalid Ethereum address: {value}")
        return cls(value)


# Register YAML representer so EthereumAddress serializes as plain string
def _ethereum_address_representer(
    dumper: yaml.SafeDumper, data: EthereumAddress
) -> yaml.ScalarNode:
    """Represent EthereumAddress as a plain YAML string."""
    return dumper.represent_str(str.__str__(data))


yaml.add_representer(EthereumAddress, _ethereum_address_representer, Dumper=yaml.SafeDumper)
