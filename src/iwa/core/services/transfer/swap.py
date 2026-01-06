"""Swap mixin module."""

from typing import TYPE_CHECKING, Optional

from loguru import logger
from web3 import Web3

from iwa.core.chain import ChainInterfaces
from iwa.core.contracts.erc20 import ERC20Contract
from iwa.core.db import log_transaction
from iwa.plugins.gnosis.cow import COWSWAP_GPV2_VAULT_RELAYER_ADDRESS, CowSwap, OrderType

if TYPE_CHECKING:
    from iwa.core.services.transfer import TransferService


class SwapMixin:
    """Mixin for token swaps."""

    async def swap(  # noqa: C901
        self: "TransferService",
        account_address_or_tag: str,
        amount_eth: Optional[float],
        sell_token_name: str,
        buy_token_name: str,
        chain_name: str = "gnosis",
        order_type: OrderType = OrderType.SELL,
    ) -> Optional[dict]:
        """Swap ERC-20 tokens on CowSwap.

        Returns:
            dict | None: The executed order data if successful, None otherwise.

        """
        if amount_eth is None:
            if order_type == OrderType.BUY:
                raise ValueError("Amount must be specified for buy orders.")

            logger.info(f"Swapping entire {sell_token_name} balance to {buy_token_name}")
            amount_wei = self.balance_service.get_erc20_balance_wei(
                account_address_or_tag, sell_token_name, chain_name
            )
        else:
            amount_wei = Web3.to_wei(amount_eth, "ether")

        chain = ChainInterfaces().get(chain_name).chain
        account = self.account_service.resolve_account(account_address_or_tag)

        retries = 1
        max_retries = 3
        while retries < max_retries + 1:
            # Get signer (LocalAccount)
            signer = self.key_storage.get_signer(account.address)
            if not signer:
                logger.error(f"Could not retrieve signer for {account_address_or_tag}")
                return None

            cow = CowSwap(
                private_key_or_signer=signer,
                chain=chain,
            )

            # Check current allowance first
            current_allowance = (
                self.get_erc20_allowance(
                    owner_address_or_tag=account_address_or_tag,
                    spender_address=COWSWAP_GPV2_VAULT_RELAYER_ADDRESS,
                    token_address_or_name=sell_token_name,
                    chain_name="gnosis",
                )
                or 0
            )

            # Calculate required amount
            required_amount = (
                amount_wei
                if order_type == OrderType.SELL
                else cow.get_max_sell_amount_wei(
                    amount_wei,
                    sell_token_name,
                    buy_token_name,
                )
            )

            # If allowance is insufficient, approve EXACT amount (No Infinite)
            if current_allowance < required_amount:
                logger.info(
                    f"Insufficient allowance ({current_allowance} < {required_amount}). Approving EXACT amount."
                )
                self.approve_erc20(
                    owner_address_or_tag=account_address_or_tag,
                    spender_address_or_tag=COWSWAP_GPV2_VAULT_RELAYER_ADDRESS,
                    token_address_or_name=sell_token_name,
                    amount_wei=required_amount,
                    chain_name="gnosis",
                )
            else:
                logger.info(
                    f"Allowance sufficient ({current_allowance} >= {required_amount}). Skipping approval."
                )

            result = await cow.swap(
                amount_wei=amount_wei,
                sell_token_name=sell_token_name,
                buy_token_name=buy_token_name,
                order_type=order_type,
            )

            if result:
                logger.info("Swap successful")

                # Log transaction and analytics
                try:
                    # Extract Data
                    executed_sell = float(result.get("executedSellAmount", 0))
                    executed_buy = float(result.get("executedBuyAmount", 0))
                    quote = result.get("quote", {})
                    sell_price_usd = float(quote.get("sellTokenPrice", 0) or 0)
                    buy_price_usd = float(quote.get("buyTokenPrice", 0) or 0)
                    tx_hash = result.get("txHash") or result.get("uid")

                    # Calculate Analytics
                    execution_price = 0.0
                    if executed_sell > 0:
                        execution_price = executed_buy / executed_sell  # Raw ratio

                    # Get actual token decimals
                    sell_decimals = 18
                    buy_decimals = 18
                    try:
                        chain_interface = ChainInterfaces().get(chain_name)
                        if chain_interface:
                            sell_addr = chain_interface.chain.get_token_address(sell_token_name)
                            buy_addr = chain_interface.chain.get_token_address(buy_token_name)
                            if sell_addr:
                                sell_decimals = ERC20Contract(sell_addr, chain_name).decimals
                            if buy_addr:
                                buy_decimals = ERC20Contract(buy_addr, chain_name).decimals
                    except Exception as e:
                        logger.warning(f"Could not get decimals for analytics: {e}")

                    value_sold = (executed_sell / (10**sell_decimals)) * sell_price_usd
                    value_bought = (executed_buy / (10**buy_decimals)) * buy_price_usd

                    value_change_pct = None
                    if value_sold > 0 and buy_price_usd > 0:
                        value_change_pct = ((value_bought - value_sold) / value_sold) * 100

                    # Prepare extra_data
                    analytics = {
                        "type": "swap",
                        "platform": "cowswap",
                        "sell_token": sell_token_name,
                        "buy_token": buy_token_name,
                        "executed_sell_amount": executed_sell,
                        "executed_buy_amount": executed_buy,
                        "sell_price_usd": sell_price_usd,
                        "buy_price_usd": buy_price_usd,
                        "execution_price": execution_price,
                        "value_change_pct": value_change_pct
                        if value_change_pct is not None
                        else "N/A",
                    }

                    # Log to DB if we have a tx_hash (CowSwap usually provides it in order info if confirmed)
                    if tx_hash:
                        log_transaction(
                            tx_hash=tx_hash,
                            from_addr=account.address,
                            to_addr=COWSWAP_GPV2_VAULT_RELAYER_ADDRESS,  # Or settlement contract
                            token=sell_token_name,
                            amount_wei=int(executed_sell),
                            chain=chain_name,
                            from_tag=account_address_or_tag,
                            tags=["swap", "cowswap", sell_token_name, buy_token_name],
                            gas_cost="0",  # User doesn't pay gas for settlement (solver does)
                            gas_value_eur=0.0,
                            value_eur=float(value_sold)
                            if value_sold > 0
                            else None,  # Approximate as USD
                            extra_data=analytics,
                        )

                    # Inject analytics back into result for API/Frontend
                    result["analytics"] = analytics

                except Exception as log_err:
                    logger.warning(f"Failed to log swap analytics: {log_err}")

                return result

            logger.error(f"Swap try {retries}/{max_retries}] failed")
            retries += 1

        logger.error("Max swap retries reached. Swap failed.")
