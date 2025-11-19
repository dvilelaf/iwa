import pytest
from unittest.mock import MagicMock, patch
from iwa.core.chain import ChainInterface, SupportedChain, SupportedChains

def test_supported_chain_token_resolution():
    """Test that tokens can be resolved by name or address."""
    chain = SupportedChains().gnosis

    # Resolve by name
    olas_address = chain.get_token_address("OLAS")
    assert olas_address == "0xcE11e14225575945b8E6Dc0D4F2dD4C570f79d9f"

    # Resolve by address (should return same address)
    addr = "0xcE11e14225575945b8E6Dc0D4F2dD4C570f79d9f"
    resolved = chain.get_token_address(addr)
    assert resolved == addr

    # Invalid name
    assert chain.get_token_address("INVALID_TOKEN") is None

def test_chain_interface_insecure_rpc_warning(caplog):
    """Test that using an HTTP RPC URL logs a warning."""
    class InsecureChain(SupportedChain):
        name: str = "Insecure"
        rpc: str = "http://insecure.rpc"
        chain_id: int = 123
        native_currency: str = "ETH"

    chain = InsecureChain()

    with caplog.at_level("WARNING"):
        ChainInterface(chain)

    assert "Using insecure RPC URL" in caplog.text
    assert "http://insecure.rpc" in caplog.text

def test_chain_interface_secure_rpc_no_warning(caplog):
    """Test that using an HTTPS RPC URL does not log a warning."""
    class SecureChain(SupportedChain):
        name: str = "Secure"
        rpc: str = "https://secure.rpc"
        chain_id: int = 123
        native_currency: str = "ETH"

    chain = SecureChain()

    with caplog.at_level("WARNING"):
        ChainInterface(chain)

    assert "Using insecure RPC URL" not in caplog.text

def test_chain_interfaces_singleton():
    """Test that ChainInterfaces is a singleton and returns correct instances."""
    from iwa.core.chain import ChainInterfaces

    interfaces = ChainInterfaces()
    gnosis = interfaces.get("gnosis")

    assert gnosis.chain.name == "Gnosis"

    # Should raise error for unknown chain
    with pytest.raises(ValueError, match="Unsupported chain"):
        interfaces.get("unknown_chain")
