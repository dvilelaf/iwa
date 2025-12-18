"""Chain interaction helpers."""

import threading
import time
from typing import Callable, Dict, List, Optional, Tuple, Union

from eth_account.datastructures import SignedTransaction
from pydantic import BaseModel
from web3 import Web3
from web3 import exceptions as web3_exceptions

from iwa.core.models import Config, EthereumAddress
from iwa.core.settings import settings
from iwa.core.utils import configure_logger, singleton

logger = configure_logger()


class RPCRateLimiter:
    """Token bucket rate limiter for RPC calls.

    Uses a token bucket algorithm that allows bursts while maintaining
    a maximum average rate over time.
    """

    # Default: 25 requests per second (conservative for public RPCs)
    DEFAULT_RATE = 25.0
    DEFAULT_BURST = 50  # Allow burst of up to 50 requests

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
        self._backoff_until = 0.0  # Timestamp until which we're in backoff

    def acquire(self, timeout: float = 30.0) -> bool:
        """Acquire a token, blocking if necessary.

        Args:
            timeout: Maximum time to wait for a token

        Returns:
            True if token acquired, False if timeout
        """
        deadline = time.monotonic() + timeout

        while True:
            with self._lock:
                now = time.monotonic()

                # Check if we're in backoff
                if now < self._backoff_until:
                    wait_time = self._backoff_until - now
                    if now + wait_time > deadline:
                        return False
                else:
                    # Refill tokens based on elapsed time
                    elapsed = now - self.last_update
                    self.tokens = min(self.burst, self.tokens + elapsed * self.rate)
                    self.last_update = now

                    if self.tokens >= 1.0:
                        self.tokens -= 1.0
                        return True

                    # Calculate wait time for next token
                    wait_time = (1.0 - self.tokens) / self.rate
                    if now + wait_time > deadline:
                        return False

            # Wait outside the lock
            time.sleep(min(wait_time, 0.1))

    def trigger_backoff(self, seconds: float = 5.0):
        """Trigger rate limit backoff.

        Called when a 429/rate limit error is detected.
        """
        with self._lock:
            self._backoff_until = time.monotonic() + seconds
            # Also reduce tokens to prevent immediate retry
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
    """Wrapper around web3.eth that applies rate limiting transparently.

    All attribute access is delegated to the underlying web3.eth,
    but RPC-calling methods are wrapped with rate limiting.
    """

    # Methods that make RPC calls and need rate limiting
    RPC_METHODS = {
        "get_balance", "get_code", "get_transaction_count",
        "estimate_gas", "send_raw_transaction", "wait_for_transaction_receipt",
        "get_block", "get_transaction", "get_transaction_receipt",
        "call", "get_logs",
    }

    def __init__(self, web3_eth, rate_limiter: RPCRateLimiter, chain_interface: "ChainInterface"):
        # Use object.__setattr__ to avoid triggering our __setattr__
        object.__setattr__(self, '_eth', web3_eth)
        object.__setattr__(self, '_rate_limiter', rate_limiter)
        object.__setattr__(self, '_chain_interface', chain_interface)

    def __getattr__(self, name):
        attr = getattr(self._eth, name)

        # Wrap RPC methods with rate limiting
        if name in self.RPC_METHODS and callable(attr):
            return self._wrap_with_rate_limit(attr, name)

        return attr

    def __setattr__(self, name, value):
        # Delegate setattr to underlying eth for test mocking
        if name.startswith('_'):
            object.__setattr__(self, name, value)
        else:
            setattr(self._eth, name, value)

    def __delattr__(self, name):
        # Delegate delattr to underlying eth for patch.object cleanup
        if name.startswith('_'):
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
    """Wrapper around Web3 instance that applies rate limiting transparently.

    Usage is identical to regular Web3, but all RPC calls go through rate limiting.
    """

    def __init__(self, web3_instance: Web3, rate_limiter: RPCRateLimiter, chain_interface: "ChainInterface"):
        self._web3 = web3_instance
        self._rate_limiter = rate_limiter
        self._chain_interface = chain_interface
        self._eth_wrapper = None

    @property
    def eth(self):
        """Return rate-limited eth interface."""
        if self._eth_wrapper is None:
            self._eth_wrapper = RateLimitedEth(self._web3.eth, self._rate_limiter, self._chain_interface)
        return self._eth_wrapper

    def __getattr__(self, name):
        # For anything except 'eth', delegate directly
        return getattr(self._web3, name)



class SupportedChain(BaseModel):
    """SupportedChain"""

    name: str
    rpcs: List[str]
    chain_id: int
    native_currency: str
    tokens: Dict[str, EthereumAddress] = {}

    @property
    def rpc(self) -> str:
        """Get the first RPC (primary)."""
        return self.rpcs[0] if self.rpcs else ""

    def get_token_address(self, token_address_or_name: str) -> Optional[EthereumAddress]:
        """Get token address"""
        try:
            address = EthereumAddress(token_address_or_name)
        except Exception:
            address = None

        # If a valid address is provided and it exists in the supported tokens, return it
        if address and address in self.tokens.values():
            return address

        # If a token name is provided, return the corresponding address
        if address is None:
            return self.tokens.get(token_address_or_name, None)

        return None


@singleton
class Gnosis(SupportedChain):
    """Gnosis Chain"""

    name: str = "Gnosis"
    rpcs: List[str] = (
        settings.gnosis_rpc.get_secret_value().split(",") if settings.gnosis_rpc else []
    )
    chain_id: int = 100
    native_currency: str = "xDAI"
    tokens: Dict[str, EthereumAddress] = {
        "OLAS": EthereumAddress("0xcE11e14225575945b8E6Dc0D4F2dD4C570f79d9f"),
        "WXDAI": EthereumAddress("0xe91D153E0b41518A2Ce8Dd3D7944Fa863463a97d"),
        "USDC": EthereumAddress("0x2a22f9c3b484c3629090FeED35F17Ff8F88f76F0"),
        "SDAI": EthereumAddress("0xaf204776c7245bF4147c2612BF6e5972Ee483701"),
        "EURE": EthereumAddress("0x420CA0f9B9b604cE0fd9C18EF134C705e5Fa3430"),
    }


@singleton
class Ethereum(SupportedChain):
    """Ethereum Mainnet"""

    name: str = "Ethereum"
    rpcs: List[str] = (
        settings.ethereum_rpc.get_secret_value().split(",") if settings.ethereum_rpc else []
    )
    chain_id: int = 1
    native_currency: str = "ETH"
    tokens: Dict[str, EthereumAddress] = {
        "OLAS": EthereumAddress("0x0001A500A6B18995B03f44bb040A5fFc28E45CB0"),
    }


@singleton
class Base(SupportedChain):
    """Base"""

    name: str = "Base"
    rpcs: List[str] = settings.base_rpc.get_secret_value().split(",") if settings.base_rpc else []
    chain_id: int = 8453
    native_currency: str = "ETH"
    tokens: Dict[str, EthereumAddress] = {
        "OLAS": EthereumAddress("0x54330d28ca3357F294334BDC454a032e7f353416"),
    }


@singleton
class SupportedChains:
    """SupportedChains"""

    gnosis: SupportedChain = Gnosis()
    ethereum: SupportedChain = Ethereum()
    base: SupportedChain = Base()


class ChainInterface:
    """ChainInterface with rate limiting support."""

    def __init__(self, chain: Union[SupportedChain, str] = None):
        """ChainInterface"""
        if chain is None:
            chain = Gnosis()
        if isinstance(chain, str):
            chain: SupportedChain = getattr(SupportedChains(), chain.lower())

        self.chain = chain
        self._rate_limiter = get_rate_limiter(chain.name)

        if self.chain.rpc and self.chain.rpc.startswith("http://"):
            logger.warning(
                f"Using insecure RPC URL for {self.chain.name}: {self.chain.rpc}. Please use HTTPS."
            )

        # Use rate-limited Web3 wrapper - all RPC calls automatically rate limited
        raw_web3 = Web3(Web3.HTTPProvider(self.chain.rpc, request_kwargs={"timeout": 3}))
        self.web3 = RateLimitedWeb3(raw_web3, self._rate_limiter, self)
        self._current_rpc_index = 0

    def _is_rate_limit_error(self, error: Exception) -> bool:
        """Check if error is a rate limit (429) error."""
        err_text = str(error).lower()
        rate_limit_signals = ["429", "rate limit", "too many requests", "ratelimit"]
        return any(signal in err_text for signal in rate_limit_signals)

    def _handle_rpc_error(self, error: Exception) -> bool:
        """Handle RPC errors, with smart rotation on rate limiting.

        When a rate limit is detected:
        1. First, try to rotate to another RPC
        2. If rotation succeeds, continue without backoff
        3. If no other RPCs available, trigger backoff

        Returns:
            True if error was handled (rotation or backoff triggered)
        """
        if self._is_rate_limit_error(error):
            logger.warning(f"Rate limit error detected: {error}")

            # Try to rotate to another RPC first
            if self.rotate_rpc():
                logger.info("Rotated to new RPC to escape rate limit")
                return True

            # No other RPCs available, must backoff
            logger.warning("No other RPCs available, triggering backoff")
            self._rate_limiter.trigger_backoff(seconds=5.0)
            return True

        return False


    def rotate_rpc(self) -> bool:
        """Rotate to the next available RPC."""
        if not self.chain.rpcs or len(self.chain.rpcs) <= 1:
            return False

        self._current_rpc_index = (self._current_rpc_index + 1) % len(self.chain.rpcs)
        new_rpc = self.chain.rpcs[self._current_rpc_index]
        logger.info(f"Rotating RPC for {self.chain.name} to {new_rpc}")
        raw_web3 = Web3(Web3.HTTPProvider(new_rpc, request_kwargs={"timeout": 3}))
        self.web3 = RateLimitedWeb3(raw_web3, self._rate_limiter, self)
        return True

    def is_contract(self, address: str) -> bool:
        """Check if address is a contract"""
        code = self.web3.eth.get_code(address)
        return code != b""

    @property
    def tokens(self) -> Dict[str, EthereumAddress]:
        """Get all tokens for this chain (default + custom)."""
        defaults = self.chain.tokens.copy()

        config = Config()
        if config.core and config.core.custom_tokens:
            # Look for chain name (case insensitive match?)
            # Config keys usually string.
            custom = config.core.custom_tokens.get(self.chain.name.lower(), {})
            if not custom:
                custom = config.core.custom_tokens.get(self.chain.name, {})

            defaults.update(custom)

        return defaults

    def get_token_symbol(self, address: str) -> str:
        """Get token symbol for an address."""
        # 1. Check known tokens in Chain model
        for symbol, addr in self.chain.tokens.items():
            if addr.lower() == address.lower():
                return symbol

        # 2. Try to fetch from chain
        try:
            from iwa.core.contracts.erc20 import ERC20Contract

            erc20 = ERC20Contract(address, self.chain.name.lower())
            return erc20.symbol or address[:6] + "..." + address[-4:]
        except Exception:
            return address[:6] + "..." + address[-4:]

    def get_token_decimals(self, address: str) -> int:
        """Get token decimals for an address."""
        try:
            from iwa.core.contracts.erc20 import ERC20Contract

            erc20 = ERC20Contract(address, self.chain.name.lower())
            return erc20.decimals if erc20.decimals is not None else 18
        except Exception:
            return 18

    def get_native_balance_wei(self, address: str):
        """Get the native balance in wei"""
        return self.web3.eth.get_balance(address)

    def get_native_balance_eth(self, address: str):
        """Get the native balance in ether"""
        balance_wei = self.get_native_balance_wei(address)
        balance_ether = self.web3.from_wei(balance_wei, "ether")
        return balance_ether

    # NOTE: sign_and_send_transaction was removed for security reasons.
    # Use TransactionService.sign_and_send() instead, which handles signing internally
    # without exposing private keys.

    def estimate_gas(self, built_method, tx_params) -> int:
        """Estimate gas for a contract function call."""
        from_address = tx_params["from"]
        value = tx_params.get("value", 0)
        estimated_gas = (
            0
            if self.is_contract(from_address)
            else built_method.estimate_gas({"from": from_address, "value": value})
        )
        return int(estimated_gas * 1.1)

    def calculate_transaction_params(self, built_method, tx_params) -> dict:
        """Calculate transaction parameters for a contract function call."""
        params = {
            "from": tx_params["from"],
            "value": tx_params.get("value", 0),
            "nonce": self.web3.eth.get_transaction_count(tx_params["from"]),
            "gas": self.estimate_gas(built_method, tx_params),
            "gasPrice": self.web3.eth.gas_price,
        }
        return params

    def wait_for_no_pending_tx(
        self, from_address: str, max_wait_seconds: int = 60, poll_interval: float = 2.0
    ):
        """Wait for no pending transactions for a specified time."""
        start_time = time.time()
        while time.time() - start_time < max_wait_seconds:
            latest_nonce = self.web3.eth.get_transaction_count(
                from_address, block_identifier="latest"
            )
            pending_nonce = self.web3.eth.get_transaction_count(
                from_address, block_identifier="pending"
            )

            if pending_nonce == latest_nonce:
                return True

            time.sleep(poll_interval)

        return False

    def send_native_transfer(
        self,
        from_address: str,
        to_address: EthereumAddress,
        value_wei: int,
        sign_callback: Callable[[dict], SignedTransaction],
    ) -> Tuple[bool, Optional[str]]:
        """Send native currency transaction.

        Note: Rate limiting is handled transparently by RateLimitedWeb3.
        """
        tx = {
            "from": from_address,
            "to": to_address,
            "value": value_wei,
            "nonce": self.web3.eth.get_transaction_count(from_address),
            "chainId": self.chain.chain_id,
        }

        balance_wei = self.get_native_balance_wei(from_address)
        gas_price = self.web3.eth.gas_price
        gas_estimate = self.web3.eth.estimate_gas(tx)
        required_wei = value_wei + (gas_estimate * gas_price)

        if balance_wei < required_wei:
            logger.error(
                f"Insufficient balance to cover amount and gas fees.\nBalance: {self.web3.from_wei(balance_wei, 'ether'):.2f} {self.chain.native_currency}, Required: {self.web3.from_wei(required_wei, 'ether'):.2f} {self.chain.native_currency}"
            )
            return False, None

        tx["gas"] = gas_estimate
        tx["gasPrice"] = gas_price

        signed_tx = sign_callback(tx)
        try:
            txn_hash = self.web3.eth.send_raw_transaction(signed_tx.raw_transaction)
            receipt = self.web3.eth.wait_for_transaction_receipt(txn_hash)
            # Use status from receipt, handle both object and dict
            status = getattr(receipt, "status", None)
            if status is None and isinstance(receipt, dict):
                status = receipt.get("status")

            if receipt and status == 1:
                self.wait_for_no_pending_tx(from_address)
                logger.info(f"Transaction sent successfully. Tx Hash: {txn_hash.hex()}")
                return True, receipt["transactionHash"].hex()

            logger.error("Transaction failed.")
            return False, None
        except Exception as e:
            # Check if it's a rate limit error and handle accordingly
            self._handle_rpc_error(e)
            logger.exception(f"Unexpected error sending native transfer: {e}")
            return False, None

    def get_token_address(self, token_name: str) -> Optional[EthereumAddress]:
        """Get token address by name"""
        return self.chain.get_token_address(token_name)


@singleton
class ChainInterfaces:
    """ChainInterfaces"""

    gnosis: ChainInterface = ChainInterface(Gnosis())
    ethereum: ChainInterface = ChainInterface(Ethereum())
    base: ChainInterface = ChainInterface(Base())

    def get(self, chain_name: str) -> ChainInterface:
        """Get ChainInterface by chain name"""
        chain_name = chain_name.strip().lower()

        if not hasattr(self, chain_name):
            raise ValueError(f"Unsupported chain: {chain_name}")

        return getattr(self, chain_name)

    def items(self):
        """Iterate over all chain interfaces."""
        yield "gnosis", self.gnosis
        yield "ethereum", self.ethereum
        yield "base", self.base
