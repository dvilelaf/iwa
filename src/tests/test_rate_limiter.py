"""Tests for RPC rate limiting."""

import threading
import time
from unittest.mock import patch

from iwa.core.chain import RPCRateLimiter, get_rate_limiter


class TestRPCRateLimiter:
    """Test cases for RPCRateLimiter."""

    def test_init_defaults(self):
        """Test default initialization."""
        limiter = RPCRateLimiter()
        assert limiter.rate == RPCRateLimiter.DEFAULT_RATE
        assert limiter.burst == RPCRateLimiter.DEFAULT_BURST
        assert limiter.tokens == float(limiter.burst)

    def test_init_custom_values(self):
        """Test custom initialization."""
        limiter = RPCRateLimiter(rate=10.0, burst=20)
        assert limiter.rate == 10.0
        assert limiter.burst == 20

    def test_acquire_success(self):
        """Test successful token acquisition."""
        limiter = RPCRateLimiter(rate=100.0, burst=10)
        assert limiter.acquire(timeout=1.0) is True
        assert limiter.tokens == 9.0

    def test_acquire_multiple(self):
        """Test acquiring multiple tokens."""
        limiter = RPCRateLimiter(rate=100.0, burst=10)
        for _ in range(5):
            assert limiter.acquire(timeout=1.0) is True
        # Allow small floating point variance due to time passage
        assert 4.9 <= limiter.tokens <= 5.1

    def test_acquire_exhausted_waits(self):
        """Test that acquire waits when tokens exhausted."""
        limiter = RPCRateLimiter(rate=100.0, burst=2)
        # Exhaust tokens
        limiter.tokens = 0.0
        limiter.last_update = time.monotonic()

        start = time.monotonic()
        result = limiter.acquire(timeout=1.0)
        elapsed = time.monotonic() - start

        assert result is True
        # Should have waited a bit for token refill
        assert elapsed >= 0.005  # At least some wait

    def test_acquire_timeout(self):
        """Test that acquire times out."""
        limiter = RPCRateLimiter(rate=0.1, burst=1)  # Very slow refill
        limiter.tokens = 0.0
        limiter.last_update = time.monotonic()

        result = limiter.acquire(timeout=0.01)
        assert result is False

    def test_trigger_backoff(self):
        """Test backoff triggering."""
        limiter = RPCRateLimiter()
        _ = limiter.tokens  # Check tokens exist

        limiter.trigger_backoff(seconds=1.0)

        assert limiter.tokens == 0
        status = limiter.get_status()
        assert status["in_backoff"] is True
        assert status["backoff_remaining"] > 0

    def test_backoff_blocks_acquire(self):
        """Test that backoff blocks acquire."""
        limiter = RPCRateLimiter(rate=100.0, burst=50)
        limiter.trigger_backoff(seconds=10.0)

        # Should timeout waiting for backoff
        result = limiter.acquire(timeout=0.01)
        assert result is False

    def test_get_status(self):
        """Test status reporting."""
        limiter = RPCRateLimiter(rate=25.0, burst=50)
        status = limiter.get_status()

        assert "tokens" in status
        assert "rate" in status
        assert "burst" in status
        assert "in_backoff" in status
        assert status["rate"] == 25.0
        assert status["burst"] == 50

    def test_thread_safety(self):
        """Test that rate limiter is thread-safe."""
        limiter = RPCRateLimiter(rate=1000.0, burst=100)
        acquired = []

        def acquire_tokens():
            for _ in range(10):
                if limiter.acquire(timeout=1.0):
                    acquired.append(1)

        threads = [threading.Thread(target=acquire_tokens) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All should have acquired
        assert len(acquired) == 50


class TestGetRateLimiter:
    """Test get_rate_limiter function."""

    def test_creates_new_limiter(self):
        """Test creating a new rate limiter."""
        # Use unique chain name to avoid interference
        limiter = get_rate_limiter("test_chain_unique_1")
        assert isinstance(limiter, RPCRateLimiter)

    def test_returns_same_limiter(self):
        """Test that same chain returns same limiter."""
        limiter1 = get_rate_limiter("test_chain_unique_2")
        limiter2 = get_rate_limiter("test_chain_unique_2")
        assert limiter1 is limiter2

    def test_different_chains_different_limiters(self):
        """Test that different chains get different limiters."""
        limiter1 = get_rate_limiter("chain_a")
        limiter2 = get_rate_limiter("chain_b")
        assert limiter1 is not limiter2

    def test_custom_rate(self):
        """Test creating limiter with custom rate."""
        limiter = get_rate_limiter("test_chain_unique_3", rate=50.0, burst=100)
        assert limiter.rate == 50.0
        assert limiter.burst == 100


class TestRateLimitRotationInterplay:
    """Test interaction between rate limiting and RPC rotation."""

    def test_rate_limit_triggers_rotation_first(self):
        """Test that rate limit error triggers RPC rotation before backoff."""
        from unittest.mock import MagicMock, PropertyMock

        from iwa.core.chain import ChainInterface, SupportedChain

        # Create a mock chain with multiple RPCs
        with patch("iwa.core.chain.interface.Web3"):
            chain = MagicMock(spec=SupportedChain)
            chain.name = "TestChain"
            chain.rpcs = ["https://rpc1", "https://rpc2", "https://rpc3"]
            type(chain).rpc = PropertyMock(return_value="https://rpc1")

            ci = ChainInterface(chain)
            original_index = ci._current_rpc_index

            # Mock health check to pass
            with patch.object(ci, "check_rpc_health", return_value=True):
                # Simulate rate limit error
                rate_limit_error = Exception("Error 429: Too Many Requests")
                result = ci._handle_rpc_error(rate_limit_error)

                # Should have rotated
                assert result["rotated"] is True
                assert result["should_retry"] is True
                assert ci._current_rpc_index != original_index
                # Backoff should NOT be triggered since rotation succeeded
                assert ci._rate_limiter.get_status()["in_backoff"] is False

    def test_rate_limit_triggers_backoff_when_no_rotation(self):
        """Test that rate limit triggers backoff when no other RPCs available."""
        from unittest.mock import MagicMock, PropertyMock

        from iwa.core.chain import ChainInterface, SupportedChain

        # Create a mock chain with single RPC (can't rotate)
        with patch("iwa.core.chain.interface.Web3"):
            chain = MagicMock(spec=SupportedChain)
            chain.name = "TestChainSingle"
            chain.rpcs = ["https://rpc1"]  # Only one RPC
            type(chain).rpc = PropertyMock(return_value="https://rpc1")

            ci = ChainInterface(chain)

            # Simulate rate limit error
            rate_limit_error = Exception("Error 429: Too Many Requests")
            result = ci._handle_rpc_error(rate_limit_error)

            # Should have triggered backoff since can't rotate
            assert result["should_retry"] is True
            assert result["rotated"] is False
            assert ci._rate_limiter.get_status()["in_backoff"] is True
