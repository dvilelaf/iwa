from iwa.core.keys import KeyStorage
from iwa.core.wallet import Wallet
from iwa.protocols.gnosis.cow import CowSwap
from iwa.core.chain import Gnosis
from iwa.protocols.gnosis.cow import COWSWAP_GPV2_VAULT_RELAYER_ADDRESS
import asyncio
from loguru import logger
import warnings

warnings.filterwarnings("ignore", message="Pydantic serializer warnings:")

key_storage = KeyStorage()
wallet = Wallet()


async def main():
    """Example of using CoW Swap on Gnosis Chain."""

    cow = CowSwap(
        private_key=key_storage.get_account("master").key,
        chain=Gnosis(),
    )

    wallet.approve_erc20(
        owner_address_or_tag="master",
        spender_address=COWSWAP_GPV2_VAULT_RELAYER_ADDRESS,
        token_address_or_name=Gnosis().get_token_address("OLAS"),
        amount_eth=1,
        chain_name="gnosis",
    )

    success = await cow.swap_tokens(
        amount_eth=1,
        sell_token_name="OLAS",
        buy_token_name="SDAI",
    )
    logger.info(f"Swap successful: {success}")


if __name__ == "__main__":
    asyncio.run(main())
