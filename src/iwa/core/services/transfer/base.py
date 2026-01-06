"""Transfer service base module."""

from typing import TYPE_CHECKING, Optional

from loguru import logger
from web3.types import Wei

from iwa.core.chain import ChainInterfaces
from iwa.core.constants import NATIVE_CURRENCY_ADDRESS
from iwa.core.models import Config, EthereumAddress
from iwa.core.pricing import PriceService

if TYPE_CHECKING:
    from iwa.core.keys import KeyStorage
    from iwa.core.services.account import AccountService
    from iwa.core.services.balance import BalanceService
    from iwa.core.services.safe import SafeService
    from iwa.core.services.transaction import TransactionService


# Coingecko IDs for tokens and native currencies
TOKEN_COINGECKO_IDS = {
    "XDAI": "xdai",
    "ETH": "ethereum",
    "OLAS": "autonolas",
    "USDC": "usdc",
    "WXDAI": "xdai",
    "SDAI": "savings-xdai",
    "EURE": "monerium-eur-money",
}

CHAIN_COINGECKO_IDS = {
    "gnosis": "dai",
    "ethereum": "ethereum",
    "base": "ethereum",
}


class TransferServiceBase:
    """Base class for TransferService with shared helpers."""

    def __init__(
        self,
        key_storage: "KeyStorage",
        account_service: "AccountService",
        balance_service: "BalanceService",
        safe_service: "SafeService",
        transaction_service: "TransactionService",
    ):
        """Initialize TransferService."""
        self.key_storage = key_storage
        self.account_service = account_service
        self.balance_service = balance_service
        self.safe_service = safe_service
        self.transaction_service = transaction_service

    def _resolve_destination(self, to_address_or_tag: str) -> tuple[Optional[str], Optional[str]]:
        """Resolve destination address and tag.

        Returns:
            Tuple of (address, tag) or (None, None) if invalid.

        """
        to_account = self.account_service.resolve_account(to_address_or_tag)
        if to_account:
            return to_account.address, getattr(to_account, "tag", None)

        try:
            to_address = EthereumAddress(to_address_or_tag)
            # Try to find tag in whitelist
            to_tag = self._resolve_whitelist_tag(to_address)
            return to_address, to_tag
        except ValueError:
            logger.error(f"Invalid destination address: {to_address_or_tag}")
            return None, None

    def _resolve_whitelist_tag(self, address: str) -> Optional[str]:
        """Resolve tag from whitelist for an address."""
        config = Config()
        if config.core and config.core.whitelist:
            try:
                target_addr = EthereumAddress(address)
                for name, addr in config.core.whitelist.items():
                    if addr == target_addr:
                        return name
            except ValueError:
                pass
        return None

    def _calculate_gas_info(
        self, receipt: Optional[dict], chain_name: str
    ) -> tuple[Optional[int], Optional[float]]:
        """Calculate gas cost and gas value in EUR from transaction receipt.

        Args:
            receipt: Transaction receipt containing gasUsed and effectiveGasPrice.
            chain_name: Name of the chain for price lookup.

        Returns:
            Tuple of (gas_cost_wei, gas_value_eur) or (None, None) if unavailable.

        """
        if not receipt:
            return None, None

        try:
            gas_used = receipt.get("gasUsed", 0)
            effective_gas_price = receipt.get("effectiveGasPrice", 0)
            gas_cost_wei = gas_used * effective_gas_price

            # Get native token price
            coingecko_id = CHAIN_COINGECKO_IDS.get(chain_name, "ethereum")
            price_service = PriceService()
            native_price_eur = price_service.get_token_price(coingecko_id, "eur")

            gas_value_eur = None
            if native_price_eur and gas_cost_wei > 0:
                gas_cost_eth = gas_cost_wei / 10**18
                gas_value_eur = gas_cost_eth * native_price_eur

            return gas_cost_wei, gas_value_eur
        except Exception as e:
            logger.warning(f"Failed to calculate gas info: {e}")
            return None, None

    def _get_token_price_info(
        self, token_symbol: str, amount_wei: Wei, chain_name: str
    ) -> tuple[Optional[float], Optional[float]]:
        """Calculate token price and total value in EUR.

        Args:
            token_symbol: Token symbol (e.g. 'OLAS', 'ETH')
            amount_wei: Amount in wei
            chain_name: Chain name

        Returns:
            Tuple of (price_eur, value_eur) or (None, None) if unavailable.

        """
        try:
            # Map symbol to coingecko id
            symbol_upper = token_symbol.upper()
            cg_id = TOKEN_COINGECKO_IDS.get(symbol_upper)
            if not cg_id:
                # Try name mapping if it's native signal
                if symbol_upper in ["NATIVE", "TOKEN"]:
                    cg_id = CHAIN_COINGECKO_IDS.get(chain_name.lower())

            if not cg_id:
                return None, None

            price_service = PriceService()
            price_eur = price_service.get_token_price(cg_id, "eur")

            if price_eur is None:
                return None, None

            # Get decimals for value calculation
            interface = ChainInterfaces().get(chain_name)
            decimals = 18
            if symbol_upper not in ["NATIVE", "TOKEN", "XDAI", "ETH"]:
                token_address = interface.chain.get_token_address(token_symbol)
                if token_address:
                    decimals = interface.get_token_decimals(token_address)

            value_eur = (amount_wei / 10**decimals) * price_eur
            return price_eur, value_eur
        except Exception as e:
            logger.warning(f"Failed to calculate token price info for {token_symbol}: {e}")
            return None, None

    def _is_whitelisted_destination(self, to_address: str) -> bool:
        """Check if destination address is whitelisted.

        An address is whitelisted if it's:
        1. One of our own accounts (from wallets.json)
        2. In the explicit whitelist in config.yaml [core.whitelist]

        Returns:
            True if allowed, False if blocked.

        """
        # Normalize address for comparison
        try:
            target_addr = EthereumAddress(to_address)
        except ValueError:
            logger.error(f"Invalid address format: {to_address}")
            return False

        # Check 1: Is it one of our own wallets?
        if self.account_service.resolve_account(to_address):
            return True

        # Check 2: Is it in the config whitelist?
        config = Config()
        if config.core and config.core.whitelist:
            if target_addr in config.core.whitelist.values():
                return True

        # Not in whitelist - block transaction
        logger.error(
            f"SECURITY: Destination {to_address} is NOT whitelisted. "
            "Transaction blocked. Add to config.yaml [core.whitelist] to allow."
        )
        return False

    def _is_supported_token(self, token_address_or_name: str, chain_name: str) -> bool:
        """Validate that the token is supported on this chain.

        Supported tokens are:
        1. Native currency
        2. Tokens defined in chain.tokens (defaults + custom_tokens)

        Returns:
            True if token is supported, False otherwise.

        """
        # Native currency is always allowed
        if token_address_or_name.lower() in ("native", NATIVE_CURRENCY_ADDRESS.lower()):
            return True

        chain_interface = ChainInterfaces().get(chain_name)
        supported_tokens = chain_interface.tokens

        # Check by name (e.g., "OLAS")
        if token_address_or_name.upper() in supported_tokens:
            return True

        # Check by address
        try:
            token_addr = EthereumAddress(token_address_or_name)
            if token_addr in supported_tokens.values():
                return True
        except ValueError:
            pass  # Not a valid address, already checked by name

        # Token not supported
        supported_list = ", ".join(supported_tokens.keys())
        logger.error(
            f"SECURITY: Token '{token_address_or_name}' is NOT supported on {chain_name}. "
            f"Supported tokens: {supported_list}. "
            "Add to config.yaml [core.custom_tokens] to allow."
        )
        return False

    def _resolve_token_symbol(
        self, token_address: str, token_address_or_name: str, chain_interface
    ) -> str:
        """Resolve token symbol for logging."""
        if token_address == NATIVE_CURRENCY_ADDRESS:
            return chain_interface.chain.native_currency

        if not token_address_or_name.startswith("0x"):
            return token_address_or_name

        for name, addr in chain_interface.tokens.items():
            if addr == token_address:
                return name

        return token_address_or_name
