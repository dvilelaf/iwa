"""Test module."""

import asyncio

from iwa.core.wallet import Wallet
from iwa.plugins.olas.service_manager import ServiceManager

wallet = Wallet()


async def main():
    """Example of using CoW Swap on Gnosis Chain."""
    # await wallet.swap_tokens(
    #     account_address_or_tag="master",
    #     amount_eth=None,  # Swap entire balance
    #     sell_token_name="OLAS",
    #     buy_token_name="SDAI",
    #     chain_name="gnosis",
    #     fixed_buy_amount=False,
    # )

    service_manager = ServiceManager(wallet=wallet)
    service_manager.create()


if __name__ == "__main__":  # pragma: no cover
    asyncio.run(main())
