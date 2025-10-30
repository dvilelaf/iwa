from iwa.core.wallet import Wallet
import asyncio
import warnings
from iwa.core.models import EthereumAddress

warnings.filterwarnings("ignore", message="Pydantic serializer warnings:")

wallet = Wallet()


# async def main():
#     """Example of using CoW Swap on Gnosis Chain."""

#     await wallet.swap_tokens(
#         account_address_or_tag="master",
#         amount_eth=None,  # Swap entire balance
#         sell_token_name="OLAS",
#         buy_token_name="SDAI",
#         chain_name="gnosis",
#         fixed_buy_amount=False,
#     )


# if __name__ == "__main__":
#     asyncio.run(main())

wallet.drain(
    from_address_or_tag="master",
    to_address_or_tag=EthereumAddress("0x832fac064e008a436d38d31eeae882cede3d7e5d"),
    chain_name="gnosis",
)
