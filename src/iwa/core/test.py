from iwa.core.keys import KeyStorage
from iwa.core.wallet import Wallet

key_storage = KeyStorage()
wallet = Wallet()


wallet.multi_send(
    from_address_or_tag="mysafe",
    transactions=[
        {"to": "safe-1", "amount": 1, "token": "olas"},
        {"to": "mysafe2", "amount": 2, "token": "olas"},
    ],
    chain_name="gnosis",
)

wallet.multi_send(
    from_address_or_tag="mysafe",
    transactions=[
        {"to": "safe-1", "amount": 1},
        {"to": "mysafe2", "amount": 2},
    ],
    chain_name="gnosis",
)

wallet.multi_send(
    from_address_or_tag="master",
    transactions=[
        {"to": "safe-1", "amount": 1},
        {"to": "mysafe2", "amount": 2},
    ],
    chain_name="gnosis",
)
