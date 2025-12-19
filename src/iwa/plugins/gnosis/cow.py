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
from iwa.core.utils import configure_logger

logger = configure_logger()

# Lazy import cache for cowdao_cowpy modules to avoid asyncio.run() conflict
_cowpy_cache: dict[str, Any] = {}


def _get_cowpy_module(name: str) -> Any:
    """Lazily import cowdao_cowpy submodules to avoid asyncio conflict at import time."""
    if name not in _cowpy_cache:
        if name == "DEFAULT_APP_DATA_HASH":
            from cowdao_cowpy.app_data.utils import DEFAULT_APP_DATA_HASH
            _cowpy_cache[name] = DEFAULT_APP_DATA_HASH
        elif name == "Chain":
            from cowdao_cowpy.common.chains import Chain
            _cowpy_cache[name] = Chain
        elif name == "SupportedChainId":
            from cowdao_cowpy.common.chains import SupportedChainId
            _cowpy_cache[name] = SupportedChainId
        elif name == "Order":
            from cowdao_cowpy.contracts.order import Order
            _cowpy_cache[name] = Order
        elif name == "PreSignSignature":
            from cowdao_cowpy.contracts.sign import PreSignSignature
            _cowpy_cache[name] = PreSignSignature
        elif name == "SigningScheme":
            from cowdao_cowpy.contracts.sign import SigningScheme
            _cowpy_cache[name] = SigningScheme
        elif name == "CompletedOrder":
            from cowdao_cowpy.cow.swap import CompletedOrder
            _cowpy_cache[name] = CompletedOrder
        elif name == "get_order_quote":
            from cowdao_cowpy.cow.swap import get_order_quote
            _cowpy_cache[name] = get_order_quote
        elif name == "post_order":
            from cowdao_cowpy.cow.swap import post_order
            _cowpy_cache[name] = post_order
        elif name == "sign_order":
            from cowdao_cowpy.cow.swap import sign_order
            _cowpy_cache[name] = sign_order
        elif name == "swap_tokens":
            from cowdao_cowpy.cow.swap import swap_tokens
            _cowpy_cache[name] = swap_tokens
        elif name == "OrderBookApi":
            from cowdao_cowpy.order_book.api import OrderBookApi
            _cowpy_cache[name] = OrderBookApi
        elif name == "Envs":
            from cowdao_cowpy.order_book.config import Envs
            _cowpy_cache[name] = Envs
        elif name == "OrderBookAPIConfigFactory":
            from cowdao_cowpy.order_book.config import OrderBookAPIConfigFactory
            _cowpy_cache[name] = OrderBookAPIConfigFactory
        elif name == "OrderQuoteRequest":
            from cowdao_cowpy.order_book.generated.model import OrderQuoteRequest
            _cowpy_cache[name] = OrderQuoteRequest
        elif name == "OrderQuoteSide3":
            from cowdao_cowpy.order_book.generated.model import OrderQuoteSide3
            _cowpy_cache[name] = OrderQuoteSide3
        elif name == "OrderQuoteSideKindBuy":
            from cowdao_cowpy.order_book.generated.model import OrderQuoteSideKindBuy
            _cowpy_cache[name] = OrderQuoteSideKindBuy
        elif name == "TokenAmount":
            from cowdao_cowpy.order_book.generated.model import TokenAmount
            _cowpy_cache[name] = TokenAmount
        elif name == "OrderQuoteSide1":
            from cowdao_cowpy.order_book.generated.model import OrderQuoteSide1
            _cowpy_cache[name] = OrderQuoteSide1
        elif name == "OrderQuoteSideKindSell":
            from cowdao_cowpy.order_book.generated.model import OrderQuoteSideKindSell
            _cowpy_cache[name] = OrderQuoteSideKindSell
        else:
            raise ValueError(f"Unknown cowpy module: {name}")
    return _cowpy_cache[name]


# Type hints for cowdao_cowpy types (only used for type checking)
if TYPE_CHECKING:
    from cowdao_cowpy.common.chains import Chain
    from cowdao_cowpy.cow.swap import CompletedOrder
    from cowdao_cowpy.order_book.config import Envs

COW_API_URLS = {100: "https://api.cow.fi/xdai"}
ORDER_ENDPOINT_URL = "/api/v1/orders/"
COW_EXPLORER_URL = "https://explorer.cow.fi/gc/orders/"
HTTP_OK = 200

COWSWAP_GPV2_VAULT_RELAYER_ADDRESS = "0xC92E8bdf79f0507f65a392b0ab4667716BFE0110"
MAX_APPROVAL = 2**256 - 1


class OrderType(Enum):
    """Order types."""

    SELL = "sell"
    BUY = "buy"


class CowSwap:
    """Simple CoW Swap integration using CoW Protocol's public API."""

    env: str = "prod"

    def __init__(self, private_key_or_signer: str | LocalAccount, chain: SupportedChain):
        """Initialize CowSwap."""
        if isinstance(private_key_or_signer, str):
            self.account = Account.from_key(private_key_or_signer)
        else:
            self.account = private_key_or_signer
        self.chain = chain
        SupportedChainId = _get_cowpy_module("SupportedChainId")
        self.supported_chain_id = SupportedChainId(chain.chain_id)
        self.cow_chain = self.get_chain()
        self.cowswap_api_url = COW_API_URLS.get(chain.chain_id)
        OrderBookApi = _get_cowpy_module("OrderBookApi")
        OrderBookAPIConfigFactory = _get_cowpy_module("OrderBookAPIConfigFactory")
        self.order_book_api = OrderBookApi(
            OrderBookAPIConfigFactory.get_config(self.env, chain.chain_id)
        )

    def get_chain(self) -> "Chain":
        """Get the Chain enum based on the supported chain ID."""
        Chain = _get_cowpy_module("Chain")
        for chain in Chain:
            if chain.value[0] == self.supported_chain_id:
                return chain
        raise ValueError(f"Unsupported SupportedChainId: {self.supported_chain_id}")

    @staticmethod
    def check_cowswap_order(order: "CompletedOrder") -> bool:
        """Check if a Cowswap order has been executed"""
        logger.info("Checking order status")

        max_retries = 8
        sleep_between_retries = 30
        retries = 0

        while retries < max_retries:
            retries += 1

            response = requests.get(order.url, timeout=60)

            if response.status_code != HTTP_OK:
                logger.info(
                    f"Order is not ready yet: {response.status_code}. Checking again in {sleep_between_retries}s"
                )
                time.sleep(sleep_between_retries)
                continue

            order_data = response.json()
            status = order_data.get("status", "unknown")
            if status == "expired":
                logger.error("Order has expired.")
                return False

            executed_sell = int(order_data.get("executedSellAmount", "0"))
            executed_buy = int(order_data.get("executedBuyAmount", "0"))

            if executed_sell > 0 or executed_buy > 0:
                logger.info("Order executed")
                sell_price = order_data.get("quote", {}).get("sellTokenPrice", None)
                buy_price = order_data.get("quote", {}).get("buyTokenPrice", None)

                if sell_price is not None:
                    logger.info(f"Sell price was ${float(sell_price):.2f}")

                if buy_price is not None:
                    logger.info(f"Buy price was ${float(buy_price):.2f}")

                return True

            logger.info(
                f"Order has not been executed yet. Checking again in {sleep_between_retries}s"
            )
            time.sleep(sleep_between_retries)

        logger.error("Max retries reached. Could not verify the order.")
        return False

    async def swap(
        self,
        amount_wei: Wei,
        sell_token_name: str,
        buy_token_name: str,
        safe_address: ChecksumAddress | None = None,
        order_type: OrderType = OrderType.SELL,
    ) -> bool:
        """Swap tokens."""
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

        swap_tokens = _get_cowpy_module("swap_tokens")
        swap_function = (
            self.swap_tokens_to_exact_tokens if order_type == OrderType.BUY else swap_tokens
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

            return self.check_cowswap_order(order)

        except Exception as e:
            logger.error(f"Error during token swap: {e}")
            return False

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
        """Calculate the maximum sell amount needed to buy a fixed amount of tokens."""
        if app_data is None:
            app_data = _get_cowpy_module("DEFAULT_APP_DATA_HASH")
        SupportedChainId = _get_cowpy_module("SupportedChainId")
        OrderBookApi = _get_cowpy_module("OrderBookApi")
        OrderBookAPIConfigFactory = _get_cowpy_module("OrderBookAPIConfigFactory")
        OrderQuoteRequest = _get_cowpy_module("OrderQuoteRequest")
        OrderQuoteSide3 = _get_cowpy_module("OrderQuoteSide3")
        OrderQuoteSideKindBuy = _get_cowpy_module("OrderQuoteSideKindBuy")
        TokenAmount = _get_cowpy_module("TokenAmount")
        get_order_quote = _get_cowpy_module("get_order_quote")

        chain_id = SupportedChainId(self.cow_chain.value[0])
        order_book_api = OrderBookApi(OrderBookAPIConfigFactory.get_config(env, chain_id))

        order_quote_request = OrderQuoteRequest(
            sellToken=sell_token,
            buyToken=buy_token,
            from_=safe_address if safe_address is not None else self.account._address,
            appData=app_data,
        )

        order_side = OrderQuoteSide3(
            kind=OrderQuoteSideKindBuy.buy,
            buyAmountAfterFee=TokenAmount(str(amount_wei)),
        )

        order_quote = await get_order_quote(order_quote_request, order_side, order_book_api)

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
            app_data = _get_cowpy_module("DEFAULT_APP_DATA_HASH")

        SupportedChainId = _get_cowpy_module("SupportedChainId")
        OrderBookApi = _get_cowpy_module("OrderBookApi")
        OrderBookAPIConfigFactory = _get_cowpy_module("OrderBookAPIConfigFactory")
        OrderQuoteRequest = _get_cowpy_module("OrderQuoteRequest")
        get_order_quote = _get_cowpy_module("get_order_quote")
        OrderQuoteSide1 = _get_cowpy_module("OrderQuoteSide1")
        OrderQuoteSideKindSell = _get_cowpy_module("OrderQuoteSideKindSell")
        TokenAmount = _get_cowpy_module("TokenAmount")

        chain_id = SupportedChainId(self.cow_chain.value[0])
        order_book_api = OrderBookApi(OrderBookAPIConfigFactory.get_config(env, chain_id))

        order_quote_request = OrderQuoteRequest(
            sellToken=sell_token,
            buyToken=buy_token,
            from_=safe_address if safe_address is not None else self.account._address,
            appData=app_data,
        )

        order_side = OrderQuoteSide1(
            kind=OrderQuoteSideKindSell.sell,
            sellAmountBeforeFee=TokenAmount(str(sell_amount_wei)),
        )

        order_quote = await get_order_quote(order_quote_request, order_side, order_book_api)

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
        """A modified version of cowdao_cowpy.cow.swap.swap_tokens to allow swapping to exact tokens."""
        # Lazy imports
        if app_data is None:
            app_data = _get_cowpy_module("DEFAULT_APP_DATA_HASH")
        SupportedChainId = _get_cowpy_module("SupportedChainId")
        OrderBookApi = _get_cowpy_module("OrderBookApi")
        OrderBookAPIConfigFactory = _get_cowpy_module("OrderBookAPIConfigFactory")
        OrderQuoteRequest = _get_cowpy_module("OrderQuoteRequest")
        OrderQuoteSide3 = _get_cowpy_module("OrderQuoteSide3")
        OrderQuoteSideKindBuy = _get_cowpy_module("OrderQuoteSideKindBuy")
        TokenAmount = _get_cowpy_module("TokenAmount")
        get_order_quote = _get_cowpy_module("get_order_quote")
        Order = _get_cowpy_module("Order")
        PreSignSignature = _get_cowpy_module("PreSignSignature")
        SigningScheme = _get_cowpy_module("SigningScheme")
        sign_order = _get_cowpy_module("sign_order")
        post_order = _get_cowpy_module("post_order")
        CompletedOrder = _get_cowpy_module("CompletedOrder")

        chain_id = SupportedChainId(chain.value[0])
        order_book_api = OrderBookApi(OrderBookAPIConfigFactory.get_config(env, chain_id))

        order_quote_request = OrderQuoteRequest(
            sellToken=sell_token,
            buyToken=buy_token,
            from_=safe_address if safe_address is not None else account._address,  # type: ignore # pyright doesn't recognize `populate_by_name=True`.
            appData=app_data,
        )

        # This is one of the changes
        order_side = OrderQuoteSide3(
            kind=OrderQuoteSideKindBuy.buy,
            buyAmountAfterFee=TokenAmount(str(amount)),
        )

        order_quote = await get_order_quote(order_quote_request, order_side, order_book_api)

        sell_amount_wei = int(int(order_quote.quote.sellAmount.root) * (1.0 + slippage_tolerance))

        min_valid_to = (
            order_quote.quote.validTo
            if valid_to is None
            else min(order_quote.quote.validTo, valid_to)
        )

        order = Order(
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
            kind=OrderQuoteSideKindBuy.buy.value,  # This is another change
            sell_token_balance="erc20",
            buy_token_balance="erc20",
            partially_fillable=partially_fillable,
        )

        signature = (
            PreSignSignature(
                scheme=SigningScheme.PRESIGN,
                data=safe_address,
            )
            if safe_address is not None
            else sign_order(chain, account, order)
        )
        order_uid = await post_order(account, safe_address, order, signature, order_book_api)
        order_link = order_book_api.get_order_link(order_uid)
        return CompletedOrder(uid=order_uid, url=order_link)
