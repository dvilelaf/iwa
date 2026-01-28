
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from iwa.core.chain.rate_limiter import RateLimitedEth, RPCRateLimiter


class MockChainInterface:
    def __init__(self):
        self._handle_rpc_error = MagicMock(return_value={"should_retry": True, "rotated": False})


class TestRateLimitedEthRetry:

    @pytest.fixture
    def mock_deps(self):
        web3_eth = MagicMock()
        rate_limiter = MagicMock(spec=RPCRateLimiter)
        rate_limiter.acquire.return_value = True
        chain_interface = MockChainInterface()
        return web3_eth, rate_limiter, chain_interface

    def test_read_method_retries_on_failure(self, mock_deps):
        """Verify that read methods automatically retry on failure."""
        web3_eth, rate_limiter, chain_interface = mock_deps
        eth_wrapper = RateLimitedEth(web3_eth, rate_limiter, chain_interface)

        # Mock get_balance to fail twice then succeed
        web3_eth.get_balance.side_effect = [
            ValueError("RPC error 1"),
            ValueError("RPC error 2"),
            100  # Success
        ]

        # Use patch to speed up sleep
        with patch("time.sleep") as mock_sleep:
            result = eth_wrapper.get_balance("0x123")

        assert result == 100
        assert web3_eth.get_balance.call_count == 3
        # Should have slept twice
        assert mock_sleep.call_count == 2
        # Verify handle_error was called
        assert chain_interface._handle_rpc_error.call_count == 2

    def test_write_method_no_auto_retry(self, mock_deps):
        """Verify that write methods (send_raw_transaction) DO NOT auto-retry."""
        web3_eth, rate_limiter, chain_interface = mock_deps
        eth_wrapper = RateLimitedEth(web3_eth, rate_limiter, chain_interface)

        # Mock send_raw_transaction to fail
        web3_eth.send_raw_transaction.side_effect = ValueError("RPC error")

        # Should raise immediately without retry loop
        with pytest.raises(ValueError, match="RPC error"):
            # Mock get_transaction_count (read) to succeed if called
            web3_eth.get_transaction_count.return_value = 1

            eth_wrapper.send_raw_transaction("0xrawtx")

        # Should verify it was called only once
        assert web3_eth.send_raw_transaction.call_count == 1
        # Chain interface error handler should NOT be called by the wrapper itself
        # (It might typically be called by the caller)
        assert chain_interface._handle_rpc_error.call_count == 0

    def test_retry_respects_max_attempts(self, mock_deps):
        """Verify that retry logic respects maximum attempts."""
        web3_eth, rate_limiter, chain_interface = mock_deps
        eth_wrapper = RateLimitedEth(web3_eth, rate_limiter, chain_interface)

        # Override default retries for quicker test
        # Use object.__setattr__ because RateLimitedEth overrides __setattr__
        object.__setattr__(eth_wrapper, "DEFAULT_READ_RETRIES", 2)

        # Mock always failing
        web3_eth.get_code.side_effect = ValueError("Persistently failing")

        with patch("time.sleep"):
            with pytest.raises(ValueError, match="Persistently failing"):
                eth_wrapper.get_code("0x123")

        # Attempts: initial + 2 retries = 3 total calls
        assert web3_eth.get_code.call_count == 3

    def test_properties_use_retry(self, mock_deps):
        """Verify that properties like block_number use retry logic."""
        web3_eth, rate_limiter, chain_interface = mock_deps
        eth_wrapper = RateLimitedEth(web3_eth, rate_limiter, chain_interface)

        # Mock property access: fail then succeed
        # Note: PropertyMock is needed if we were mocking a property on the CLASS,
        # but here we are mocking the instance attribute access which might be a method call or property.
        # web3.eth.block_number is a property.

        # We need to set side_effect on the PROPERTY of the mock
        type(web3_eth).block_number = PropertyMock(side_effect=[
            ValueError("Fail 1"),
            12345
        ])

        with patch("time.sleep"):
            val = eth_wrapper.block_number

        assert val == 12345
        # Verify handle_error called
        assert chain_interface._handle_rpc_error.call_count == 1
