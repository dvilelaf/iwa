"""ChainInterface class for blockchain interactions."""

import threading
import time
from typing import Callable, Dict, Optional, TypeVar, Union

from web3 import Web3

from iwa.core.chain.errors import TenderlyQuotaExceededError, sanitize_rpc_url
from iwa.core.chain.models import Gnosis, SupportedChain, SupportedChains
from iwa.core.chain.rate_limiter import RateLimitedWeb3, get_rate_limiter
from iwa.core.models import Config, EthereumAddress
from iwa.core.utils import configure_logger

logger = configure_logger()

T = TypeVar("T")
DEFAULT_RPC_TIMEOUT = 10


class ChainInterface:
    """ChainInterface with rate limiting, retry logic, and RPC rotation support."""

    DEFAULT_MAX_RETRIES = 6  # Allow trying most/all available RPCs on rate limit
    DEFAULT_RETRY_DELAY = 1.0  # Base delay between retries (exponential backoff)

    chain: SupportedChain

    def __init__(self, chain: Union[SupportedChain, str] = None):
        """Initialize ChainInterface."""
        if chain is None:
            chain = Gnosis()
        if isinstance(chain, str):
            chain: SupportedChain = getattr(SupportedChains(), chain.lower())

        self.chain = chain
        # Enforce strict 1.0 RPS limit to prevent synchronization issues
        self._rate_limiter = get_rate_limiter(chain.name, rate=1.0, burst=1)
        self._current_rpc_index = 0
        self._rpc_failure_counts: Dict[int, int] = {}

        if self.chain.rpc and self.chain.rpc.startswith("http://"):
            logger.warning(
                f"Using insecure RPC URL for {self.chain.name}: "
                f"{sanitize_rpc_url(self.chain.rpc)}. Please use HTTPS."
            )

        self._initial_block = 0
        self._rotation_lock = threading.Lock()
        self._init_web3()

    @property
    def current_rpc(self) -> str:
        """Get the current active RPC URL."""
        if not self.chain.rpcs:
            return ""
        return self.chain.rpcs[self._current_rpc_index]

    @property
    def is_tenderly(self) -> bool:
        """Check if connected to Tenderly vNet."""
        rpc = self.current_rpc or ""
        return "tenderly" in rpc.lower() or "virtual" in rpc.lower()

    def init_block_tracking(self):
        """Initialize block tracking for limit detection.

        Only enables block limit warnings if we have a valid tenderly config file
        with initial_block set. Otherwise, leaves _initial_block at 0 which
        disables the warnings (since we can't accurately track usage without
        knowing the fork point).
        """
        if not self.is_tenderly:
            return  # Only track for Tenderly vNets

        try:
            from iwa.core.constants import get_tenderly_config_path
            from iwa.core.models import TenderlyConfig

            profile = Config().core.tenderly_profile
            config_path = get_tenderly_config_path(profile)

            if not config_path.exists():
                logger.debug(f"Tenderly config not found at {config_path}, skipping block tracking")
                return

            t_config = TenderlyConfig.load(config_path)
            vnet = t_config.vnets.get(self.chain.name)
            if not vnet:
                vnet = t_config.vnets.get(self.chain.name.lower())

            if vnet and vnet.initial_block > 0:
                self._initial_block = vnet.initial_block
                logger.info(f"Tenderly block tracking enabled (genesis: {self._initial_block})")
            else:
                logger.debug(f"Tenderly config exists but no initial_block for {self.chain.name}")

        except Exception as ex:
            logger.warning(f"Failed to load Tenderly config for block tracking: {ex}")

    def check_block_limit(self, show_progress_bar: bool = False):
        """Check if approaching block limit (heuristic).

        Args:
            show_progress_bar: If True, display a large ASCII progress bar (for startup).

        """
        if not self.is_tenderly or self._initial_block == 0:
            return

        try:
            current = self.web3.eth.block_number
            delta = current - self._initial_block
            limit = 20  # Tenderly free tier limit (updated Jan 2026)
            percentage = min(100, int((delta / limit) * 100))

            # Show progress bar at startup or when explicitly requested
            if show_progress_bar or delta == 0:
                self._display_tenderly_progress(delta, limit, percentage)

            if delta >= 20:
                logger.error(
                    f"🛑 CRITICAL TENDERLY LIMIT REACHED: {delta} blocks processed. "
                    f"The vNet has likely expired (limit 20). Transactions WILL fail. "
                    f"Please run `just reset-tenderly` immediately."
                )
            elif delta > 16:
                logger.warning(
                    f"⚠️ TENDERLY LIMIT WARNING: {delta}/20 blocks ({percentage}%). "
                    f"You may experience errors soon."
                )
            elif delta > 0 and delta % 5 == 0:
                logger.info(f"📊 Tenderly Usage: {delta}/20 blocks ({percentage}%)")

        except Exception:
            pass

    def _display_tenderly_progress(self, used: int, limit: int, percentage: int):
        """Display a visual ASCII progress bar for Tenderly block usage."""
        bar_width = 40
        filled = int(bar_width * percentage / 100)
        empty = bar_width - filled

        # Color coding based on usage
        if percentage >= 80:
            bar_char = "█"
            status = "🔴 CRITICAL"
        elif percentage >= 60:
            bar_char = "█"
            status = "🟡 WARNING"
        else:
            bar_char = "█"
            status = "🟢 OK"

        bar = bar_char * filled + "░" * empty
        # Use print to ensure visibility in console (loguru writes to file)
        print("")
        print("╔══════════════════════════════════════════════════╗")
        print("║          TENDERLY VIRTUAL NETWORK USAGE          ║")
        print("╠══════════════════════════════════════════════════╣")
        print(f"║  [{bar}]  ║")
        print(f"║           {used:2d}/{limit} blocks  ({percentage:3d}%)  {status:12s}     ║")
        print("╚══════════════════════════════════════════════════╝")
        print("")

    def _is_rate_limit_error(self, error: Exception) -> bool:
        """Check if error is a rate limit (429) error."""
        err_text = str(error).lower()
        rate_limit_signals = ["429", "rate limit", "too many requests", "ratelimit"]
        return any(signal in err_text for signal in rate_limit_signals)

    def _is_connection_error(self, error: Exception) -> bool:
        """Check if error is a connection/network error."""
        err_text = str(error).lower()
        connection_signals = [
            "timeout",
            "timed out",
            "connection refused",
            "connection reset",
            "connection error",
            "connection aborted",
            "name resolution",
            "dns",
            "no route to host",
            "network unreachable",
            "max retries exceeded",
            "read timeout",
            "connect timeout",
            "remote end closed",
            "broken pipe",
        ]
        return any(signal in err_text for signal in connection_signals)

    def _is_tenderly_quota_exceeded(self, error: Exception) -> bool:
        """Check if error indicates Tenderly quota exceeded (403 Forbidden)."""
        err_text = str(error).lower()
        if "403" in err_text and "forbidden" in err_text:
            if "tenderly" in err_text or "virtual" in err_text:
                return True
        return False

    def _is_server_error(self, error: Exception) -> bool:
        """Check if error is a server-side error (5xx)."""
        err_text = str(error).lower()
        server_error_signals = [
            "500",
            "502",
            "503",
            "504",
            "internal server error",
            "bad gateway",
            "service unavailable",
            "gateway timeout",
        ]
        return any(signal in err_text for signal in server_error_signals)

    def _is_gas_error(self, error: Exception) -> bool:
        """Check if error is related to gas limits or fees."""
        err_text = str(error).lower()
        gas_signals = [
            "intrinsic gas too low",
            "feetoolow",
            "gas limit",
            "underpriced",
        ]
        return any(signal in err_text for signal in gas_signals)

    def _handle_rpc_error(self, error: Exception) -> Dict[str, Union[bool, int]]:
        """Handle RPC errors with smart rotation and retry logic."""
        result: Dict[str, Union[bool, int]] = {
            "is_rate_limit": self._is_rate_limit_error(error),
            "is_connection_error": self._is_connection_error(error),
            "is_server_error": self._is_server_error(error),
            "is_gas_error": self._is_gas_error(error),
            "is_tenderly_quota": self._is_tenderly_quota_exceeded(error),
            "rotated": False,
            "should_retry": False,
        }

        if result["is_tenderly_quota"]:
            logger.error(
                "TENDERLY QUOTA EXCEEDED! The virtual network has reached its limit. "
                "Please run 'uv run -m iwa.tools.reset_tenderly' to reset the network."
            )
            raise TenderlyQuotaExceededError(
                "Tenderly virtual network quota exceeded (403 Forbidden). "
                "Run 'uv run -m iwa.tools.reset_tenderly' to reset."
            )

        self._rpc_failure_counts[self._current_rpc_index] = (
            self._rpc_failure_counts.get(self._current_rpc_index, 0) + 1
        )

        should_rotate = result["is_rate_limit"] or result["is_connection_error"]

        if should_rotate:
            error_type = "rate limit" if result["is_rate_limit"] else "connection"
            logger.warning(
                f"RPC {error_type} error on {self.chain.name} "
                f"(RPC #{self._current_rpc_index}): {error}"
            )

            if self.rotate_rpc():
                result["rotated"] = True
                result["should_retry"] = True
                logger.info(f"Rotated to RPC #{self._current_rpc_index} for {self.chain.name}")
            else:
                if result["is_rate_limit"]:
                    self._rate_limiter.trigger_backoff(seconds=5.0)
                    result["should_retry"] = True
                    logger.warning("No other RPCs available, triggered backoff")

        elif result["is_server_error"]:
            logger.warning(f"Server error on {self.chain.name}: {error}")
            result["should_retry"] = True

        elif result["is_gas_error"]:
            logger.warning(f"Gas/Fee error detected: {error}. Allowing retry for adjustment.")
            result["should_retry"] = True

        return result

    def rotate_rpc(self) -> bool:
        """Rotate to the next available RPC."""
        with self._rotation_lock:
            if not self.chain.rpcs or len(self.chain.rpcs) <= 1:
                return False

            # Simple Round Robin rotation
            self._current_rpc_index = (self._current_rpc_index + 1) % len(self.chain.rpcs)
            # Internal call to _init_web3 already expects to be under lock if called from here,
            # but _init_web3 itself doesn't have a lock. Let's make it consistent.
            self._init_web3_under_lock()

            logger.info(
                f"Rotated RPC for {self.chain.name} to index {self._current_rpc_index}: {self.chain.rpcs[self._current_rpc_index]}"
            )
            return True

    def _init_web3(self):
        """Initialize Web3 with current RPC (thread-safe)."""
        with self._rotation_lock:
            self._init_web3_under_lock()

    def _init_web3_under_lock(self):
        """Internal non-thread-safe web3 initialization."""
        rpc_url = self.chain.rpcs[self._current_rpc_index] if self.chain.rpcs else ""
        raw_web3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": DEFAULT_RPC_TIMEOUT}))

        # Use duck typing to check if current web3 is a RateLimitedWeb3 wrapper
        if hasattr(self, "web3") and hasattr(self.web3, "set_backend"):
            self.web3.set_backend(raw_web3)
        else:
            self.web3 = RateLimitedWeb3(raw_web3, self._rate_limiter, self)

    def check_rpc_health(self) -> bool:
        """Check if the current RPC is healthy."""
        try:
            block = self.web3._web3.eth.block_number
            return block is not None and block > 0
        except Exception as e:
            logger.debug(f"RPC health check failed: {e}")
            return False

    def with_retry(
        self,
        operation: Callable[[], T],
        max_retries: Optional[int] = None,
        operation_name: str = "operation",
    ) -> T:
        """Execute an operation with retry logic."""
        if max_retries is None:
            max_retries = self.DEFAULT_MAX_RETRIES

        last_error = None

        for attempt in range(max_retries + 1):
            try:
                return operation()
            except Exception as e:
                last_error = e
                result = self._handle_rpc_error(e)

                if not result["should_retry"] or attempt >= max_retries:
                    logger.error(f"{operation_name} failed after {attempt + 1} attempts: {e}")
                    raise

                delay = self.DEFAULT_RETRY_DELAY * (2**attempt)
                logger.info(
                    f"{operation_name} attempt {attempt + 1} failed, retrying in {delay:.1f}s..."
                )
                time.sleep(delay)

        if last_error:
            raise last_error
        raise RuntimeError(f"{operation_name} failed unexpectedly")

    def is_contract(self, address: EthereumAddress) -> bool:
        """Check if address is a contract"""
        code = self.web3.eth.get_code(address)
        return code != b""

    @property
    def tokens(self) -> Dict[str, EthereumAddress]:
        """Get all tokens for this chain (default + custom)."""
        defaults = self.chain.tokens.copy()

        config = Config()
        if config.core and config.core.custom_tokens:
            custom = config.core.custom_tokens.get(self.chain.name.lower(), {})
            if not custom:
                custom = config.core.custom_tokens.get(self.chain.name, {})
            defaults.update(custom)

        return defaults

    def get_token_symbol(self, address: EthereumAddress) -> str:
        """Get token symbol for an address."""
        for symbol, addr in self.chain.tokens.items():
            if addr.lower() == address.lower():
                return symbol

        try:
            from iwa.core.contracts.erc20 import ERC20Contract

            erc20 = ERC20Contract(address, self.chain.name.lower())
            return erc20.symbol or address[:6] + "..." + address[-4:]
        except Exception:
            return address[:6] + "..." + address[-4:]

    def get_token_decimals(self, address: EthereumAddress, fallback_to_18: bool = True) -> Optional[int]:
        """Get token decimals for an address.

        Args:
            address: Token contract address.
            fallback_to_18: If True, return 18 on error (default).
                           If False, return None on error (useful for detecting NFTs).

        Returns:
            Decimals as int, or None if error and fallback_to_18 is False.

        """
        try:
            # Call decimals() directly without with_retry to avoid error logging
            # Use _web3 directly to ensure current provider after RPC rotation
            contract = self.web3._web3.eth.contract(
                address=self.web3.to_checksum_address(address),
                abi=[{"constant": True, "inputs": [], "name": "decimals", "outputs": [{"type": "uint8"}], "type": "function"}]
            )
            return contract.functions.decimals().call()
        except Exception:
            if fallback_to_18:
                return 18
            return None

    def get_native_balance_wei(self, address: EthereumAddress):
        """Get the native balance in wei"""
        return self.web3.eth.get_balance(address)

    def get_native_balance_eth(self, address: EthereumAddress):
        """Get the native balance in ether"""
        balance_wei = self.get_native_balance_wei(address)
        balance_ether = self.web3.from_wei(balance_wei, "ether")
        return balance_ether

    def estimate_gas(self, built_method: Callable, tx_params: Dict[str, Union[str, int]]) -> int:
        """Estimate gas for a contract function call."""
        from_address = tx_params["from"]
        value = int(tx_params.get("value", 0))

        if self.is_contract(str(from_address)):
            logger.debug(f"Skipping gas estimation for contract caller {str(from_address)[:10]}...")
            return 0

        try:
            estimated_gas = built_method.estimate_gas({"from": from_address, "value": value})
            return int(estimated_gas * 1.1)
        except Exception as e:
            logger.warning(f"Gas estimation failed: {e}")
            return 500_000

    def calculate_transaction_params(
        self, built_method: Optional[Callable], tx_params: Dict[str, Union[str, int]]
    ) -> Dict[str, Union[str, int]]:
        """Calculate transaction parameters for a contract function call or native transfer."""
        # Baseline parameters
        params = {
            "from": tx_params["from"],
            "to": tx_params.get("to"),
            "value": tx_params.get("value", 0),
            "nonce": self.web3.eth.get_transaction_count(tx_params["from"]),
        }

        # Determine gas
        if built_method:
            # Contract function call
            params["gas"] = self.estimate_gas(built_method, tx_params)
        elif "gas" in tx_params:
            # Manual gas override
            params["gas"] = tx_params["gas"]
        else:
            # Native transfer - dynamic estimation
            try:
                # web3.eth.estimate_gas returns gas for the dict it receives
                est_params = {
                    "from": params["from"],
                    "to": params["to"],
                    "value": params["value"]
                }
                # Remove None 'to' for contract creation simulation if needed, but usually send() has to
                if not est_params["to"]:
                    est_params.pop("to")

                estimated = self.web3.eth.estimate_gas(est_params)
                # Apply 10% buffer for safety
                params["gas"] = int(estimated * 1.1)
                logger.debug(f"[GAS] Estimated native transfer gas: {params['gas']} (raw: {estimated})")
            except Exception as e:
                logger.debug(f"[GAS] Native estimation failed, fallback to 21000: {e}")
                params["gas"] = 21_000

        # Add EIP-1559 or Legacy fees
        params.update(self.get_suggested_fees())
        return params

    def get_suggested_fees(self) -> Dict[str, int]:
        """Calculate suggested fees for a transaction (EIP-1559 or legacy)."""
        try:
            # Check for EIP-1559 support
            latest_block = self.web3.eth.get_block("latest")
            base_fee = latest_block.get("baseFeePerGas")

            if base_fee is not None:
                # EIP-1559 logic
                max_priority_fee = int(self.web3.eth.max_priority_fee)

                # Gnosis specific: ensure min priority fee (critical for validation)
                if self.chain.name.lower() == "gnosis":
                    if max_priority_fee < 1:
                        max_priority_fee = 1  # Network minimum is 1 wei

                # Global minimum for EIP-1559
                if max_priority_fee < 1:
                    max_priority_fee = 1

                # Buffer max_fee to handle base fee expansion
                max_fee = int(base_fee * 1.5) + max_priority_fee

                return {
                    "maxFeePerGas": max_fee,
                    "maxPriorityFeePerGas": max_priority_fee
                }
        except Exception as e:
            logger.debug(f"Failed to calculate EIP-1559 fees: {e}, falling back to legacy")

        # Legacy fallback
        return {"gasPrice": self.web3.eth.gas_price}

    def wait_for_no_pending_tx(
        self, from_address: EthereumAddress, max_wait_seconds: int = 60, poll_interval: float = 2.0
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

    def get_token_address(self, token_name: str) -> Optional[EthereumAddress]:
        """Get token address by name"""
        return self.chain.get_token_address(token_name)

    def get_contract_address(self, contract_name: str) -> Optional[EthereumAddress]:
        """Get contract address by name from the chain's contracts mapping."""
        return self.chain.contracts.get(contract_name)

    def reset_rpc_failure_counts(self):
        """Reset RPC failure tracking. Call periodically to allow retrying failed RPCs."""
        self._rpc_failure_counts.clear()
        logger.debug("Reset RPC failure counts")
