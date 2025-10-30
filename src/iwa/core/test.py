from iwa.core.keys import KeyStorage
from iwa.core.wallet import Wallet
import asyncio
import warnings

warnings.filterwarnings("ignore", message="Pydantic serializer warnings:")

wallet = Wallet()


async def main():
    """Example of using CoW Swap on Gnosis Chain."""

    await wallet.swap_tokens(
        account_address_or_tag="master",
        amount_eth=0.9,
        sell_token_name="OLAS",
        buy_token_name="SDAI",
        chain_name="gnosis",
    )


if __name__ == "__main__":
    asyncio.run(main())
