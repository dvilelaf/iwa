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

    READ_METHODS = {
        "get_balance",
        "get_code",
        "get_transaction_count",
        "estimate_gas",
        "wait_for_transaction_receipt",
        "get_block",
        "get_transaction",
        "get_transaction_receipt",
        "call",
        "get_logs",
    }

    WRITE_METHODS = {
        "send_raw_transaction",
    }

    # Helper sets for efficient lookup
    RPC_METHODS = READ_METHODS | WRITE_METHODS

    DEFAULT_READ_RETRIES = 1  # Keep low; ChainInterface.with_retry handles cross-RPC retries
    DEFAULT_READ_RETRY_DELAY = 0.5

    # Only retry errors that are clearly transient network issues.
    # Rate-limit / quota / server errors propagate up to with_retry for rotation.
    TRANSIENT_SIGNALS = (
        "timeout",
        "timed out",
        "connection reset",
        "connection refused",
        "connection aborted",
        "broken pipe",
        "eof",
        "remote end closed",
    )

    def __init__(self, web3_eth, rate_limiter: RPCRateLimiter, chain_interface: "ChainInterface"):
        """Initialize RateLimitedEth wrapper."""
        object.__setattr__(self, "_eth", web3_eth)
        object.__setattr__(self, "_rate_limiter", rate_limiter)
        object.__setattr__(self, "_chain_interface", chain_interface)

    def __getattr__(self, name):
        """Get attribute from underlying eth, wrapping RPC methods with rate limiting."""
        attr = getattr(self._eth, name)

        if name in self.RPC_METHODS and callable(attr):
            return self._wrap_with_retry(attr, name)

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

    @property
    def block_number(self):
        """Get block number with retry."""
        return self._execute_with_retry(lambda: self._eth.block_number, "block_number")

    @property
    def gas_price(self):
        """Get gas price with retry."""
        return self._execute_with_retry(lambda: self._eth.gas_price, "gas_price")

    def _wrap_with_retry(self, method, method_name):
        """Wrap method with rate limiting and retry for reads."""

        def wrapper(*args, **kwargs):
            if not self._rate_limiter.acquire(timeout=30.0):
                raise TimeoutError(f"Rate limit timeout for {method_name}")

            # Writes: no auto-retry (handled by caller or not safe)
            if method_name in self.WRITE_METHODS:
                return method(*args, **kwargs)

            # Reads: with retry
            return self._execute_with_retry(method, method_name, *args, **kwargs)

        return wrapper

    def _execute_with_retry(self, method, method_name, *args, **kwargs):
        """Execute a read operation with limited retry for transient errors.

        Only connection-level failures (timeout, reset, broken pipe) are
        retried here.  Rate-limit, quota, and server errors propagate up
        to ``ChainInterface.with_retry`` which handles RPC rotation.
        This avoids the double-retry amplification that previously caused
        up to 4x7 = 28 RPC requests per logical call.
        """
        for attempt in range(self.DEFAULT_READ_RETRIES + 1):
            try:
                return method(*args, **kwargs)
            except Exception as e:
                if attempt >= self.DEFAULT_READ_RETRIES:
                    raise

                # Only retry clearly transient network errors.
                err_text = str(e).lower()
                if not any(signal in err_text for signal in self.TRANSIENT_SIGNALS):
                    raise

                # Re-acquire a rate-limiter token before retrying.
                if not self._rate_limiter.acquire(timeout=30.0):
                    raise TimeoutError(
                        f"Rate limit timeout for retry of {method_name}"
                    ) from e

                delay = self.DEFAULT_READ_RETRY_DELAY * (2**attempt)
                logger.debug(
                    f"{method_name} attempt {attempt + 1} failed (transient), "
                    f"retrying in {delay:.1f}s..."
                )
                time.sleep(delay)


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
        # Initialize eth wrapper immediately
        self._update_eth_wrapper()

    def set_backend(self, new_web3):
        """Update the underlying Web3 instance (hot-swap)."""
        self._web3 = new_web3
        self._update_eth_wrapper()

    def _update_eth_wrapper(self):
        """Update the eth wrapper to point to the current _web3.eth."""
        self._eth_wrapper = RateLimitedEth(
            self._web3.eth, self._rate_limiter, self._chain_interface
        )

    @property
    def eth(self):
        """Return rate-limited eth interface."""
        return self._eth_wrapper

    def __getattr__(self, name):
        """Delegate attribute access to underlying Web3 instance."""
        return getattr(self._web3, name)
