"""Swap mixin module."""

from typing import TYPE_CHECKING, Any, Optional

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

    async def swap(
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
        amount_wei = self._prepare_swap_amount(
            account_address_or_tag,
            amount_eth,
            sell_token_name,
            buy_token_name,
            chain_name,
            order_type,
        )
        if amount_wei is None:
            return None

        chain = ChainInterfaces().get(chain_name).chain
        account = self.account_service.resolve_account(account_address_or_tag)

        # Validate balance before proceeding (for SELL orders)
        if order_type == OrderType.SELL:
            current_balance = self.balance_service.get_erc20_balance_wei(
                account_address_or_tag, sell_token_name, chain_name
            )
            if current_balance is not None and current_balance < amount_wei:
                # Precision tolerance: if the discrepancy is tiny (e.g. < 0.0001 tokens),
                # just use the actual balance instead of failing.
                # This handles float precision issues from the frontend.
                diff = amount_wei - current_balance
                tolerance = 10**14  # 0.0001 tokens (handles most rounding issues)

                if diff <= tolerance:
                    logger.warning(
                        f"Adjusting swap amount due to precision discrepancy: "
                        f"requested {amount_wei}, balance {current_balance} (diff: {diff})"
                    )
                    amount_wei = current_balance
                else:
                    balance_eth = current_balance / 1e18
                    amount_eth_val = amount_wei / 1e18
                    raise ValueError(
                        f"Insufficient {sell_token_name} balance: have {balance_eth:.6f}, need {amount_eth_val:.6f}"
                    )
            elif current_balance is None:
                raise ValueError(f"Could not retrieve balance for {sell_token_name}")

        # Get signer (LocalAccount)
        signer = self.key_storage.get_signer(account.address)
        if not signer:
            logger.error(f"Could not retrieve signer for {account_address_or_tag}")
            return None

        cow = CowSwap(
            private_key_or_signer=signer,
            chain=chain,
        )

        # Check and approve allowance if needed
        await self._ensure_allowance_for_swap(
            account_address_or_tag,
            sell_token_name,
            buy_token_name,
            chain_name,
            amount_wei,
            order_type,
            cow,
        )

        # Execute Swap
        logger.debug(
            f"Executing swap: amount_wei={amount_wei}, sell={sell_token_name}, buy={buy_token_name}, order_type={order_type}"
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
                analytics = self._calculate_swap_analytics(
                    result, sell_token_name, buy_token_name, chain_name
                )

                tx_hash = result.get("txHash") or result.get("uid")
                if tx_hash:
                    self._log_swap_transaction(
                        tx_hash,
                        account,
                        account_address_or_tag,
                        sell_token_name,
                        buy_token_name,
                        result,
                        chain_name,
                        analytics,
                    )

                # Inject analytics back into result for API/Frontend
                result["analytics"] = analytics

            except Exception as log_err:
                logger.warning(f"Failed to log swap analytics: {log_err}")

            return result

        logger.error("Swap failed")
        return None

    def _prepare_swap_amount(
        self: "TransferService",
        account_address_or_tag: str,
        amount_eth: Optional[float],
        sell_token_name: str,
        buy_token_name: str,
        chain_name: str,
        order_type: OrderType,
    ) -> Optional[int]:
        """Calculate and validate the swap amount in wei."""
        if amount_eth is None:
            if order_type == OrderType.BUY:
                # raise ValueError("Amount must be specified for buy orders.")
                # To maintain existing behavior (exception raised in original code),
                # we can either raise or let the caller handle None.
                # Original raised ValueError, let's keep it safe or just return.
                # Since original code raised it inside the method, let's raise it here.
                raise ValueError("Amount must be specified for buy orders.")

            logger.info(f"Swapping entire {sell_token_name} balance to {buy_token_name}")
            return self.balance_service.get_erc20_balance_wei(
                account_address_or_tag, sell_token_name, chain_name
            )
        else:
            # Get decimals correctly!
            decimals = 18
            try:
                chain_interface = ChainInterfaces().get(chain_name)
                token_addr = chain_interface.chain.get_token_address(sell_token_name)
                if token_addr:
                    checksum_addr = Web3.to_checksum_address(token_addr)
                    decimals = ERC20Contract(checksum_addr, chain_name).decimals
            except Exception as e:
                logger.warning(f"Could not get decimals for {sell_token_name}, assuming 18: {e}")

            return int(amount_eth * (10**decimals))

    async def _ensure_allowance_for_swap(
        self: "TransferService",
        account_address_or_tag: str,
        sell_token_name: str,
        buy_token_name: str,
        chain_name: str,
        amount_wei: int,
        order_type: OrderType,
        cow: CowSwap,
    ) -> int:
        """Check and approve allowance for CowSwap."""
        # Check current allowance first
        current_allowance = (
            self.get_erc20_allowance(
                owner_address_or_tag=account_address_or_tag,
                spender_address=COWSWAP_GPV2_VAULT_RELAYER_ADDRESS,
                token_address_or_name=sell_token_name,
                chain_name=chain_name,
            )
            or 0
        )

        # Calculate required amount
        if order_type == OrderType.SELL:
            required_amount = amount_wei
        else:
            # Need token addresses for buy mode calculation
            chain_interface = ChainInterfaces().get(chain_name)
            sell_token_address = chain_interface.chain.get_token_address(sell_token_name)
            buy_token_address = chain_interface.chain.get_token_address(buy_token_name)
            required_amount = await cow.get_max_sell_amount_wei(
                amount_wei,
                sell_token_address,
                buy_token_address,
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
                chain_name=chain_name,
            )
        else:
            logger.info(
                f"Allowance sufficient ({current_allowance} >= {required_amount}). Skipping approval."
            )
        return required_amount

    def _calculate_swap_analytics(
        self: "TransferService",
        result: dict,
        sell_token_name: str,
        buy_token_name: str,
        chain_name: str,
    ) -> dict:
        """Calculate swap analytics from result."""
        executed_sell = float(result.get("executedSellAmount", 0))
        executed_buy = float(result.get("executedBuyAmount", 0))
        quote = result.get("quote", {})
        sell_price_usd = float(quote.get("sellTokenPrice", 0) or 0)
        buy_price_usd = float(quote.get("buyTokenPrice", 0) or 0)

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
                    sell_decimals = ERC20Contract(
                        Web3.to_checksum_address(sell_addr), chain_name
                    ).decimals
                if buy_addr:
                    buy_decimals = ERC20Contract(
                        Web3.to_checksum_address(buy_addr), chain_name
                    ).decimals
        except Exception as e:
            logger.warning(f"Could not get decimals for analytics: {e}")

        value_sold = (executed_sell / (10**sell_decimals)) * sell_price_usd
        value_bought = (executed_buy / (10**buy_decimals)) * buy_price_usd

        value_change_pct = None
        if value_sold > 0 and buy_price_usd > 0:
            value_change_pct = ((value_bought - value_sold) / value_sold) * 100

        # Prepare extra_data
        return {
            "type": "swap",
            "platform": "cowswap",
            "sell_token": sell_token_name,
            "buy_token": buy_token_name,
            "executed_sell_amount": executed_sell,
            "executed_buy_amount": executed_buy,
            "sell_price_usd": sell_price_usd,
            "buy_price_usd": buy_price_usd,
            "execution_price": execution_price,
            "value_change_pct": value_change_pct if value_change_pct is not None else "N/A",
            # Internal fields for logging use
            "_value_sold": value_sold,
        }

    def _log_swap_transaction(
        self,
        tx_hash: str,
        account: Any,
        account_tag: str,
        sell_token: str,
        buy_token: str,
        result: dict,
        chain_name: str,
        analytics: dict,
    ) -> None:
        """Log swap transaction to database."""
        executed_sell = float(result.get("executedSellAmount", 0))
        value_sold = analytics.get("_value_sold", 0.0)

        # Clean internal fields
        clean_analytics = analytics.copy()
        clean_analytics.pop("_value_sold", None)

        log_transaction(
            tx_hash=tx_hash,
            from_addr=account.address,
            to_addr=COWSWAP_GPV2_VAULT_RELAYER_ADDRESS,
            token=sell_token,
            amount_wei=int(executed_sell),
            chain=chain_name,
            from_tag=account_tag,
            tags=["swap", "cowswap", sell_token, buy_token],
            gas_cost="0",
            gas_value_eur=0.0,
            value_eur=float(value_sold) if value_sold > 0 else None,
            extra_data=clean_analytics,
        )
