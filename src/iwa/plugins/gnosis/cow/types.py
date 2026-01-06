"""CoW Swap types and constants."""

from enum import Enum

from iwa.core.types import EthereumAddress

COW_API_URLS = {100: "https://api.cow.fi/xdai"}
ORDER_ENDPOINT_URL = "/api/v1/orders/"
COW_EXPLORER_URL = "https://explorer.cow.fi/gc/orders/"
HTTP_OK = 200

COWSWAP_GPV2_VAULT_RELAYER_ADDRESS = EthereumAddress("0xC92E8bdf79f0507f65a392b0ab4667716BFE0110")
MAX_APPROVAL = 2**256 - 1


class OrderType(Enum):
    """Order types."""

    SELL = "sell"
    BUY = "buy"
