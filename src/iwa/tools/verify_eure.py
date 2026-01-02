"""Verify EURE swaps."""

import asyncio
import sys

from web3 import Web3

from iwa.core.wallet import Wallet
from iwa.plugins.gnosis.cow import OrderType

# Pre-import cowpy utils to trigger asyncio.run() BEFORE our loop starts
try:
    import cowdao_cowpy.app_data.utils  # noqa: F401
except ImportError:
    pass

from loguru import logger

logger.remove()
logger.add(sys.stderr, level="DEBUG")

def run_verification():
    """Run the verification flow."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        w = Wallet()

        async def verify_eure():
            print("\n=== STARTING EURE VERIFICATION ===\n")

            # 1. SETUP: Need WXDAI
            amount_swap_eth = 0.01 # 0.01 WXDAI (~$0.01)

            wxdai_bal = w.balance_service.get_erc20_balance_wei("master", "WXDAI", "gnosis")
            if wxdai_bal < Web3.to_wei(amount_swap_eth, "ether"):
                 print("Step 1: Wrapping 0.02 xDAI -> WXDAI...")
                 w.transfer_service.wrap_native("master", Web3.to_wei(0.02, "ether"), "gnosis")
                 await asyncio.sleep(5)

            # 2. SWAP WXDAI -> EURE
            print("\nStep 2: Swapping 0.01 WXDAI -> EURE...")
            # We expect approval if not done (it wasn't done for EURE specifically in previous optimization test)
            # Actually, infinite approval (from my cancelled run/tests) might still be active?
            # Or Exact approval?
            # optimization test used WXDAI->USDC. EURE is a different spender?
            # NO, spender is RELAYER (same for all).
            # So if I approved WXDAI for Relayer in previous tests, it might be consumed or not.

            result1 = await w.transfer_service.swap(
                account_address_or_tag="master",
                amount_eth=amount_swap_eth,
                sell_token_name="WXDAI",
                buy_token_name="EURE",
                chain_name="gnosis",
                order_type=OrderType.SELL
            )

            if result1:
                 print("  ✅ Swap WXDAI->EURE Success!")
            else:
                 print("  ❌ Swap WXDAI->EURE Failed (or Expired)!")
                 return

            await asyncio.sleep(5)

            # 3. SWAP EURE -> WXDAI (Sell All)
            print("\nStep 3: Swapping ALL EURE -> WXDAI...")
            result2 = await w.transfer_service.swap(
                account_address_or_tag="master",
                amount_eth=None,
                sell_token_name="EURE",
                buy_token_name="WXDAI",
                chain_name="gnosis",
                order_type=OrderType.SELL
            )

            if result2:
                 print("  ✅ Swap EURE->WXDAI Success!")
            else:
                 print("  ❌ Swap EURE->WXDAI Failed!")

        loop.run_until_complete(verify_eure())

    finally:
        loop.close()

if __name__ == "__main__":
    run_verification()
