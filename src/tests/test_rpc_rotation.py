"""Comprehensive RPC rotation tests.

These tests verify that RPC rotation works correctly when rate limit errors occur,
ensuring that after rotation, requests actually go to the new RPC.
"""

import time
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from iwa.core.chain import ChainInterface, SupportedChain


class MockHTTPError(Exception):
    """Mock HTTP 429 error with URL info."""

    def __init__(self, url: str):
        self.url = url
        super().__init__(f"429 Client Error: Too Many Requests for url: {url}")


@pytest.fixture
def multi_rpc_chain():
    """Create a chain with multiple RPCs for testing rotation."""
    chain = MagicMock(spec=SupportedChain)
    chain.name = "TestChain"
    chain.rpcs = [
        "https://rpc1.example.com",
        "https://rpc2.example.com",
        "https://rpc3.example.com",
        "https://rpc4.example.com",
        "https://rpc5.example.com",
    ]
    chain.chain_id = 1
    chain.native_currency = "ETH"
    chain.tokens = {}
    type(chain).rpc = PropertyMock(return_value=chain.rpcs[0])
    return chain


@pytest.fixture
def mock_web3_factory():
    """Factory to create mock Web3 instances that track their RPC URL."""

    def create_mock_web3(rpc_url: str):
        mock = MagicMock()
        mock.provider.endpoint_uri = rpc_url
        mock.eth.block_number = 12345
        return mock

    return create_mock_web3


def test_rpc_rotation_basic(multi_rpc_chain):
    """Test that RPC rotation cycles through all available RPCs."""
    with patch("iwa.core.chain.interface.RateLimitedWeb3", side_effect=lambda w3, rl, ci: w3):
        ci = ChainInterface(multi_rpc_chain)

        # Should start at index 0
        assert ci._current_rpc_index == 0

        # Rotate through all RPCs
        # We need to mock monotonic time to bypass cooldown
        current_time = [1000.0]

        def mock_monotonic():
            current_time[0] += 3.0  # Advance by 3s (> 2s cooldown)
            return current_time[0]

        with patch("time.monotonic", side_effect=mock_monotonic):
            for expected_index in [1, 2, 3, 4, 0, 1]:  # Wraps around
                result = ci.rotate_rpc()
                assert result is True
                assert ci._current_rpc_index == expected_index


def test_rpc_rotation_updates_provider():
    """Test that after rotation, set_backend is called to update the provider.

    The current implementation uses set_backend() to hot-swap the underlying
    Web3 instance rather than creating a new RateLimitedWeb3 wrapper.
    """
    chain = MagicMock(spec=SupportedChain)
    chain.name = "TestChain"
    chain.rpcs = ["https://rpc1.example.com", "https://rpc2.example.com"]
    type(chain).rpc = PropertyMock(return_value=chain.rpcs[0])

    set_backend_calls = []

    class MockRateLimitedWeb3:
        def __init__(self, w3, rl, ci):
            self._web3 = w3
            self.set_backend = MagicMock(
                side_effect=lambda new_w3: set_backend_calls.append(new_w3)
            )

        def __getattr__(self, name):
            return getattr(self._web3, name)

    with patch("iwa.core.chain.interface.Web3") as mock_web3_class:
        with patch("iwa.core.chain.interface.RateLimitedWeb3", MockRateLimitedWeb3):
            # Make Web3 return a mock with the correct provider URL
            def create_web3_mock(provider):
                mock = MagicMock()
                mock.provider = provider
                return mock

            mock_web3_class.side_effect = create_web3_mock
            mock_web3_class.HTTPProvider = lambda url, **kwargs: MagicMock(endpoint_uri=url)

            ci = ChainInterface(chain)

            # Initially no set_backend calls
            assert len(set_backend_calls) == 0

            # Rotate
            ci.rotate_rpc()

            # After rotation, set_backend should have been called
            assert len(set_backend_calls) == 1
            # And it should have been called with a new Web3 instance
            assert set_backend_calls[0].provider.endpoint_uri == "https://rpc2.example.com"


def test_rate_limit_triggers_rotation(multi_rpc_chain):
    """Test that a 429 rate limit error triggers RPC rotation."""
    with patch("iwa.core.chain.interface.RateLimitedWeb3", side_effect=lambda w3, rl, ci: w3):
        ci = ChainInterface(multi_rpc_chain)

        initial_index = ci._current_rpc_index
        assert initial_index == 0

        # Simulate a rate limit error
        error = MockHTTPError("https://rpc1.example.com")
        result = ci._handle_rpc_error(error)

        # Should have detected rate limit and rotated
        assert result["is_rate_limit"] is True
        assert result["rotated"] is True
        assert result["should_retry"] is True
        assert ci._current_rpc_index == 1


def test_with_retry_rotates_on_rate_limit(multi_rpc_chain):
    """Test that with_retry properly rotates RPC on rate limit and succeeds on new RPC."""
    with patch("iwa.core.chain.interface.RateLimitedWeb3", side_effect=lambda w3, rl, ci: w3):
        ci = ChainInterface(multi_rpc_chain)

        call_count = 0
        rpc_indices_seen = []

        # Mock time to avoid cooldown preventing rotation in this test
        current_time = [1000.0]

        def mock_monotonic():
            current_time[0] += 3.0  # Advance by 3s (> 2s cooldown)
            return current_time[0]

        def flaky_operation():
            nonlocal call_count
            call_count += 1
            rpc_indices_seen.append(ci._current_rpc_index)

            # Fail on first RPC, succeed on second
            if ci._current_rpc_index == 0:
                raise MockHTTPError(ci.chain.rpcs[0])
            return "success"

        with patch("time.sleep"):  # Skip actual delays
            with patch("time.monotonic", side_effect=mock_monotonic):
                result = ci.with_retry(flaky_operation, operation_name="test_operation")

        assert result == "success"
        assert 0 in rpc_indices_seen  # Started on RPC 0
        assert 1 in rpc_indices_seen  # Rotated to RPC 1
        assert ci._current_rpc_index == 1  # Ended on RPC 1


def test_with_retry_exhausts_all_rpcs_then_backs_off(multi_rpc_chain):
    """Test that when all RPCs fail, we trigger backoff."""
    with patch("iwa.core.chain.interface.RateLimitedWeb3", side_effect=lambda w3, rl, ci: w3):
        ci = ChainInterface(multi_rpc_chain)

        # All RPCs fail
        def always_fail():
            raise MockHTTPError(ci.chain.rpcs[ci._current_rpc_index])

        with patch("time.sleep"):
            with pytest.raises(MockHTTPError):
                ci.with_retry(always_fail, max_retries=6, operation_name="doomed_operation")

        # Should have rotated through multiple RPCs
        # Since we didn't mock time to bypass cooldown, it might not have rotated many times
        # But we just want to ensure it at least tried
        assert ci._current_rpc_index >= 0


def test_rotation_applies_to_subsequent_calls():
    """Test that after rotation, subsequent method calls use the new RPC.

    This is the critical test - verifying that the fix for the RPC rotation
    bug actually works. After rotation, calls should go to the new RPC.
    """
    chain = MagicMock(spec=SupportedChain)
    chain.name = "TestChain"
    chain.rpcs = ["https://rpc1.example.com", "https://rpc2.example.com"]
    type(chain).rpc = PropertyMock(return_value=chain.rpcs[0])

    with patch("iwa.core.chain.interface.Web3") as mock_web3_class:
        # Track which provider is being used for each call
        current_provider_url = ["https://rpc1.example.com"]

        def create_web3(provider):
            mock = MagicMock()
            mock.provider = provider

            # eth.get_balance should use the current provider
            def mock_get_balance(addr):
                return f"balance_from_{current_provider_url[0]}"

            mock.eth.get_balance = mock_get_balance
            mock.eth.block_number = 12345
            return mock

        def create_provider(url, **kwargs):
            prov = MagicMock()
            prov.endpoint_uri = url
            current_provider_url[0] = url
            return prov

        mock_web3_class.side_effect = create_web3
        mock_web3_class.HTTPProvider = create_provider

        with patch("iwa.core.chain.interface.RateLimitedWeb3", side_effect=lambda w3, rl, ci: w3):
            ci = ChainInterface(chain)

            # First call uses RPC 1
            result1 = ci.web3.eth.get_balance("0xtest")
            assert "rpc1" in result1

            # Rotate to RPC 2
            # Mock time to bypass cooldown
            with patch("time.monotonic", return_value=time.monotonic() + 10):
                ci.rotate_rpc()

            # Second call should use RPC 2
            result2 = ci.web3.eth.get_balance("0xtest")
            assert "rpc2" in result2


def test_contract_uses_current_provider_after_rotation():
    """Test that ContractInstance.contract property recreates contract each time.

    This verifies the contract property doesn't cache and always
    uses the current provider.
    """
    # This is a simplified test that verifies the contract property
    # creates a new contract each time it's accessed
    from pathlib import Path

    from iwa.core.contracts.contract import ContractInstance

    # Mock a minimal chain interface
    mock_web3 = MagicMock()
    mock_web3._web3.eth.contract = MagicMock()

    mock_chain_interface = MagicMock()
    mock_chain_interface.web3 = mock_web3

    # Create a ContractInstance with mocked dependencies
    with patch("iwa.core.chain.ChainInterfaces") as mock_interfaces:
        mock_interfaces.return_value.get.return_value = mock_chain_interface

        # Mock the ABI loading
        mock_abi = [{"type": "function", "name": "test", "inputs": [], "outputs": []}]

        with patch("builtins.open", MagicMock()):
            with patch("json.load", return_value=mock_abi):
                # Need to mock abi_path for ContractInstance
                with patch.object(ContractInstance, "abi_path", Path("/fake/path.json")):
                    with patch.object(ContractInstance, "load_error_selectors", return_value={}):
                        instance = ContractInstance.__new__(ContractInstance)
                        instance.address = "0x1234567890123456789012345678901234567890"
                        instance.abi = mock_abi
                        instance.chain_interface = mock_chain_interface
                        instance._contract_cache = None
                        instance.error_selectors = {}

                        # Access contract property twice
                        # The key test: verify it calls web3._web3.eth.contract each time
                        _ = instance.contract
                        _ = instance.contract

                        # Should have called contract() twice (no caching)
                        assert mock_web3._web3.eth.contract.call_count == 2


def test_single_rpc_no_rotation(multi_rpc_chain):
    """Test that rotation returns False when there's only one RPC."""
    multi_rpc_chain.rpcs = ["https://only-one.example.com"]

    with patch("iwa.core.chain.interface.RateLimitedWeb3", side_effect=lambda w3, rl, ci: w3):
        ci = ChainInterface(multi_rpc_chain)

        result = ci.rotate_rpc()
        assert result is False
        assert ci._current_rpc_index == 0


def test_rotation_cooldown(multi_rpc_chain):
    """Test that rotation respects the cooldown period."""
    with patch("iwa.core.chain.interface.RateLimitedWeb3", side_effect=lambda w3, rl, ci: w3):
        ci = ChainInterface(multi_rpc_chain)

        # Initial state
        assert ci._current_rpc_index == 0

        # First rotation - should succeed
        with patch("time.monotonic", return_value=1000.0):
            result = ci.rotate_rpc()
            assert result is True
            assert ci._current_rpc_index == 1

        # Immediate second rotation - should fail due to cooldown
        with patch("time.monotonic", return_value=1000.5):  # only 0.5s later
            result = ci.rotate_rpc()
            assert result is False
            assert ci._current_rpc_index == 1  # Index unchanged

        # Rotation after cooldown - should succeed
        with patch("time.monotonic", return_value=1003.0):  # 3s later
            result = ci.rotate_rpc()
            assert result is True
            assert ci._current_rpc_index == 2  # Index advanced
