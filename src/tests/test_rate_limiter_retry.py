from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from iwa.core.chain.rate_limiter import RateLimitedEth, RateLimitedWeb3, RPCRateLimiter


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

        web3_eth.get_balance.side_effect = [
            ValueError("connection timeout"),
            100,  # Success
        ]

        with patch("time.sleep"):
            result = eth_wrapper.get_balance("0x123")

        assert result == 100
        assert web3_eth.get_balance.call_count == 2
        # Transient retry doesn't trigger rotation
        assert chain_interface._handle_rpc_error.call_count == 0

    def test_read_method_rotates_on_429(self, mock_deps):
        """Verify that 429 errors trigger RPC rotation + single retry."""
        web3_eth, rate_limiter, chain_interface = mock_deps
        eth_wrapper = RateLimitedEth(web3_eth, rate_limiter, chain_interface)

        # First call: 429, rotation retry: success
        web3_eth.get_balance.side_effect = [
            ValueError("429 Too Many Requests"),
            200,  # Success after rotation
        ]

        result = eth_wrapper.get_balance("0x123")

        assert result == 200
        assert web3_eth.get_balance.call_count == 2
        chain_interface._handle_rpc_error.assert_called_once()

    def test_read_method_rotates_on_server_error(self, mock_deps):
        """Verify that 502/503 errors trigger rotation."""
        web3_eth, rate_limiter, chain_interface = mock_deps
        eth_wrapper = RateLimitedEth(web3_eth, rate_limiter, chain_interface)

        web3_eth.get_balance.side_effect = [
            ValueError("502 Bad Gateway"),
            300,
        ]

        result = eth_wrapper.get_balance("0x123")

        assert result == 300
        chain_interface._handle_rpc_error.assert_called_once()

    def test_read_method_rotation_failure_reraises(self, mock_deps):
        """Verify that if rotation retry also fails, error propagates."""
        web3_eth, rate_limiter, chain_interface = mock_deps
        eth_wrapper = RateLimitedEth(web3_eth, rate_limiter, chain_interface)

        # Both attempts fail with 429
        web3_eth.get_balance.side_effect = ValueError("429 Too Many Requests")

        with pytest.raises(ValueError, match="429"):
            eth_wrapper.get_balance("0x123")

        # 1 initial + 1 rotation retry = 2 calls
        assert web3_eth.get_balance.call_count == 2
        chain_interface._handle_rpc_error.assert_called_once()

    def test_read_method_unknown_error_no_rotation(self, mock_deps):
        """Verify that non-transient, non-rotation errors propagate without rotation."""
        web3_eth, rate_limiter, chain_interface = mock_deps
        eth_wrapper = RateLimitedEth(web3_eth, rate_limiter, chain_interface)

        web3_eth.get_balance.side_effect = ValueError("execution reverted")

        with pytest.raises(ValueError, match="execution reverted"):
            eth_wrapper.get_balance("0x123")

        assert web3_eth.get_balance.call_count == 1
        assert chain_interface._handle_rpc_error.call_count == 0

    def test_write_method_rotates_on_429(self, mock_deps):
        """Verify that write methods also rotate on 429 (signed TX is idempotent)."""
        web3_eth, rate_limiter, chain_interface = mock_deps
        eth_wrapper = RateLimitedEth(web3_eth, rate_limiter, chain_interface)

        web3_eth.send_raw_transaction.side_effect = [
            ValueError("429 Too Many Requests"),
            b"0xtxhash",
        ]

        result = eth_wrapper.send_raw_transaction("0xrawtx")

        assert result == b"0xtxhash"
        assert web3_eth.send_raw_transaction.call_count == 2
        chain_interface._handle_rpc_error.assert_called_once()

    def test_write_method_no_transient_retry(self, mock_deps):
        """Verify that writes skip transient retry (only rotation)."""
        web3_eth, rate_limiter, chain_interface = mock_deps
        eth_wrapper = RateLimitedEth(web3_eth, rate_limiter, chain_interface)

        # Non-rotation error — should fail immediately
        web3_eth.send_raw_transaction.side_effect = ValueError("nonce too low")

        with pytest.raises(ValueError, match="nonce too low"):
            eth_wrapper.send_raw_transaction("0xrawtx")

        assert web3_eth.send_raw_transaction.call_count == 1
        assert chain_interface._handle_rpc_error.call_count == 0

    def test_retry_respects_max_attempts(self, mock_deps):
        """Verify that transient retry respects maximum attempts."""
        web3_eth, rate_limiter, chain_interface = mock_deps
        eth_wrapper = RateLimitedEth(web3_eth, rate_limiter, chain_interface)
        object.__setattr__(eth_wrapper, "DEFAULT_READ_RETRIES", 2)

        web3_eth.get_code.side_effect = ValueError("connection reset by peer")

        with patch("time.sleep"):
            with pytest.raises(ValueError, match="connection reset"):
                eth_wrapper.get_code("0x123")

        # 1 initial + 2 transient retries + 1 rotation retry (not a rotation signal) = 3
        assert web3_eth.get_code.call_count == 3
        # "connection reset" is transient, not a rotation signal
        assert chain_interface._handle_rpc_error.call_count == 0

    def test_properties_use_retry_and_rotation(self, mock_deps):
        """Verify that properties like block_number get rotation on 429."""
        web3_eth, rate_limiter, chain_interface = mock_deps
        eth_wrapper = RateLimitedEth(web3_eth, rate_limiter, chain_interface)

        type(web3_eth).block_number = PropertyMock(
            side_effect=[ValueError("429 rate limit"), 12345]
        )

        val = eth_wrapper.block_number

        assert val == 12345
        chain_interface._handle_rpc_error.assert_called_once()

    def test_tenderly_quota_error_propagates(self, mock_deps):
        """Verify TenderlyQuotaExceededError from _handle_rpc_error propagates."""
        web3_eth, rate_limiter, chain_interface = mock_deps
        eth_wrapper = RateLimitedEth(web3_eth, rate_limiter, chain_interface)

        web3_eth.get_balance.side_effect = ValueError("403 Forbidden")

        # _handle_rpc_error raises a special exception
        chain_interface._handle_rpc_error.side_effect = RuntimeError("TenderlyQuotaExceeded")

        with pytest.raises(RuntimeError, match="TenderlyQuotaExceeded"):
            eth_wrapper.get_balance("0x123")

    def test_rotation_should_retry_false(self, mock_deps):
        """Verify that rotation with should_retry=False still raises."""
        web3_eth, rate_limiter, chain_interface = mock_deps
        eth_wrapper = RateLimitedEth(web3_eth, rate_limiter, chain_interface)

        web3_eth.get_balance.side_effect = ValueError("429 Too Many Requests")
        chain_interface._handle_rpc_error.return_value = {"should_retry": False}

        with pytest.raises(ValueError, match="429"):
            eth_wrapper.get_balance("0x123")

        # Only 1 attempt (no retry since should_retry=False)
        assert web3_eth.get_balance.call_count == 1

    def test_transient_then_rotation(self, mock_deps):
        """Verify transient retry exhausted → rotation triggered for rotation error."""
        web3_eth, rate_limiter, chain_interface = mock_deps
        eth_wrapper = RateLimitedEth(web3_eth, rate_limiter, chain_interface)

        # 1st: transient → retried. 2nd: 429 → rotation. 3rd: success.
        web3_eth.get_balance.side_effect = [
            ValueError("connection timeout"),  # Transient retry
            ValueError("429 rate limited"),  # Falls through to rotation
            500,  # Success
        ]

        with patch("time.sleep"):
            result = eth_wrapper.get_balance("0x123")

        assert result == 500
        assert web3_eth.get_balance.call_count == 3
        chain_interface._handle_rpc_error.assert_called_once()


class TestEthWrapperHotSwap:
    """Test that _update_eth_wrapper hot-swaps _eth in-place."""

    def test_hot_swap_updates_eth_in_place(self):
        """Verify set_backend updates _eth without creating new RateLimitedEth."""
        rate_limiter = MagicMock(spec=RPCRateLimiter)
        rate_limiter.acquire.return_value = True
        chain_interface = MockChainInterface()

        mock_web3_v1 = MagicMock()
        mock_web3_v1.eth.get_balance.return_value = 100

        wrapper = RateLimitedWeb3(mock_web3_v1, rate_limiter, chain_interface)
        eth_wrapper_v1 = wrapper.eth  # Capture reference

        # Now rotate: swap to v2
        mock_web3_v2 = MagicMock()
        mock_web3_v2.eth.get_balance.return_value = 200

        wrapper.set_backend(mock_web3_v2)

        # Same RateLimitedEth instance (hot-swapped, not replaced)
        assert wrapper.eth is eth_wrapper_v1
        # But the _eth inside points to v2 now
        result = wrapper.eth.get_balance("0x123")
        assert result == 200

    def test_rotation_retry_uses_new_provider(self):
        """End-to-end: 429 → rotation → hot-swap → retry uses new provider."""
        rate_limiter = MagicMock(spec=RPCRateLimiter)
        rate_limiter.acquire.return_value = True

        mock_web3_v1 = MagicMock()
        mock_web3_v2 = MagicMock()

        # v1 returns 429, v2 returns success
        mock_web3_v1.eth.get_balance.side_effect = ValueError("429 Too Many Requests")
        mock_web3_v2.eth.get_balance.return_value = 42

        chain_interface = MockChainInterface()

        wrapper = RateLimitedWeb3(mock_web3_v1, rate_limiter, chain_interface)

        # When _handle_rpc_error is called, simulate rotation by swapping backend
        def simulate_rotation(error):
            wrapper.set_backend(mock_web3_v2)
            return {"should_retry": True, "rotated": True}

        chain_interface._handle_rpc_error.side_effect = simulate_rotation

        result = wrapper.eth.get_balance("0x123")

        assert result == 42
        # v1 was called once (429), v2 was called once (success)
        assert mock_web3_v1.eth.get_balance.call_count == 1
        assert mock_web3_v2.eth.get_balance.call_count == 1
