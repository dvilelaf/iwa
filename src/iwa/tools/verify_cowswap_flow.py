"""Verify CowSwap flow."""
import asyncio
import logging

from web3 import Web3

from iwa.core.chain import ChainInterfaces
from iwa.core.wallet import Wallet
from iwa.plugins.gnosis.cow import OrderType

# Pre-load cowda-cowpy to prevent lazy-load asyncio.run() conflict inside the loop
try:
    import cowdao_cowpy.app_data.utils  # noqa: F401
except ImportError:
    pass

# Configure minimal logging to see critical info
logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger("iwa")


def run_verification():
    """Run verification flow."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        w = Wallet()
        # chain_interfaces = ChainInterfaces()
        # chain_interface = chain_interfaces.get("gnosis")
        # chain = chain_interface  # Unused
        # gnosis = Gnosis()        # Unused
        # signer = w.key_storage.get_signer("master") # Unused
        # cow = CowSwap(signer, gnosis) # Not used directly, TransferService handles it

        async def verify_flow():
            print("\n=== STARTING LIVE VERIFICATION ===\n")

            # 1. Check Initial Balance
            native = w.get_native_balance_eth("master", "gnosis")
            wxdai = w.balance_service.get_erc20_balance_wei("master", "WXDAI", "gnosis")
            olas = w.balance_service.get_erc20_balance_wei("master", "OLAS", "gnosis")
            print(f"Initial Balances:\n  xDAI: {native:.4f}\n  WXDAI: {float(Web3.from_wei(wxdai, 'ether')):.4f}\n  OLAS: {float(Web3.from_wei(olas or 0, 'ether')):.4f}\n")

            # 2. WRAP 0.05 xDAI
            wrap_amount = Web3.to_wei(0.05, "ether")
            print("Step 1: Wrapping 0.05 xDAI -> WXDAI...")
            tx = w.transfer_service.wrap_native("master", wrap_amount, "gnosis")
            if tx:
                print(f"  ✅ Wrap Success! TX: {tx}")
            else:
                print("  ❌ Wrap Failed!")
                return

            # Allow chain to update
            print("  Waiting 5s for consistency...")
            await asyncio.sleep(5)

            # 3. SWAP 1: 0.02 WXDAI -> OLAS
            print("\nStep 2: Swapping 0.02 WXDAI -> OLAS...")

            result1 = await w.transfer_service.swap(
                account_address_or_tag="master",
                amount_eth=0.02,
                sell_token_name="WXDAI",
                buy_token_name="OLAS",
                chain_name="gnosis",
                order_type=OrderType.SELL
            )

            if result1:
                print("  ✅ Swap 1 Success!")
                quote = result1.get("quote", {})
                sell_price = float(quote.get("sellTokenPrice", 0))
                buy_price = float(quote.get("buyTokenPrice", 0))
                executed_sell = float(result1.get("executedSellAmount", 0))
                executed_buy = float(result1.get("executedBuyAmount", 0))

                print(f"     Executed Sell: {executed_sell/1e18:.4f} WXDAI")
                print(f"     Executed Buy:  {executed_buy/1e18:.4f} OLAS")
                print(f"     Prices (USD):  Sell=${sell_price:.2f} | Buy=${buy_price:.2f}")

                 # Analytics Logic Duplication for Verify
                value_sold = (executed_sell / 1e18) * sell_price
                value_bought = (executed_buy / 1e18) * buy_price
                value_change = 0.0
                if value_sold > 0:
                     value_change = ((value_bought - value_sold) / value_sold) * 100
                print(f"     Value Change: {value_change:.2f}%")

            else:
                print("  ❌ Swap 1 Failed!")
                return

            print("  Waiting 5s for consistency...")
            await asyncio.sleep(5)

            # 4. SWAP 2: Sell ALL OLAS -> WXDAI
            # Get current OLAS balance
            olas_bal = w.balance_service.get_erc20_balance_wei("master", "OLAS", "gnosis")
            olas_bal_eth = float(Web3.from_wei(olas_bal, "ether"))
            print(f"\nStep 3: Swapping ALL OLAS ({olas_bal_eth:.4f}) -> WXDAI...")

            result2 = await w.transfer_service.swap(
                account_address_or_tag="master",
                amount_eth=None,
                sell_token_name="OLAS",
                buy_token_name="WXDAI",
                chain_name="gnosis",
                order_type=OrderType.SELL
            )

            if result2:
                 print("  ✅ Swap 2 Success!")
                 quote = result2.get("quote", {})
                 executed_sell = float(result2.get("executedSellAmount", 0))
                 executed_buy = float(result2.get("executedBuyAmount", 0))
                 sell_price = float(quote.get("sellTokenPrice", 0))
                 buy_price = float(quote.get("buyTokenPrice", 0))

                 value_sold = (executed_sell / 1e18) * sell_price
                 value_bought = (executed_buy / 1e18) * buy_price
                 value_change = 0.0
                 if value_sold > 0:
                     value_change = ((value_bought - value_sold) / value_sold) * 100
                 print(f"     Value Change: {value_change:.2f}%")

            else:
                 print("  ❌ Swap 2 Failed!")

            print("  Waiting 5s for consistency...")
            await asyncio.sleep(5)

            # 5. SWAP 3: 0.01 WXDAI -> OLAS
            print("\nStep 4: Swapping 0.01 WXDAI -> OLAS...")
            result3 = await w.transfer_service.swap(
                account_address_or_tag="master",
                amount_eth=0.01,
                sell_token_name="WXDAI",
                buy_token_name="OLAS",
                chain_name="gnosis",
                order_type=OrderType.SELL
            )
            if result3:
                 print("  ✅ Swap 3 Success!")
                 quote = result3.get("quote", {})
                 executed_sell = float(result3.get("executedSellAmount", 0))
                 executed_buy = float(result3.get("executedBuyAmount", 0))
                 sell_price = float(quote.get("sellTokenPrice", 0))
                 buy_price = float(quote.get("buyTokenPrice", 0))

                 value_sold = (executed_sell / 1e18) * sell_price
                 value_bought = (executed_buy / 1e18) * buy_price
                 value_change = 0.0
                 if value_sold > 0:
                     value_change = ((value_bought - value_sold) / value_sold) * 100
                 print(f"     Value Change: {value_change:.2f}%")
            else:
                 print("  ❌ Swap 3 Failed!")

            print("  Waiting 5s for consistency...")
            await asyncio.sleep(5)

            # 6. UNWRAP ALL WXDAI -> xDAI
            print("\nStep 5: Unwrapping ALL WXDAI -> xDAI...")
            tx_unwrap = w.transfer_service.unwrap_native("master", amount_wei=None, chain_name="gnosis")
            if tx_unwrap:
                print(f"  ✅ Unwrap Success! TX: {tx_unwrap}")
            else:
                print("  ❌ Unwrap Failed!")

            # 7. Final Balances
            print("  Waiting 5s for consistency...")
            await asyncio.sleep(5)
            native_final = w.get_native_balance_eth("master", "gnosis")
            wxdai_final = w.balance_service.get_erc20_balance_wei("master", "WXDAI", "gnosis")
            olas_final = w.balance_service.get_erc20_balance_wei("master", "OLAS", "gnosis")

            print("\n=== FINAL RESULTS ===\n")
            print(f"Final Balances:\n  xDAI: {native_final:.4f}\n  WXDAI: {float(Web3.from_wei(wxdai_final or 0, 'ether')):.4f}\n  OLAS: {float(Web3.from_wei(olas_final or 0, 'ether')):.4f}\n")

        loop.run_until_complete(verify_flow())

    finally:
        loop.close()

if __name__ == "__main__":
    run_verification()
