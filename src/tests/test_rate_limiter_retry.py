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

    def test_read_method_retries_on_transient_failure(self, mock_deps):
        """Verify that read methods retry on transient (connection) errors."""
        web3_eth, rate_limiter, chain_interface = mock_deps
        eth_wrapper = RateLimitedEth(web3_eth, rate_limiter, chain_interface)

        # Mock get_balance to fail once with transient error then succeed
        web3_eth.get_balance.side_effect = [
            ValueError("connection timeout"),
            100,  # Success
        ]

        with patch("time.sleep") as mock_sleep:
            result = eth_wrapper.get_balance("0x123")

        assert result == 100
        # 1 initial + 1 retry = 2 calls (DEFAULT_READ_RETRIES=1)
        assert web3_eth.get_balance.call_count == 2
        assert mock_sleep.call_count == 1
        # RateLimitedEth no longer calls _handle_rpc_error (that's for with_retry)
        assert chain_interface._handle_rpc_error.call_count == 0

    def test_read_method_raises_non_transient_immediately(self, mock_deps):
        """Verify non-transient errors (rate limit, quota) propagate immediately."""
        web3_eth, rate_limiter, chain_interface = mock_deps
        eth_wrapper = RateLimitedEth(web3_eth, rate_limiter, chain_interface)

        web3_eth.get_balance.side_effect = ValueError("429 Too Many Requests")

        with pytest.raises(ValueError, match="429"):
            eth_wrapper.get_balance("0x123")

        # Only 1 attempt, no retry for non-transient errors
        assert web3_eth.get_balance.call_count == 1

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
        assert chain_interface._handle_rpc_error.call_count == 0

    def test_retry_respects_max_attempts(self, mock_deps):
        """Verify that retry logic respects maximum attempts for transient errors."""
        web3_eth, rate_limiter, chain_interface = mock_deps
        eth_wrapper = RateLimitedEth(web3_eth, rate_limiter, chain_interface)

        # Override default retries
        object.__setattr__(eth_wrapper, "DEFAULT_READ_RETRIES", 2)

        # Mock always failing with transient error
        web3_eth.get_code.side_effect = ValueError("connection reset by peer")

        with patch("time.sleep"):
            with pytest.raises(ValueError, match="connection reset"):
                eth_wrapper.get_code("0x123")

        # Attempts: initial + 2 retries = 3 total calls
        assert web3_eth.get_code.call_count == 3

    def test_properties_use_retry(self, mock_deps):
        """Verify that properties like block_number use retry logic."""
        web3_eth, rate_limiter, chain_interface = mock_deps
        eth_wrapper = RateLimitedEth(web3_eth, rate_limiter, chain_interface)

        # block_number fails once with transient error then succeeds
        type(web3_eth).block_number = PropertyMock(
            side_effect=[ValueError("connection timeout"), 12345]
        )

        with patch("time.sleep"):
            val = eth_wrapper.block_number

        assert val == 12345
        # _handle_rpc_error is NOT called by RateLimitedEth anymore
        assert chain_interface._handle_rpc_error.call_count == 0
