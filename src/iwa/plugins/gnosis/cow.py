"""CoW Swap interaction."""

# ruff: noqa: E402

import time
import warnings
from typing import TYPE_CHECKING, Any

warnings.filterwarnings("ignore", message="Pydantic serializer warnings:")
warnings.filterwarnings(
    "ignore", message="This AsyncLimiter instance is being re-used across loops.*"
)

from enum import Enum

import requests
from eth_account import Account
from eth_account.signers.local import LocalAccount
from eth_typing.evm import ChecksumAddress
from web3 import Web3
from web3.types import Wei

from iwa.core.chain import SupportedChain
from iwa.core.types import EthereumAddress
from iwa.core.utils import configure_logger

logger = configure_logger()

from iwa.plugins.gnosis.cow_utils import get_cowpy_module


# Type hints for cowdao_cowpy types (only used for type checking)
if TYPE_CHECKING:
    from cowdao_cowpy.common.chains import Chain
    from cowdao_cowpy.cow.swap import CompletedOrder
    from cowdao_cowpy.order_book.config import Envs

COW_API_URLS = {100: "https://api.cow.fi/xdai"}
ORDER_ENDPOINT_URL = "/api/v1/orders/"
COW_EXPLORER_URL = "https://explorer.cow.fi/gc/orders/"
HTTP_OK = 200

COWSWAP_GPV2_VAULT_RELAYER_ADDRESS = EthereumAddress("0xC92E8bdf79f0507f65a392b0ab4667716BFE0110")
MAX_APPROVAL = 2**256 - 1

# Placeholders for cowdao_cowpy functions/classes to allow patching in tests
swap_tokens = None
get_order_quote = None
post_order = None
sign_order = None
CompletedOrder = None
OrderQuoteRequest = None
OrderQuoteSide1 = None
OrderQuoteSide3 = None
OrderQuoteSideKindBuy = None
OrderQuoteSideKindSell = None
TokenAmount = None
Order = None
PreSignSignature = None
SigningScheme = None
Chain = None
SupportedChainId = None
OrderBookApi = None
OrderBookAPIConfigFactory = None


class OrderType(Enum):
    """Order types."""

    SELL = "sell"
    BUY = "buy"


class CowSwap:
    """Simple CoW Swap integration using CoW Protocol's public API.

    Handles token swaps on Gnosis Chain (and others) using CoW Protocol.
    Uses lazy loading for `cowdao-cowpy` dependencies to improve startup time
    and avoid asyncio conflicts during import.
    """

    env: str = "prod"

    def __init__(self, private_key_or_signer: str | LocalAccount, chain: SupportedChain):
        """Initialize CowSwap."""
        if isinstance(private_key_or_signer, str):
            self.account = Account.from_key(private_key_or_signer)
        else:
            self.account = private_key_or_signer
        self.chain = chain
        supported_chain_id_cls = get_cowpy_module("SupportedChainId")
        self.supported_chain_id = supported_chain_id_cls(chain.chain_id)
        self.cow_chain = self.get_chain()
        self.cowswap_api_url = COW_API_URLS.get(chain.chain_id)
        order_book_api_cls = get_cowpy_module("OrderBookApi")
        order_book_api_config_factory_cls = get_cowpy_module("OrderBookAPIConfigFactory")
        self.order_book_api = order_book_api_cls(
            order_book_api_config_factory_cls.get_config(self.env, chain.chain_id)
        )

    def get_chain(self) -> "Chain":
        """Get the Chain enum based on the supported chain ID."""
        chain_cls = get_cowpy_module("Chain")
        for chain in chain_cls:
            if chain.value[0] == self.supported_chain_id:
                return chain
        raise ValueError(f"Unsupported SupportedChainId: {self.supported_chain_id}")

    @staticmethod
    async def check_cowswap_order(order: "CompletedOrder") -> dict | None:
        """Check if a CowSwap order has been executed by polling the Explorer API.

        Args:
            order: The executed order object containing UID and URL.

        Returns:
            dict | None: The full order data if executed successfully, None otherwise.

        """
        import asyncio
        logger.info(f"Checking order status for UID: {order.uid}")

        max_retries = 8
        sleep_between_retries = 30
        retries = 0

        while retries < max_retries:
            retries += 1

            try:
                # Use a thread executor for blocking requests.get
                loop = asyncio.get_event_loop()
                response = await loop.run_in_executor(None, lambda: requests.get(order.url, timeout=60))
            except Exception as e:
                logger.warning(f"Error checking order status: {e}")
                await asyncio.sleep(sleep_between_retries)
                continue

            if response.status_code != HTTP_OK:
                logger.debug(
                    f"Order status check {retries}/{max_retries}: HTTP {response.status_code}. Retry in {sleep_between_retries}s"
                )
                await asyncio.sleep(sleep_between_retries)
                continue

            order_data = response.json()


            status = order_data.get("status", "unknown")
            valid_to = int(order_data.get("validTo", 0))
            current_time = int(time.time())

            if status == "expired" or (valid_to > 0 and current_time > valid_to):
                logger.error(f"Order expired without execution (Status: {status}, ValidTo: {valid_to}, Now: {current_time}).")
                return None

            executed_sell = int(order_data.get("executedSellAmount", "0"))
            executed_buy = int(order_data.get("executedBuyAmount", "0"))

            if executed_sell > 0 or executed_buy > 0:
                logger.info("Order executed successfully.")
                sell_price = order_data.get("quote", {}).get("sellTokenPrice", None)
                buy_price = order_data.get("quote", {}).get("buyTokenPrice", None)

                if sell_price is not None:
                    logger.debug(f"Sell price: ${float(sell_price):.2f}")

                if buy_price is not None:
                    logger.debug(f"Buy price: ${float(buy_price):.2f}")

                return order_data

            logger.info(
                f"Order pending... ({retries}/{max_retries}). Retry in {sleep_between_retries}s"
            )
            await asyncio.sleep(sleep_between_retries)

        logger.warning("Max retries reached. Order status unknown.")
        return None

    async def swap(
        self,
        amount_wei: Wei,
        sell_token_name: str,
        buy_token_name: str,
        safe_address: ChecksumAddress | None = None,
        order_type: OrderType = OrderType.SELL,
    ) -> dict | None:
        """Execute a token swap on CoW Protocol.

        Args:
            amount_wei: Amount to swap in Wei.
            sell_token_name: Symbol of token to sell.
            buy_token_name: Symbol of token to buy.
            safe_address: Optional address of Safe if this is a Multisig swap.
            order_type: SELL or BUY.

        Returns:
            dict | None: The order data if swap initiated and verified successfully.

        """
        amount_eth = Web3.from_wei(amount_wei, "ether")

        if order_type == OrderType.BUY:
            logger.info(
                f"Swapping {sell_token_name} to {amount_eth:.4f} {buy_token_name} on {self.chain.name}..."
            )

        else:
            logger.info(
                f"Swapping {amount_eth:.4f} {sell_token_name} to {buy_token_name} on {self.chain.name}..."
            )

        valid_to = int(time.time()) + 3 * 60  # Order valid for 3 minutes

        # Check if they are patched (testing context)
        global swap_tokens
        if swap_tokens is not None:
            # If patched, we use the patched version
            swap_function = (
                self.swap_tokens_to_exact_tokens if order_type == OrderType.BUY else swap_tokens
            )
        else:
            # Normal execution, lazy load
            actual_swap_tokens = get_cowpy_module("swap_tokens")
            swap_function = (
                self.swap_tokens_to_exact_tokens
                if order_type == OrderType.BUY
                else actual_swap_tokens
            )

        try:
            order = await swap_function(
                amount=amount_wei,
                account=self.account,
                chain=self.cow_chain,
                sell_token=self.chain.get_token_address(sell_token_name),
                buy_token=self.chain.get_token_address(buy_token_name),
                safe_address=safe_address,
                valid_to=valid_to,
                env=self.env,
                slippage_tolerance=0.005,
                partially_fillable=False,
            )

            logger.info(f"Swap order placed: {COW_EXPLORER_URL}{order.uid.root}")

            return await self.check_cowswap_order(order)

        except Exception as e:
            logger.error(f"Error during token swap: {e}")
            return None

    async def get_max_sell_amount_wei(
        self,
        amount_wei: Wei,
        sell_token: ChecksumAddress,
        buy_token: ChecksumAddress,
        safe_address: ChecksumAddress | None = None,
        app_data: str | None = None,
        env: "Envs" = "prod",
        slippage_tolerance: float = 0.005,
    ) -> int:
        """Calculate the estimated sell amount needed to buy a fixed amount of tokens.

        Queries the CoW Protocol Order Book API for a quote.

        Args:
            amount_wei: Desired buy amount in Wei.
            sell_token: Address of token to sell.
            buy_token: Address of token to buy.
            safe_address: Optional Safe address context.
            app_data: Optional app data hash.
            env: API environment ("prod" or "staging").
            slippage_tolerance: Tolerance percentage (default 0.5%).

        Returns:
            int: Estimated sell amount in Wei (including slippage buffer).

        """
        if app_data is None:
            app_data = get_cowpy_module("DEFAULT_APP_DATA_HASH")

        # In testing context, these might be patched
        global \
            get_order_quote, \
            OrderQuoteRequest, \
            OrderQuoteSide3, \
            OrderQuoteSideKindBuy, \
            TokenAmount, \
            SupportedChainId, \
            OrderBookApi, \
            OrderBookAPIConfigFactory

        _get_order_quote = get_order_quote or get_cowpy_module("get_order_quote")
        _order_quote_request_cls = OrderQuoteRequest or get_cowpy_module("OrderQuoteRequest")
        _order_quote_side_cls = OrderQuoteSide3 or get_cowpy_module("OrderQuoteSide3")
        _order_quote_side_kind_buy_cls = OrderQuoteSideKindBuy or get_cowpy_module(
            "OrderQuoteSideKindBuy"
        )
        _token_amount_cls = TokenAmount or get_cowpy_module("TokenAmount")
        _supported_chain_id_cls = SupportedChainId or get_cowpy_module("SupportedChainId")
        _order_book_api_cls = OrderBookApi or get_cowpy_module("OrderBookApi")
        _order_book_api_config_factory_cls = OrderBookAPIConfigFactory or get_cowpy_module(
            "OrderBookAPIConfigFactory"
        )

        chain_id = _supported_chain_id_cls(self.cow_chain.value[0])
        order_book_api = _order_book_api_cls(
            _order_book_api_config_factory_cls.get_config(env, chain_id)
        )

        order_quote_request = _order_quote_request_cls(
            sellToken=sell_token,
            buyToken=buy_token,
            from_=safe_address if safe_address is not None else self.account._address,
            appData=app_data,
        )

        order_side = _order_quote_side_cls(
            kind=_order_quote_side_kind_buy_cls.buy,
            buyAmountAfterFee=_token_amount_cls(str(amount_wei)),
        )

        order_quote = await _get_order_quote(order_quote_request, order_side, order_book_api)

        sell_amount_wei = int(int(order_quote.quote.sellAmount.root) * (1.0 + slippage_tolerance))
        return sell_amount_wei

    async def get_max_buy_amount_wei(
        self,
        sell_amount_wei: Wei,
        sell_token: ChecksumAddress,
        buy_token: ChecksumAddress,
        safe_address: ChecksumAddress | None = None,
        app_data: str | None = None,
        env: "Envs" = "prod",
        slippage_tolerance: float = 0.005,
    ) -> int:
        """Calculate the maximum buy amount for a given sell amount.

        Args:
            sell_amount_wei: Amount of sell token in wei
            sell_token: Sell token address
            buy_token: Buy token address
            safe_address: Optional Safe address
            app_data: Optional app data hash
            env: CowSwap environment
            slippage_tolerance: Slippage tolerance

        Returns:
            Maximum buy amount in wei (after slippage)

        """
        if app_data is None:
            app_data = get_cowpy_module("DEFAULT_APP_DATA_HASH")

        global \
            get_order_quote, \
            OrderQuoteRequest, \
            OrderQuoteSide1, \
            OrderQuoteSideKindSell, \
            TokenAmount, \
            SupportedChainId, \
            OrderBookApi, \
            OrderBookAPIConfigFactory

        _get_order_quote = get_order_quote or get_cowpy_module("get_order_quote")
        _order_quote_request_cls = OrderQuoteRequest or get_cowpy_module("OrderQuoteRequest")
        _order_quote_side_cls = OrderQuoteSide1 or get_cowpy_module("OrderQuoteSide1")
        _order_quote_side_kind_sell_cls = OrderQuoteSideKindSell or get_cowpy_module(
            "OrderQuoteSideKindSell"
        )
        _token_amount_cls = TokenAmount or get_cowpy_module("TokenAmount")
        _supported_chain_id_cls = SupportedChainId or get_cowpy_module("SupportedChainId")
        _order_book_api_cls = OrderBookApi or get_cowpy_module("OrderBookApi")
        _order_book_api_config_factory_cls = OrderBookAPIConfigFactory or get_cowpy_module(
            "OrderBookAPIConfigFactory"
        )

        chain_id = _supported_chain_id_cls(self.cow_chain.value[0])
        order_book_api = _order_book_api_cls(
            _order_book_api_config_factory_cls.get_config(env, chain_id)
        )

        order_quote_request = _order_quote_request_cls(
            sellToken=sell_token,
            buyToken=buy_token,
            from_=safe_address if safe_address is not None else self.account._address,
            appData=app_data,
        )

        order_side = _order_quote_side_cls(
            kind=_order_quote_side_kind_sell_cls.sell,
            sellAmountBeforeFee=_token_amount_cls(str(sell_amount_wei)),
        )

        order_quote = await _get_order_quote(order_quote_request, order_side, order_book_api)

        # Apply slippage (reduce buy amount)
        buy_amount_wei = int(int(order_quote.quote.buyAmount.root) * (1.0 - slippage_tolerance))
        return buy_amount_wei

    @staticmethod
    async def swap_tokens_to_exact_tokens(
        amount: Wei,
        account: LocalAccount,
        chain: "Chain",
        sell_token: ChecksumAddress,
        buy_token: ChecksumAddress,
        safe_address: ChecksumAddress | None = None,
        app_data: str | None = None,
        valid_to: int | None = None,
        env: "Envs" = "prod",
        slippage_tolerance: float = 0.005,
        partially_fillable: bool = False,
    ) -> "CompletedOrder":
        """Execute a 'Buy' order (Exact Output) on CoW Protocol.

        This is a modified version of `cowdao_cowpy.cow.swap.swap_tokens` tailored
        for 'Buy' orders where the buy amount is fixed and sell amount is estimated.

        Args:
            amount: Exact amount of tokens to buy in Wei.
            account: The local account signing the order.
            chain: The chain instance.
            sell_token: Address of token to sell.
            buy_token: Address of token to buy.
            safe_address: Optional Safe address.
            app_data: App data hash.
            valid_to: Order expiration timestamp.
            env: API environment.
            slippage_tolerance: Slippage tolerance.
            partially_fillable: Whether order can be partially filled.

        Returns:
            CompletedOrder: The created order with UID and explorer link.

        """
        # Lazy imports
        if app_data is None:
            app_data = get_cowpy_module("DEFAULT_APP_DATA_HASH")

        global \
            get_order_quote, \
            OrderQuoteRequest, \
            OrderQuoteSide3, \
            OrderQuoteSideKindBuy, \
            TokenAmount, \
            SupportedChainId, \
            OrderBookApi, \
            OrderBookAPIConfigFactory, \
            Order, \
            PreSignSignature, \
            SigningScheme, \
            sign_order, \
            post_order, \
            CompletedOrder

        _get_order_quote = get_order_quote or get_cowpy_module("get_order_quote")
        _order_quote_request_cls = OrderQuoteRequest or get_cowpy_module("OrderQuoteRequest")
        _order_quote_side_cls = OrderQuoteSide3 or get_cowpy_module("OrderQuoteSide3")
        _order_quote_side_kind_buy_cls = OrderQuoteSideKindBuy or get_cowpy_module(
            "OrderQuoteSideKindBuy"
        )
        _token_amount_cls = TokenAmount or get_cowpy_module("TokenAmount")
        _supported_chain_id_cls = SupportedChainId or get_cowpy_module("SupportedChainId")
        _order_book_api_cls = OrderBookApi or get_cowpy_module("OrderBookApi")
        _order_book_api_config_factory_cls = OrderBookAPIConfigFactory or get_cowpy_module(
            "OrderBookAPIConfigFactory"
        )
        _order_cls = Order or get_cowpy_module("Order")
        _pre_sign_signature_cls = PreSignSignature or get_cowpy_module("PreSignSignature")
        _signing_scheme_cls = SigningScheme or get_cowpy_module("SigningScheme")
        _sign_order = sign_order or get_cowpy_module("sign_order")
        _post_order = post_order or get_cowpy_module("post_order")
        _completed_order_cls = CompletedOrder or get_cowpy_module("CompletedOrder")

        chain_id = _supported_chain_id_cls(chain.value[0])
        order_book_api = _order_book_api_cls(
            _order_book_api_config_factory_cls.get_config(env, chain_id)
        )

        order_quote_request = _order_quote_request_cls(
            sellToken=sell_token,
            buyToken=buy_token,
            from_=safe_address if safe_address is not None else account._address,  # type: ignore # pyright doesn't recognize `populate_by_name=True`.
            appData=app_data,
        )

        # This is one of the changes
        order_side = _order_quote_side_cls(
            kind=_order_quote_side_kind_buy_cls.buy,
            buyAmountAfterFee=_token_amount_cls(str(amount)),
        )

        order_quote = await _get_order_quote(order_quote_request, order_side, order_book_api)

        sell_amount_wei = int(int(order_quote.quote.sellAmount.root) * (1.0 + slippage_tolerance))

        min_valid_to = (
            order_quote.quote.validTo
            if valid_to is None
            else min(order_quote.quote.validTo, valid_to)
        )

        order_obj = _order_cls(
            sell_token=sell_token,
            buy_token=buy_token,
            receiver=safe_address if safe_address is not None else account.address,
            valid_to=min_valid_to,
            app_data=app_data,
            sell_amount=str(sell_amount_wei),
            buy_amount=str(
                amount
            ),  # Since it is a buy order, the buyAmountBeforeFee is the same as the buyAmount.
            fee_amount="0",  # CoW Swap does not charge fees.
            kind=_order_quote_side_kind_buy_cls.buy.value,  # This is another change
            sell_token_balance="erc20",
            buy_token_balance="erc20",
            partially_fillable=partially_fillable,
        )

        signature = (
            _pre_sign_signature_cls(
                scheme=_signing_scheme_cls.PRESIGN,
                data=safe_address,
            )
            if safe_address is not None
            else _sign_order(chain, account, order_obj)
        )
        order_uid = await _post_order(account, safe_address, order_obj, signature, order_book_api)
        order_link = order_book_api.get_order_link(order_uid)
        return _completed_order_cls(uid=order_uid, url=order_link)
