"""Verify all token swaps."""

import asyncio

from web3 import Web3

from iwa.core.wallet import Wallet
from iwa.plugins.gnosis.cow import COWSWAP_GPV2_VAULT_RELAYER_ADDRESS, OrderType

try:
    import cowdao_cowpy.app_data.utils  # noqa: F401
except ImportError:
    pass

import sys

from loguru import logger

logger.remove()
logger.add(sys.stderr, level="DEBUG")

def run_verification():
    """Run verification flow."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        w = Wallet()

        async def verify_flow():
            print("\n=== STARTING OPTIMIZATION VERIFICATION ===\n")

            # 1. SETUP: Wrap enough for 2 swaps (0.02 WXDAI)
            amount_swap_eth = 0.01
            amount_swap_wei = Web3.to_wei(amount_swap_eth, "ether")
            amount_approve_wei = amount_swap_wei * 2 # 0.02

            wxdai = w.balance_service.get_erc20_balance_wei("master", "WXDAI", "gnosis")
            if wxdai < amount_approve_wei:
                 print("Step 1: Wrapping 0.05 xDAI -> WXDAI (Ensure balance)...")
                 w.transfer_service.wrap_native("master", Web3.to_wei(0.05, "ether"), "gnosis")
                 await asyncio.sleep(5)

            # 2. MANUALLY APPROVE 0.02 WXDAI (Enough for 2 swaps)
            print("\nStep 2: Manually Approving 2x Amount (0.02 WXDAI) to test optimization...")
            w.transfer_service.approve_erc20(
                owner_address_or_tag="master",
                spender_address_or_tag=COWSWAP_GPV2_VAULT_RELAYER_ADDRESS,
                token_address_or_name="WXDAI",
                amount_wei=amount_approve_wei,
                chain_name="gnosis"
            )
            # Wait for approval to propagate/index if needed? Gnosis is fast.
            await asyncio.sleep(5)

            # 3. RUN SWAP 1 (Should SKIP approval)
            print("\nStep 3: Swap 1 (0.01 WXDAI) - EXPECT: 'Allowance sufficient'")
            result1 = await w.transfer_service.swap(
                account_address_or_tag="master",
                amount_eth=amount_swap_eth,
                sell_token_name="WXDAI",
                buy_token_name="USDC",
                chain_name="gnosis",
                order_type=OrderType.SELL
            )
            if result1:
                 print("  ✅ Swap 1 Success!")
            else:
                 print("  ❌ Swap 1 Failed!")

            await asyncio.sleep(5)

            # 4. RUN SWAP 2 (Should SKIP approval since 0.01 remains)
            print("\nStep 4: Swap 2 (0.01 WXDAI) - EXPECT: 'Allowance sufficient'")
            result2 = await w.transfer_service.swap(
                account_address_or_tag="master",
                amount_eth=amount_swap_eth,
                sell_token_name="WXDAI",
                buy_token_name="USDC",
                chain_name="gnosis",
                order_type=OrderType.SELL
            )
            if result2:
                 print("  ✅ Swap 2 Success!")
            else:
                 print("  ❌ Swap 2 Failed!")

            await asyncio.sleep(5)

            # 5. RUN SWAP 3 (Should APPROVE 0.01 WXDAI since 0 remains)
            print("\nStep 5: Swap 3 (0.01 WXDAI) - EXPECT: 'Approving EXACT amount'")
            result3 = await w.transfer_service.swap(
                account_address_or_tag="master",
                amount_eth=amount_swap_eth,
                sell_token_name="WXDAI",
                buy_token_name="USDC",
                chain_name="gnosis",
                order_type=OrderType.SELL
            )
            if result3:
                 print("  ✅ Swap 3 Success!")


        loop.run_until_complete(verify_flow())

    finally:
        loop.close()

if __name__ == "__main__":
    run_verification()
