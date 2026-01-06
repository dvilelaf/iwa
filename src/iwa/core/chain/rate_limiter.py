"""RPC rate limiting classes for chain interactions."""

import threading
import time
from typing import TYPE_CHECKING, Dict

from iwa.core.utils import configure_logger

if TYPE_CHECKING:
    from iwa.core.chain.interface import ChainInterface

logger = configure_logger()


class RPCRateLimiter:
    """Token bucket rate limiter for RPC calls.

    Uses a token bucket algorithm that allows bursts while maintaining
    a maximum average rate over time.
    """

    DEFAULT_RATE = 25.0
    DEFAULT_BURST = 50

    def __init__(
        self,
        rate: float = DEFAULT_RATE,
        burst: int = DEFAULT_BURST,
    ):
        """Initialize rate limiter.

        Args:
            rate: Maximum requests per second (refill rate)
            burst: Maximum tokens (bucket size)

        """
        self.rate = rate
        self.burst = burst
        self.tokens = float(burst)
        self.last_update = time.monotonic()
        self._lock = threading.Lock()
        self._backoff_until = 0.0

    def acquire(self, timeout: float = 30.0) -> bool:
        """Acquire a token, blocking if necessary."""
        deadline = time.monotonic() + timeout

        while True:
            with self._lock:
                now = time.monotonic()

                if now < self._backoff_until:
                    wait_time = self._backoff_until - now
                    if now + wait_time > deadline:
                        return False
                else:
                    elapsed = now - self.last_update
                    self.tokens = min(self.burst, self.tokens + elapsed * self.rate)
                    self.last_update = now

                    if self.tokens >= 1.0:
                        self.tokens -= 1.0
                        return True

                    wait_time = (1.0 - self.tokens) / self.rate
                    if now + wait_time > deadline:
                        return False

            time.sleep(min(wait_time, 0.1))

    def trigger_backoff(self, seconds: float = 5.0):
        """Trigger rate limit backoff."""
        with self._lock:
            self._backoff_until = time.monotonic() + seconds
            self.tokens = 0
            logger.warning(f"RPC rate limit triggered, backing off for {seconds}s")

    def get_status(self) -> dict:
        """Get current rate limiter status."""
        with self._lock:
            now = time.monotonic()
            in_backoff = now < self._backoff_until
            return {
                "tokens": self.tokens,
                "rate": self.rate,
                "burst": self.burst,
                "in_backoff": in_backoff,
                "backoff_remaining": max(0, self._backoff_until - now) if in_backoff else 0,
            }


# Global rate limiters per chain
_rate_limiters: Dict[str, RPCRateLimiter] = {}
_rate_limiters_lock = threading.Lock()


def get_rate_limiter(chain_name: str, rate: float = None, burst: int = None) -> RPCRateLimiter:
    """Get or create a rate limiter for a chain."""
    with _rate_limiters_lock:
        if chain_name not in _rate_limiters:
            _rate_limiters[chain_name] = RPCRateLimiter(
                rate=rate or RPCRateLimiter.DEFAULT_RATE,
                burst=burst or RPCRateLimiter.DEFAULT_BURST,
            )
        return _rate_limiters[chain_name]


class RateLimitedEth:
    """Wrapper around web3.eth that applies rate limiting transparently."""

    RPC_METHODS = {
        "get_balance",
        "get_code",
        "get_transaction_count",
        "estimate_gas",
        "send_raw_transaction",
        "wait_for_transaction_receipt",
        "get_block",
        "get_transaction",
        "get_transaction_receipt",
        "call",
        "get_logs",
    }

    def __init__(self, web3_eth, rate_limiter: RPCRateLimiter, chain_interface: "ChainInterface"):
        """Initialize RateLimitedEth wrapper."""
        object.__setattr__(self, "_eth", web3_eth)
        object.__setattr__(self, "_rate_limiter", rate_limiter)
        object.__setattr__(self, "_chain_interface", chain_interface)

    def __getattr__(self, name):
        """Get attribute from underlying eth, wrapping RPC methods with rate limiting."""
        attr = getattr(self._eth, name)

        if name in self.RPC_METHODS and callable(attr):
            return self._wrap_with_rate_limit(attr, name)

        return attr

    def __setattr__(self, name, value):
        """Set attribute on underlying eth for test mocking."""
        if name.startswith("_"):
            object.__setattr__(self, name, value)
        else:
            setattr(self._eth, name, value)

    def __delattr__(self, name):
        """Delete attribute from underlying eth for patch.object cleanup."""
        if name.startswith("_"):
            object.__delattr__(self, name)
        else:
            delattr(self._eth, name)

    def _wrap_with_rate_limit(self, method, method_name):
        """Wrap a method with rate limiting and error handling."""

        def wrapper(*args, **kwargs):
            if not self._rate_limiter.acquire(timeout=30.0):
                raise TimeoutError(f"Rate limit timeout waiting for {method_name}")

            try:
                return method(*args, **kwargs)
            except Exception as e:
                self._chain_interface._handle_rpc_error(e)
                raise

        return wrapper


class RateLimitedWeb3:
    """Wrapper around Web3 instance that applies rate limiting transparently."""

    def __init__(
        self, web3_instance, rate_limiter: RPCRateLimiter, chain_interface: "ChainInterface"
    ):
        """Initialize RateLimitedWeb3 wrapper."""
        self._web3 = web3_instance
        self._rate_limiter = rate_limiter
        self._chain_interface = chain_interface
        self._eth_wrapper = None

    @property
    def eth(self):
        """Return rate-limited eth interface."""
        if self._eth_wrapper is None:
            self._eth_wrapper = RateLimitedEth(
                self._web3.eth, self._rate_limiter, self._chain_interface
            )
        return self._eth_wrapper

    def __getattr__(self, name):
        """Delegate attribute access to underlying Web3 instance."""
        return getattr(self._web3, name)
