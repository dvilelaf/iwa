import logging
import time

import requests
from eth_account import Account
from web3 import Web3
from cowdao_cowpy.order_book.generated.model import (
    UID,
    OrderCreation,
    OrderQuoteRequest,
    OrderQuoteResponse,
    OrderQuoteSide1,
    OrderQuoteSideKindSell,
    TokenAmount,
    OrderQuoteSide3,
    OrderQuoteSideKindBuy,
)
from cowdao_cowpy.order_book.api import OrderBookApi
from cowdao_cowpy.order_book.config import Envs, OrderBookAPIConfigFactory
from cowdao_cowpy.common.chains import Chain
from cowdao_cowpy.common.chains import SupportedChainId
from loguru import logger
from pydantic import BaseModel
from cowdao_cowpy.cow.swap import CompletedOrder, swap_tokens
from web3.types import Wei
from eth_typing.evm import ChecksumAddress
from web3 import Web3
from iwa.core.contracts.ERC20 import ERC20Contract
from iwa.core.chain import SupportedChain
import warnings

warnings.filterwarnings("ignore", message="Pydantic serializer warnings:")

COW_API_URLS = {100: "https://api.cow.fi/xdai"}
COW_EXPLORER_URL = "https://explorer.cow.fi/gc/orders/"
HTTP_OK = 200

COWSWAP_GPV2_VAULT_RELAYER_ADDRESS = "0xC92E8bdf79f0507f65a392b0ab4667716BFE0110"
MAX_APPROVAL = 2**256 - 1


class CowSwap:
    """Simple CoW Swap integration using CoW Protocol's public API."""

    env: Envs = "prod"

    def __init__(self, private_key: str, chain: SupportedChain):
        self.account = Account.from_key(private_key)
        self.chain = chain
        self.supported_chain_id = SupportedChainId(chain.chain_id)
        self.cow_chain = self.get_chain()
        self.cowswap_api_url = COW_API_URLS.get(chain.chain_id)
        self.order_book_api = OrderBookApi(
            OrderBookAPIConfigFactory.get_config(self.env, chain.chain_id)
        )

    def get_chain(self) -> Chain:
        """Get the Chain enum based on the supported chain ID."""
        for chain in Chain:
            if chain.value[0] == self.supported_chain_id:
                return chain
        raise ValueError(f"Unsupported SupportedChainId: {self.supported_chain_id}")

    @staticmethod
    def check_cowswap_order(order: CompletedOrder) -> bool:
        """Check if a Cowswap order has been executed"""

        logger.info(f"Checking order status")

        MAX_RETRIES = 8
        SLEEP_BETWEEN_RETRIES = 30
        retries = 0

        while retries < MAX_RETRIES:
            retries += 1

            response = requests.get(order.url, timeout=60)

            if response.status_code != HTTP_OK:
                logger.info(
                    f"Order is not ready yet: {response.status_code}. Checking again in {SLEEP_BETWEEN_RETRIES}s"
                )
                time.sleep(SLEEP_BETWEEN_RETRIES)
                continue

            order_data = response.json()
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
                f"Order has not been executed yet. Checking again in {SLEEP_BETWEEN_RETRIES}s"
            )
            time.sleep(SLEEP_BETWEEN_RETRIES)

        logger.error("Max retries reached. Could not verify the order.")
        return False

    async def swap_tokens(
        self,
        amount_eth: float,
        sell_token_name: str,
        buy_token_name: str,
        safe_address: ChecksumAddress | None = None,
    ) -> bool:
        """Swap tokens."""

        amount_wei = Web3.to_wei(amount_eth, "ether")

        logger.info(
            f"Swapping {amount_eth} {sell_token_name} to {buy_token_name} on {self.chain.name}..."
        )

        valid_to = int(time.time()) + 3 * 60  # Order valid for 3 minutes

        try:
            order = await swap_tokens(
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
