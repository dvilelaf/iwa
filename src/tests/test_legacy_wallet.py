import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Mock cowdao_cowpy before importing Wallet
sys.modules["cowdao_cowpy"] = MagicMock()
sys.modules["cowdao_cowpy.app_data"] = MagicMock()
sys.modules["cowdao_cowpy.app_data.utils"] = MagicMock()
sys.modules["cowdao_cowpy.common"] = MagicMock()
sys.modules["cowdao_cowpy.common.chains"] = MagicMock()
sys.modules["cowdao_cowpy.contracts"] = MagicMock()
sys.modules["cowdao_cowpy.contracts.order"] = MagicMock()
sys.modules["cowdao_cowpy.contracts.sign"] = MagicMock()
sys.modules["cowdao_cowpy.cow"] = MagicMock()
sys.modules["cowdao_cowpy.cow.swap"] = MagicMock()
sys.modules["cowdao_cowpy.order_book"] = MagicMock()
sys.modules["cowdao_cowpy.order_book.api"] = MagicMock()
sys.modules["cowdao_cowpy.order_book.config"] = MagicMock()
sys.modules["cowdao_cowpy.order_book.generated"] = MagicMock()
sys.modules["cowdao_cowpy.order_book.generated.model"] = MagicMock()

from iwa.core.chain import Gnosis
from iwa.core.models import StoredAccount, StoredSafeAccount
from iwa.core.services import TransferService
from iwa.core.wallet import Wallet
from iwa.plugins.gnosis.cow import OrderType

# Use valid addresses
VALID_ADDR_1 = "0x5B38Da6a701c568545dCfcB03FcB875f56beddC4"
VALID_ADDR_2 = "0x78731D3Ca6b7E34aC0F824c42a7cC18A495cabaB"


@pytest.fixture
def mock_transaction_service():
    with patch("iwa.core.wallet.TransactionService") as mock:
        instance = mock.return_value
        instance.sign_and_send.return_value = (True, "0xTxHash")
        yield instance


@pytest.fixture
def mock_key_storage():
    with patch("iwa.core.wallet.KeyStorage") as mock:
        instance = mock.return_value
        instance.accounts = {}
        instance.get_account.return_value = None
        instance.find_stored_account = instance.get_account
        yield instance


@pytest.fixture
def mock_chain_interfaces():
    with (
        patch("iwa.core.chain.ChainInterfaces") as mock,
        patch("iwa.core.services.transfer.multisend.ChainInterfaces", new=mock),
        patch("iwa.core.services.transfer.erc20.ChainInterfaces", new=mock),
        patch("iwa.core.services.transfer.native.ChainInterfaces", new=mock),
        patch("iwa.core.services.transfer.base.ChainInterfaces", new=mock),
        patch("iwa.core.services.balance.ChainInterfaces", new=mock),
        patch("iwa.core.services.transaction.ChainInterfaces", new=mock),
        patch("iwa.core.services.transfer.ChainInterfaces", new=mock),
        # Patch ERC20Contract where it is imported in the transfer package __init__
        patch("iwa.core.services.transfer.ERC20Contract"),
    ):
        instance = mock.return_value
        gnosis_interface = MagicMock()

        # Use a mock for the chain instead of the real Gnosis object
        mock_chain = MagicMock()
        mock_chain.name = "Gnosis"
        mock_chain.native_currency = "xDAI"
        mock_chain.chain_id = 100
        mock_chain.tokens = {}

        def debug_get_token(name):
            addr = mock_chain.tokens.get(name)
            # print(f"DEBUG LAMBDA: name={name} tokens={mock_chain.tokens} addr={addr}")
            return addr

        mock_chain.get_token_address.side_effect = debug_get_token
        gnosis_interface.chain = mock_chain

        gnosis_interface.web3 = MagicMock()
        gnosis_interface.web3.to_wei.side_effect = lambda val, unit: int(float(val) * 10**18)
        gnosis_interface.web3.from_wei.side_effect = lambda val, unit: float(val) / 10**18
        gnosis_interface.web3.eth.gas_price = 1000000000
        gnosis_interface.get_erc20_allowance.return_value = 0

        instance.get.return_value = gnosis_interface
        yield instance


@pytest.fixture
def mock_cow_swap():
    with patch("iwa.core.services.transfer.swap.CowSwap") as mock:
        yield mock


@pytest.fixture
def mock_account_service(mock_key_storage):
    with patch("iwa.core.wallet.AccountService") as mock:
        instance = mock.return_value
        instance.key_storage = mock_key_storage
        instance.master_account = None
        instance.get_account_data.return_value = {}
        # Delegate to key_storage.get_account for compatibility
        instance.resolve_account.side_effect = lambda tag: mock_key_storage.get_account(tag)

        # Default get_token_address to look up in chain tokens
        def get_token_address_side_effect(name, chain):
            if name == "native":
                return "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE"
            if str(name).startswith("0x"):
                return name
            if chain:
                return chain.get_token_address(name)
            return None

        instance.get_token_address.side_effect = get_token_address_side_effect
        yield instance


@pytest.fixture
def mock_balance_service(mock_key_storage, mock_account_service):
    with patch("iwa.core.wallet.BalanceService") as mock:
        instance = mock.return_value
        # Ensure we don't return MagicMocks for numeric values by default
        instance.get_native_balance_eth.return_value = 0.0
        instance.get_native_balance_wei.return_value = 0
        instance.get_erc20_balance_eth.return_value = 0.0
        instance.get_erc20_balance_wei.return_value = 0

        # Mocking resolve_account to return something with an address
        def resolve_side_effect(tag_or_addr):
            m = MagicMock()
            m.address = VALID_ADDR_1 if not str(tag_or_addr).startswith("0x") else tag_or_addr
            m.tag = "mock-tag"
            return m

        yield instance


# NOTE: mock_safe_multisig_global was removed because SafeMultisig is no longer
# imported in TransferService. Safe transactions now go through SafeService.execute_safe_transaction().


@pytest.fixture(autouse=True)
def mock_erc20_contract_global():
    with (
        patch("iwa.core.services.transfer.multisend.ERC20Contract") as m1,
        patch("iwa.core.services.transfer.erc20.ERC20Contract") as m2,
        patch("iwa.core.services.balance.ERC20Contract") as m3,
    ):
        m1.return_value.decimals = 18
        m2.return_value.decimals = 18
        m3.return_value.decimals = 18
        yield


@pytest.fixture(autouse=True)
def mock_security_validations():
    """Mock security validations to allow tests to run without full config.

    The _is_whitelisted_destination and _is_supported_token methods are mocked
    to return True by default. Tests that specifically test security rejection
    should patch these again to return False.
    """
    with (
        patch(
            "iwa.core.services.transfer.TransferService._is_whitelisted_destination",
            return_value=True,
        ),
        patch(
            "iwa.core.services.transfer.TransferService._is_supported_token",
            return_value=True,
        ),
    ):
        yield


@pytest.fixture
def mock_safe_service(mock_key_storage, mock_account_service):
    with patch("iwa.core.wallet.SafeService") as mock:
        instance = mock.return_value
        instance.key_storage = mock_key_storage
        instance.account_service = mock_account_service
        yield instance


@pytest.fixture
def wallet(
    mock_key_storage,
    mock_chain_interfaces,
    mock_cow_swap,
    mock_account_service,
    mock_balance_service,
    mock_safe_service,
    mock_transaction_service,
):
    with patch("iwa.core.wallet.init_db"):
        w = Wallet()
        w.key_storage = mock_key_storage
        w.account_service = mock_account_service
        w.transaction_service = mock_transaction_service
        w.balance_service = mock_balance_service
        w.safe_service = mock_safe_service

        # Re-initialize TransferService with these mocks
        w.transfer_service = TransferService(
            w.key_storage,
            w.account_service,
            w.balance_service,
            w.safe_service,
            w.transaction_service,
        )

        # Mock internal transfer service methods to return 0 by default for numeric comparisons,
        # but allow side_effect to handle tests that expect None.
        def get_allowance_side_effect(
            owner_address_or_tag,
            spender_address,
            token_address_or_name,
            chain_name="gnosis",
        ):
            if owner_address_or_tag == "unknown" or token_address_or_name == "INVALID":
                return None
            return 0

        w.transfer_service.get_erc20_allowance = MagicMock(side_effect=get_allowance_side_effect)
        w.transfer_service.get_native_balance_wei = MagicMock(return_value=0)
        w.transfer_service.get_erc20_balance_wei = MagicMock(return_value=0)
        yield w


def test_wallet_init(wallet, mock_key_storage):
    assert wallet.key_storage == mock_key_storage


def test_get_token_address_native(wallet, mock_account_service):
    chain = Gnosis()
    mock_account_service.get_token_address.return_value = (
        "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE"
    )
    addr = wallet.get_token_address("native", chain)
    assert addr == "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE"


def test_get_token_address_valid_address(wallet):
    chain = Gnosis()
    addr = wallet.get_token_address(VALID_ADDR_1, chain)
    assert addr == VALID_ADDR_1


def test_get_token_address_by_name(wallet):
    chain = Gnosis()
    # Assuming OLAS is in Gnosis tokens
    addr = wallet.get_token_address("OLAS", chain)
    assert addr == chain.tokens["OLAS"]


def test_get_token_address_invalid(wallet):
    chain = Gnosis()
    addr = wallet.get_token_address("INVALID_TOKEN", chain)
    assert addr is None


def test_sign_and_send_transaction_account_not_found(wallet, mock_account_service):
    mock_account_service.resolve_account.return_value = None
    wallet.transaction_service.sign_and_send.return_value = (False, {})

    success, receipt = wallet.sign_and_send_transaction({"to": "0x123"}, "unknown-tag", "gnosis")

    assert success is False
    assert receipt == {}
    wallet.transaction_service.sign_and_send.assert_called_with(
        {"to": "0x123"}, "unknown-tag", "gnosis", None
    )


def test_sign_and_send_transaction_success(wallet, mock_key_storage):
    tx = {"to": "0x123", "value": 100}

    # Setup mocks
    wallet.transaction_service.sign_and_send.return_value = (True, {"status": 1})

    # Call
    success, receipt = wallet.sign_and_send_transaction(tx, "tag")

    # Assert
    assert success is True
    assert receipt["status"] == 1
    wallet.transaction_service.sign_and_send.assert_called_with(tx, "tag", "gnosis", None)


def test_get_accounts_balances(wallet, mock_key_storage, mock_chain_interfaces):
    wallet.account_service.get_account_data.return_value = {"0x123": {}}
    mock_chain_interfaces.get.return_value.get_balance.return_value = 100
    wallet.balance_service.get_native_balance_eth.return_value = 1.0

    accounts_data, token_balances = wallet.get_accounts_balances("gnosis", ["native"])

    assert accounts_data == {"0x123": {}}
    assert token_balances == {"0x123": {"native": 1.0}}
    wallet.balance_service.get_native_balance_eth.assert_called_with("0x123", "gnosis")


def test_get_native_balance_eth(wallet, mock_chain_interfaces, mock_balance_service):
    # chain_interface.get_native_balance_eth.return_value = 1.5 # Ignored
    mock_balance_service.get_native_balance_eth.return_value = 1.5

    balance = wallet.get_native_balance_eth(VALID_ADDR_2)
    assert balance == 1.5


def test_get_native_balance_wei(wallet, mock_chain_interfaces, mock_balance_service):
    # chain_interface.get_native_balance_wei.return_value = ... # Ignored
    mock_balance_service.get_native_balance_wei.return_value = 1500000000000000000

    balance = wallet.get_native_balance_wei(VALID_ADDR_2)
    assert balance == 1500000000000000000
    # chain_interface.get_native_balance_wei.assert_called_with(VALID_ADDR_2) # Wrapper verification?
    # If using MockBalanceService, ChainInterface is NOT called.
    # So this assertion should be removed or changed to check BalanceService call.
    mock_balance_service.get_native_balance_wei.assert_called_with(
        VALID_ADDR_2, "gnosis"
    )  # Defaults to gnosis in test?
    # Wallet.get_native_balance_wei takes (account_tag, chain_name="gnosis").
    # If validation passes.


def test_send_native_success(wallet, mock_key_storage, mock_chain_interfaces, mock_balance_service):
    account = StoredAccount(address=VALID_ADDR_1, tag="sender")
    mock_key_storage.get_account.return_value = account

    chain_interface = mock_chain_interfaces.get.return_value
    # chain_interface.get_native_balance_wei.return_value = ... # Ignored
    mock_balance_service.get_native_balance_wei.return_value = 2000000000000000000

    chain_interface.web3.eth.gas_price = 1000000000
    chain_interface.web3.eth.estimate_gas.return_value = 21000
    chain_interface.web3.from_wei.side_effect = lambda val, unit: float(val) / 10**18

    # Mock return values for success
    chain_interface.sign_and_send_transaction.return_value = (True, {})
    chain_interface.send_native_transfer.return_value = (True, "0xHash")

    wallet.send(
        "sender", VALID_ADDR_2, amount_wei=1000000000000000000, token_address_or_name="native"
    )  # 1 ETH

    # wallet.transaction_service.sign_and_send.assert_called_once()
    chain_interface.send_native_transfer.assert_called_once()


def test_send_erc20_success(wallet, mock_key_storage, mock_chain_interfaces):
    account = MagicMock(spec=StoredAccount)
    account.address = VALID_ADDR_2
    account.key = "private_key"
    mock_key_storage.get_account.return_value = account

    chain_interface = mock_chain_interfaces.get.return_value
    chain_interface.chain.tokens = {"TEST": "0xTokenAddress"}
    chain_interface.web3.from_wei.side_effect = lambda val, unit: float(val) / 10**18

    wallet.balance_service.get_erc20_balance_wei.return_value = 2000
    wallet.balance_service.get_native_balance_wei.return_value = 1000000000000000000

    # Mock TransactionService return
    wallet.transaction_service.sign_and_send.return_value = (
        True,
        {"status": 1, "transactionHash": b"hash"},
    )

    with patch("iwa.core.services.transfer.multisend.ERC20Contract") as mock_erc20:
        with patch("iwa.core.services.transfer.erc20.ERC20Contract", new=mock_erc20):
            erc20_instance = mock_erc20.return_value
            erc20_instance.address = VALID_ADDR_1
            erc20_instance.prepare_transfer_tx.return_value = {
                "data": b"transfer_data",
                "to": VALID_ADDR_1,
                "value": 0,
            }

            wallet.send("sender", "recipient", amount_wei=1000, token_address_or_name="TEST")

            wallet.transaction_service.sign_and_send.assert_called_once()


def test_approve_erc20_success(wallet, mock_key_storage, mock_chain_interfaces):
    account = MagicMock(spec=StoredAccount)
    account.address = VALID_ADDR_2
    account.key = "private_key"
    mock_key_storage.get_account.return_value = account

    chain_interface = mock_chain_interfaces.get.return_value
    chain_interface.chain.tokens = {"TEST": "0xTokenAddress"}  # Needed for resolution
    chain_interface.web3.from_wei.side_effect = lambda val, unit: float(val) / 10**18

    wallet.transaction_service.sign_and_send.return_value = (
        True,
        {"status": 1, "transactionHash": b"hash"},
    )

    with patch("iwa.core.services.transfer.multisend.ERC20Contract") as mock_erc20:
        with patch("iwa.core.services.transfer.erc20.ERC20Contract", new=mock_erc20):
            erc20_instance = mock_erc20.return_value
            erc20_instance.allowance_wei.return_value = 0
            erc20_instance.prepare_approve_tx.return_value = {
                "data": b"approve_data",
                "to": VALID_ADDR_1,
                "value": 0,
            }

            wallet.approve_erc20("owner", "spender", "TEST", 1000)

            erc20_instance.prepare_approve_tx.assert_called_once()
            wallet.transaction_service.sign_and_send.assert_called_once()


def test_approve_erc20_already_sufficient(wallet, mock_key_storage, mock_chain_interfaces):
    account = MagicMock(spec=StoredAccount)
    account.address = VALID_ADDR_2
    mock_key_storage.get_account.return_value = account

    with (
        patch("iwa.core.services.transfer.multisend.ERC20Contract") as mock_erc20,
        patch("iwa.core.services.transfer.erc20.ERC20Contract"),
    ):
        erc20_instance = mock_erc20.return_value
        erc20_instance.allowance_wei.return_value = 2000

        wallet.approve_erc20("owner", "spender", "TEST", 1000)

        erc20_instance.prepare_approve_tx.assert_not_called()


def test_multi_send_success(wallet, mock_key_storage, mock_chain_interfaces):
    account = MagicMock(spec=StoredAccount)
    account.address = VALID_ADDR_2
    account.key = "private_key"
    mock_key_storage.get_account.return_value = account

    chain_interface = mock_chain_interfaces.get.return_value
    chain_interface.web3.to_wei.return_value = 1000

    wallet.transaction_service.sign_and_send.return_value = (
        True,
        {"status": 1, "transactionHash": b"hash"},
    )

    with patch("iwa.core.services.transfer.multisend.MultiSendCallOnlyContract") as mock_multisend:
        multisend_instance = mock_multisend.return_value
        multisend_instance.prepare_tx.return_value = {
            "data": b"multisend_data",
            "to": "0xMultiSend",
            "value": 0,
        }

        transactions = [
            {
                "to": VALID_ADDR_2,
                "amount": 1.0,
                "token": "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE",
            }
        ]

        wallet.multi_send("sender", transactions)

        multisend_instance.prepare_tx.assert_called_once()
        wallet.transaction_service.sign_and_send.assert_called_once()


def test_drain_native_success(
    wallet, mock_key_storage, mock_chain_interfaces, mock_balance_service
):
    account = MagicMock(spec=StoredAccount)
    account.address = VALID_ADDR_1
    mock_key_storage.get_account.return_value = account

    chain_interface = mock_chain_interfaces.get.return_value
    chain_interface.chain.tokens = {}
    mock_balance_service.get_native_balance_wei.return_value = 2000000000000000000
    chain_interface.web3.eth.gas_price = 1000000000
    chain_interface.web3.from_wei.side_effect = lambda val, unit: float(val) / 10**18
    chain_interface.web3.to_wei.side_effect = lambda val, unit: int(float(val) * 10**18)

    # Mock return values
    wallet.transaction_service.sign_and_send.return_value = (True, {"status": 1})

    with patch("iwa.core.services.transfer.multisend.MultiSendCallOnlyContract") as mock_multisend:
        multisend_instance = mock_multisend.return_value
        multisend_instance.prepare_tx.return_value = {"to": "0x", "data": b"", "value": 0}

        wallet.drain("sender", "recipient")

        # Now drain uses multi_send
        multisend_instance.prepare_tx.assert_called_once()
        wallet.transaction_service.sign_and_send.assert_called_once()


def test_drain_erc20_success(wallet, mock_key_storage, mock_chain_interfaces):
    account = MagicMock(spec=StoredAccount)
    account.address = VALID_ADDR_2
    mock_key_storage.get_account.return_value = account

    chain_interface = mock_chain_interfaces.get.return_value
    chain_interface.chain.tokens = {"TEST": "0xTokenAddress"}
    chain_interface.web3.from_wei.side_effect = lambda val, unit: float(val) / 10**18
    chain_interface.web3.to_wei.side_effect = lambda val, unit: int(float(val) * 10**18)

    wallet.balance_service.get_erc20_balance_wei.return_value = 1000
    wallet.balance_service.get_native_balance_wei.return_value = 1000000000000000000

    wallet.transaction_service.sign_and_send.return_value = (
        True,
        {"status": 1, "transactionHash": b"hash"},
    )

    with (
        patch("iwa.core.services.transfer.multisend.ERC20Contract") as mock_erc20,
        patch("iwa.core.services.transfer.multisend.MultiSendCallOnlyContract") as mock_multisend,
    ):
        with patch("iwa.core.services.transfer.erc20.ERC20Contract", new=mock_erc20):
            erc20_instance = mock_erc20.return_value
            erc20_instance.prepare_transfer_tx.return_value = {"to": "0x", "data": b"", "value": 0}

            multisend_instance = mock_multisend.return_value
            multisend_instance.prepare_tx.return_value = {"to": "0x", "data": b"", "value": 0}

            wallet.drain("sender", "recipient")

            # Drain now uses multi_send batching
            multisend_instance.prepare_tx.assert_called_once()
            assert wallet.transaction_service.sign_and_send.call_count == 2


@pytest.mark.asyncio
async def test_swap_success(wallet, mock_key_storage, mock_chain_interfaces, mock_cow_swap):
    account = MagicMock(spec=StoredAccount)
    account.address = VALID_ADDR_2
    account.key = "private_key"
    mock_key_storage.get_account.return_value = account

    chain_interface = mock_chain_interfaces.get.return_value
    chain_interface.web3.to_wei.return_value = 1000
    chain_interface.web3.from_wei.side_effect = lambda val, unit: float(val) / 10**18

    cow_instance = mock_cow_swap.return_value
    cow_instance.swap = MagicMock()
    cow_instance.swap.return_value = True

    # Make it awaitable
    async def async_true(*args, **kwargs):
        return True

    cow_instance.swap.side_effect = async_true

    with (
        patch("iwa.core.services.transfer.multisend.ERC20Contract") as mock_erc20,
        patch("iwa.core.services.transfer.erc20.ERC20Contract"),
    ):
        erc20_instance = mock_erc20.return_value
        erc20_instance.allowance_wei.return_value = 0
        erc20_instance.prepare_approve_tx.return_value = {
            "data": b"approve_data",
            "to": VALID_ADDR_1,
            "value": 0,
        }
        chain_interface.sign_and_send_transaction.return_value = (True, {})

        # Mock balance for pre-swap validation
        wallet.balance_service.get_erc20_balance_wei.return_value = (
            2000000000000000000  # 2 ETH (> 1.0 ETH)
        )
        wallet.balance_service.get_native_balance_wei.return_value = 2000000000000000000  # 2 ETH

        success = await wallet.swap("sender", 1.0, "SELL", "BUY")

        assert success is True
        cow_instance.swap.assert_called_once()


def test_transfer_from_erc20_success(wallet, mock_key_storage, mock_chain_interfaces):
    from_account = MagicMock(spec=StoredAccount)
    from_account.address = VALID_ADDR_2
    from_account.key = "private_key"

    sender_account = MagicMock(spec=StoredAccount)
    sender_account.address = VALID_ADDR_1

    mock_key_storage.get_account.side_effect = (
        lambda tag: from_account if tag == "from" else sender_account if tag == "sender" else None
    )

    chain_interface = mock_chain_interfaces.get.return_value
    chain_interface.chain.tokens = {"TEST": "0xTokenAddress"}

    wallet.transaction_service.sign_and_send.return_value = (
        True,
        {"status": 1, "transactionHash": b"hash"},
    )

    with patch("iwa.core.services.transfer.multisend.ERC20Contract") as mock_erc20:
        with patch("iwa.core.services.transfer.erc20.ERC20Contract", new=mock_erc20):
            erc20_instance = mock_erc20.return_value
            erc20_instance.address = VALID_ADDR_1
            erc20_instance.prepare_transfer_from_tx.return_value = {
                "data": b"transfer_from_data",
                "to": VALID_ADDR_1,
                "value": 0,
            }

            wallet.transfer_from_erc20("from", "sender", "recipient", "TEST", 1000)

            wallet.transaction_service.sign_and_send.assert_called_once()


def test_master_account(wallet, mock_account_service):
    mock_account = MagicMock(spec=StoredSafeAccount)
    mock_account_service.master_account = mock_account
    assert wallet.master_account == mock_account


def test_send_invalid_from_account(wallet, mock_key_storage):
    mock_key_storage.get_account.return_value = None
    wallet.send("unknown", "recipient", "native", 1000)
    # Should log error and return


def test_send_invalid_token(wallet, mock_key_storage, mock_chain_interfaces):
    account = MagicMock(spec=StoredAccount)
    account.address = "0xSender"
    mock_key_storage.get_account.return_value = account
    chain_interface = mock_chain_interfaces.get.return_value
    chain_interface.chain.get_token_address.return_value = None

    wallet.send("sender", "recipient", "INVALID", 1000)
    # Should log error and return


def test_send_native_safe(wallet, mock_key_storage, mock_chain_interfaces, mock_balance_service):
    account = StoredSafeAccount(
        address=VALID_ADDR_1, tag="safe", chains=["gnosis"], signers=[VALID_ADDR_2], threshold=1
    )
    mock_key_storage.get_account.return_value = account
    wallet.safe_service.execute_safe_transaction.return_value = "0xTxHash123"

    chain_interface = mock_chain_interfaces.get.return_value
    chain_interface.web3.from_wei.return_value = 1.0
    mock_balance_service.get_native_balance_wei.return_value = 2000000000000000000  # Enough balance

    # NOTE: SafeMultisig is no longer used directly in TransferService.
    # Safe transactions now go through SafeService.execute_safe_transaction().
    # Let's just assert the delegation happened.
    wallet.send("safe", "recipient", amount_wei=1000, token_address_or_name="native")
    wallet.safe_service.execute_safe_transaction.assert_called_once()


def test_send_erc20_safe(wallet, mock_key_storage, mock_chain_interfaces, mock_balance_service):
    account = StoredSafeAccount(
        address=VALID_ADDR_1, tag="safe", chains=["gnosis"], signers=[VALID_ADDR_2], threshold=1
    )
    mock_key_storage.get_account.return_value = account
    wallet.safe_service.execute_safe_transaction.return_value = "0xTxHash123"

    chain_interface = mock_chain_interfaces.get.return_value
    chain_interface.chain.tokens = {"TEST": "0xToken"}
    chain_interface.web3.from_wei.return_value = 1.0

    # Needs balance for check
    mock_balance_service.get_erc20_balance_wei.return_value = 2000
    mock_balance_service.get_native_balance_wei.return_value = (
        1000000000000000000  # Enough native for gas
    )

    with (
        patch("iwa.core.services.transfer.multisend.ERC20Contract") as mock_erc20,
        patch("iwa.core.services.transfer.erc20.ERC20Contract"),
    ):
        erc20_instance = mock_erc20.return_value
        erc20_instance.decimals = 18
        erc20_instance.address = "0xToken"
        erc20_instance.prepare_transfer_tx.return_value = {"data": b"data"}

        wallet.send("safe", "recipient", amount_wei=1000, token_address_or_name="TEST")
        wallet.safe_service.execute_safe_transaction.assert_called_once()


def test_multi_send_invalid_from_account(wallet, mock_key_storage):
    mock_key_storage.get_account.return_value = None
    wallet.multi_send("unknown", [])
    # Should log error and return


def test_multi_send_erc20_eoa_success(wallet, mock_key_storage, mock_chain_interfaces):
    account = MagicMock(spec=StoredAccount)
    account.address = VALID_ADDR_2
    mock_key_storage.get_account.return_value = account

    chain_interface = mock_chain_interfaces.get.return_value
    chain_interface.web3.to_wei.side_effect = lambda val, unit: int(float(val) * 10**18)
    chain_interface.chain.tokens = {"TEST": "0xTokenAddress"}

    transactions = [{"to": "0xRecipient", "amount": 1.0, "token": "TEST"}]

    wallet.transaction_service.sign_and_send.return_value = (True, {"status": 1})

    with (
        patch("iwa.core.services.transfer.multisend.ERC20Contract") as mock_erc20,
        patch("iwa.core.services.transfer.multisend.MultiSendCallOnlyContract") as mock_multisend,
    ):
        with patch("iwa.core.services.transfer.erc20.ERC20Contract", new=mock_erc20):
            erc20_instance = mock_erc20.return_value
            erc20_instance.prepare_transfer_from_tx.return_value = {
                "to": "0x",
                "data": b"",
                "value": 0,
            }

            multisend_instance = mock_multisend.return_value
            multisend_instance.prepare_tx.return_value = {"to": "0x", "data": b"", "value": 0}

            wallet.multi_send("sender", transactions)

            # Now EOA supports MultiSend with ERC20 (requires approval first)
            multisend_instance.prepare_tx.assert_called_once()
            assert wallet.transaction_service.sign_and_send.call_count == 2


def test_multi_send_safe(wallet, mock_key_storage, mock_chain_interfaces):
    account = StoredSafeAccount(
        address=VALID_ADDR_1, tag="safe", chains=["gnosis"], signers=[VALID_ADDR_2], threshold=1
    )
    mock_key_storage.get_account.return_value = account
    wallet.safe_service.execute_safe_transaction.return_value = "0xTxHash123"

    chain_interface = mock_chain_interfaces.get.return_value
    chain_interface.web3.to_wei.return_value = 1000

    with patch("iwa.core.services.transfer.multisend.MultiSendContract") as mock_multisend:
        multisend_instance = mock_multisend.return_value
        multisend_instance.prepare_tx.return_value = {
            "data": b"multisend_data",
            "to": "0xMultiSend",
            "value": 0,
        }

        transactions = [
            {
                "to": VALID_ADDR_2,
                "amount": 1.0,
                "token": "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE",
            }
        ]
        wallet.multi_send("safe", transactions)

        wallet.safe_service.execute_safe_transaction.assert_called_once()


def test_get_erc20_balance_eth_success(
    wallet, mock_key_storage, mock_chain_interfaces, mock_balance_service
):
    account = MagicMock(spec=StoredAccount)
    account.address = "0xAccount"
    mock_key_storage.get_account.return_value = account

    # Chain interface setup no longer strictly needed for balance service mock but helps consistency
    chain_interface = mock_chain_interfaces.get.return_value
    chain_interface.chain.tokens = {"TEST": "0xToken"}

    mock_balance_service.get_erc20_balance_eth.return_value = 10.0
    balance = wallet.get_erc20_balance_eth("account", "TEST")
    assert balance == 10.0


def test_get_erc20_balance_eth_token_not_found(wallet, mock_balance_service):
    mock_balance_service.get_erc20_balance_eth.return_value = None
    balance = wallet.get_erc20_balance_eth("account", "INVALID")
    assert balance is None


def test_get_erc20_balance_eth_account_not_found(wallet, mock_balance_service):
    mock_balance_service.get_erc20_balance_eth.return_value = None
    balance = wallet.get_erc20_balance_eth("account", "TEST")
    assert balance is None


def test_get_erc20_balance_wei_token_not_found(wallet, mock_balance_service):
    mock_balance_service.get_erc20_balance_wei.return_value = None
    balance = wallet.get_erc20_balance_wei("account", "INVALID")
    assert balance is None


def test_get_erc20_balance_wei_account_not_found(wallet, mock_balance_service):
    mock_balance_service.get_erc20_balance_wei.return_value = None
    balance = wallet.get_erc20_balance_wei("account", "TEST")
    assert balance is None

    balance = wallet.get_erc20_balance_wei("unknown", "TEST")
    assert balance is None


def test_get_erc20_allowance_token_not_found(wallet, mock_chain_interfaces):
    chain_interface = mock_chain_interfaces.get.return_value
    chain_interface.chain.get_token_address.return_value = None

    allowance = wallet.get_erc20_allowance("owner", "spender", "INVALID")
    assert allowance is None


def test_get_erc20_allowance_owner_not_found(wallet, mock_key_storage, mock_chain_interfaces):
    mock_key_storage.get_account.return_value = None
    chain_interface = mock_chain_interfaces.get.return_value
    chain_interface.chain.tokens = {"TEST": "0xToken"}

    allowance = wallet.get_erc20_allowance("unknown", "spender", "TEST")
    assert allowance is None


def test_approve_erc20_owner_not_found(wallet, mock_key_storage):
    mock_key_storage.get_account.return_value = None
    wallet.approve_erc20("unknown", "spender", "TEST", 1000)
    # Should log error and return


def test_approve_erc20_token_not_found(wallet, mock_key_storage, mock_chain_interfaces):
    account = MagicMock(spec=StoredAccount)
    account.address = "0xAccount"
    mock_key_storage.get_account.return_value = account
    chain_interface = mock_chain_interfaces.get.return_value
    chain_interface.get_token_address.return_value = None

    wallet.approve_erc20("owner", "spender", "INVALID", 1000)
    # Should return


def test_approve_erc20_tx_prep_failed(wallet, mock_key_storage, mock_chain_interfaces):
    account = MagicMock(spec=StoredAccount)
    account.address = VALID_ADDR_2
    mock_key_storage.get_account.return_value = account

    chain_interface = mock_chain_interfaces.get.return_value
    chain_interface.chain.tokens = {"TEST": "0xToken"}

    with (
        patch("iwa.core.services.transfer.multisend.ERC20Contract") as mock_erc20,
        patch("iwa.core.services.transfer.erc20.ERC20Contract"),
    ):
        erc20_instance = mock_erc20.return_value
        erc20_instance.allowance_wei.return_value = 0
        erc20_instance.prepare_approve_tx.return_value = None

        wallet.approve_erc20("owner", "spender", "TEST", 1000)
        # Should return


def test_approve_erc20_safe(wallet, mock_key_storage, mock_chain_interfaces):
    account = StoredSafeAccount(
        address=VALID_ADDR_1, tag="safe", chains=["gnosis"], signers=[VALID_ADDR_2], threshold=1
    )
    mock_key_storage.get_account.return_value = account
    wallet.safe_service.execute_safe_transaction.return_value = "0xTxHash123"

    chain_interface = mock_chain_interfaces.get.return_value
    chain_interface.chain.tokens = {"TEST": "0xToken"}
    chain_interface.web3.from_wei.return_value = 1.0

    with (
        patch("iwa.core.services.transfer.multisend.ERC20Contract") as mock_erc20,
        patch("iwa.core.services.transfer.erc20.ERC20Contract"),
    ):
        erc20_instance = mock_erc20.return_value
        erc20_instance.allowance_wei.return_value = 0
        erc20_instance.prepare_approve_tx.return_value = {"data": b"data"}

        wallet.approve_erc20("safe", "spender", "TEST", 1000)
        wallet.safe_service.execute_safe_transaction.assert_called_once()


def test_transfer_from_erc20_sender_not_found(wallet, mock_key_storage):
    # from_account found, sender not found
    from_account = MagicMock(spec=StoredAccount)
    mock_key_storage.get_account.side_effect = lambda tag: from_account if tag == "from" else None

    wallet.transfer_from_erc20("from", "unknown", "recipient", "TEST", 1000)
    # Should log error and return


def test_transfer_from_erc20_token_not_found(wallet, mock_key_storage, mock_chain_interfaces):
    account = MagicMock(spec=StoredAccount)
    account.address = "0xAccount"
    mock_key_storage.get_account.return_value = account

    chain_interface = mock_chain_interfaces.get.return_value
    chain_interface.get_token_address.return_value = None

    wallet.transfer_from_erc20("from", "sender", "recipient", "INVALID", 1000)
    # Should return


def test_transfer_from_erc20_tx_prep_failed(wallet, mock_key_storage, mock_chain_interfaces):
    account = MagicMock(spec=StoredAccount)
    account.address = VALID_ADDR_2
    mock_key_storage.get_account.return_value = account

    chain_interface = mock_chain_interfaces.get.return_value
    chain_interface.chain.tokens = {"TEST": "0xToken"}

    with (
        patch("iwa.core.services.transfer.multisend.ERC20Contract") as mock_erc20,
        patch("iwa.core.services.transfer.erc20.ERC20Contract"),
    ):
        erc20_instance = mock_erc20.return_value
        erc20_instance.prepare_transfer_from_tx.return_value = None

        wallet.transfer_from_erc20("from", "sender", "recipient", "TEST", 1000)
        # Should return


def test_transfer_from_erc20_safe(wallet, mock_key_storage, mock_chain_interfaces):
    from_account = MagicMock(spec=StoredSafeAccount)
    from_account.address = VALID_ADDR_1
    sender_account = MagicMock(spec=StoredAccount)
    sender_account.address = VALID_ADDR_2

    # Needs chains for Safe
    from_account.chains = ["gnosis"]
    from_account.threshold = 1  # Ensure is_safe=True

    mock_key_storage.get_account.side_effect = (
        lambda tag: from_account if tag == "safe" else sender_account
    )

    wallet.safe_service.execute_safe_transaction.return_value = "0xTxHash123"

    chain_interface = mock_chain_interfaces.get.return_value
    chain_interface.chain.tokens = {"TEST": "0xToken"}

    with (
        patch("iwa.core.services.transfer.multisend.ERC20Contract") as mock_erc20,
        patch("iwa.core.services.transfer.erc20.ERC20Contract"),
    ):
        erc20_instance = mock_erc20.return_value
        erc20_instance.prepare_transfer_from_tx.return_value = {"data": b"data"}
        erc20_instance.address = "0xToken"

        wallet.transfer_from_erc20("safe", "sender", "recipient", "TEST", 1000)
        wallet.safe_service.execute_safe_transaction.assert_called_once()


@pytest.mark.asyncio
async def test_swap_buy_no_amount(wallet):
    with pytest.raises(ValueError, match="Amount must be specified for buy orders"):
        await wallet.swap("account", None, "SELL", "BUY", order_type=OrderType.BUY)


@pytest.mark.asyncio
async def test_swap_max_retries(wallet, mock_key_storage, mock_chain_interfaces, mock_cow_swap):
    account = MagicMock(spec=StoredAccount)
    account.address = VALID_ADDR_2
    account.key = "private_key"
    mock_key_storage.get_account.return_value = account

    chain_interface = mock_chain_interfaces.get.return_value
    chain_interface.web3.to_wei.return_value = 1000
    chain_interface.web3.from_wei.side_effect = lambda val, unit: float(val) / 10**18
    chain_interface.sign_and_send_transaction.return_value = (True, {})

    cow_instance = mock_cow_swap.return_value
    cow_instance.get_max_sell_amount_wei = AsyncMock(return_value=1000)
    cow_instance.swap = AsyncMock(return_value=False)  # Always fail

    cow_instance.get_max_sell_amount_wei = AsyncMock(return_value=1000)
    cow_instance.swap = AsyncMock(return_value=False)  # Always fail

    with patch("iwa.core.services.transfer.multisend.ERC20Contract") as mock_erc20:
        mock_erc20.return_value.allowance_wei.return_value = 0

        # Mock balance
        wallet.balance_service.get_erc20_balance_wei.return_value = 2000000000000000000
        wallet.balance_service.get_native_balance_wei.return_value = 2000000000000000000

        await wallet.swap("account", 1.0, "SELL", "BUY")
        # Should log error after retries


def test_drain_from_account_not_found(wallet, mock_key_storage, mock_account_service):
    mock_account_service.resolve_account.return_value = None
    wallet.drain("unknown")
    # Should log error and return


def test_drain_no_token_balance(
    wallet, mock_key_storage, mock_chain_interfaces, mock_account_service, mock_balance_service
):
    account = MagicMock(spec=StoredAccount)
    account.address = VALID_ADDR_1
    mock_account_service.resolve_account.return_value = account

    chain_interface = mock_chain_interfaces.get.return_value
    chain_interface.chain.tokens = {"TEST": "0xToken"}
    mock_balance_service.get_native_balance_wei.return_value = 0
    mock_balance_service.get_erc20_balance_wei.return_value = 0

    wallet.drain("account")
    # Should log info and continue


def test_drain_native_safe(wallet, mock_key_storage, mock_chain_interfaces, mock_balance_service):
    account = StoredSafeAccount(
        address=VALID_ADDR_1, tag="safe", chains=["gnosis"], signers=[VALID_ADDR_2], threshold=1
    )
    mock_key_storage.get_account.return_value = account
    wallet.safe_service.execute_safe_transaction.return_value = "0xTxHash123"

    chain_interface = mock_chain_interfaces.get.return_value
    chain_interface.chain.tokens = {}
    mock_balance_service.get_native_balance_wei.return_value = 2000000000000000000
    chain_interface.web3.from_wei.return_value = 2.0

    with patch("iwa.core.services.transfer.multisend.MultiSendContract") as mock_multisend:
        mock_multisend.return_value.prepare_tx.return_value = {
            "to": "0xMultiSend",
            "data": b"multisend_data",
            "value": 0,
        }

        wallet.drain("safe")
        wallet.safe_service.execute_safe_transaction.assert_called_once()


def test_drain_not_enough_native_balance(
    wallet, mock_key_storage, mock_chain_interfaces, mock_account_service, mock_balance_service
):
    account = MagicMock(spec=StoredAccount)
    account.address = VALID_ADDR_1
    mock_account_service.resolve_account.return_value = account

    chain_interface = mock_chain_interfaces.get.return_value
    chain_interface.chain.tokens = {}
    mock_balance_service.get_native_balance_wei.return_value = 1000  # Very low balance
    chain_interface.web3.eth.gas_price = 1000000000

    wallet.drain("account")
    # Should log info and return


def test_send_erc20_tx_prep_failed(wallet, mock_key_storage, mock_chain_interfaces):
    account = MagicMock(spec=StoredAccount)
    account.address = VALID_ADDR_2
    mock_key_storage.get_account.return_value = account

    chain_interface = mock_chain_interfaces.get.return_value
    chain_interface.chain.tokens = {"TEST": "0xToken"}

    with (
        patch("iwa.core.services.transfer.multisend.ERC20Contract") as mock_erc20,
        patch("iwa.core.services.transfer.erc20.ERC20Contract"),
    ):
        erc20_instance = mock_erc20.return_value
        erc20_instance.prepare_transfer_tx.return_value = None

        wallet.send("sender", "recipient", "TEST", 1000)
        # Should return


def test_multi_send_tx_prep_failed(wallet, mock_key_storage, mock_chain_interfaces):
    account = StoredSafeAccount(
        address=VALID_ADDR_1, tag="safe", chains=["gnosis"], signers=[VALID_ADDR_2], threshold=1
    )
    mock_key_storage.get_account.return_value = account

    chain_interface = mock_chain_interfaces.get.return_value
    chain_interface.web3.to_wei.return_value = 1000

    with patch("iwa.core.services.transfer.multisend.MultiSendContract") as mock_multisend:
        multisend_instance = mock_multisend.return_value
        multisend_instance.prepare_tx.return_value = None

        transactions = [
            {
                "to": VALID_ADDR_2,
                "amount": 1.0,
                "token": "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE",
            }
        ]
        wallet.multi_send("safe", transactions)
        # Should return


@pytest.mark.asyncio
async def test_swap_entire_balance(wallet, mock_key_storage, mock_chain_interfaces, mock_cow_swap):
    account = MagicMock(spec=StoredAccount)
    account.address = VALID_ADDR_2
    mock_key_storage.get_account.return_value = account

    chain_interface = mock_chain_interfaces.get.return_value
    sell_token_address = VALID_ADDR_1
    chain_interface.chain.tokens = {"SELL": sell_token_address}
    chain_interface.get_token_address.return_value = sell_token_address
    chain_interface.chain.get_token_address.return_value = sell_token_address
    chain_interface.get_erc20_allowance.return_value = 0  # Added default allowance

    cow_instance = mock_cow_swap.return_value
    cow_instance.swap = AsyncMock(return_value=True)

    # Create a shared mock for both
    erc20_mock = MagicMock()
    erc20_instance = erc20_mock.return_value
    erc20_instance.balance_of_wei.return_value = 1000
    erc20_instance.allowance_wei.return_value = 0
    erc20_instance.prepare_approve_tx.return_value = {
        "data": b"approve_data",
        "to": VALID_ADDR_1,
        "value": 0,
    }

    with (
        patch("iwa.core.services.transfer.multisend.ERC20Contract", new=erc20_mock),
        patch("iwa.core.services.balance.ERC20Contract", new=erc20_mock),
    ):
        await wallet.swap("account", None, "SELL", "BUY")

        cow_instance.swap.assert_called_once()


def test_multi_send_erc20_safe_success(wallet, mock_key_storage, mock_chain_interfaces):
    account = StoredSafeAccount(
        address=VALID_ADDR_1, tag="safe", chains=["gnosis"], signers=[VALID_ADDR_2], threshold=1
    )
    mock_key_storage.get_account.return_value = account
    wallet.safe_service.execute_safe_transaction.return_value = "0xTxHash123"

    chain_interface = mock_chain_interfaces.get.return_value
    chain_interface.web3.to_wei.return_value = 1000
    chain_interface.chain.tokens = {"TEST": "0xToken"}

    with (
        patch("iwa.core.services.transfer.multisend.MultiSendContract") as mock_multisend,
        patch("iwa.core.services.transfer.multisend.ERC20Contract") as mock_erc20,
    ):
        multisend_instance = mock_multisend.return_value
        multisend_instance.prepare_tx.return_value = {
            "data": b"multisend_data",
            "to": "0xMultiSend",
            "value": 0,
        }

        erc20_instance = mock_erc20.return_value
        erc20_instance.decimals = 18
        erc20_instance.address = "0xToken"
        erc20_instance.prepare_transfer_tx.return_value = {"data": b"transfer_data"}

        transactions = [{"to": VALID_ADDR_2, "amount": 1.0, "token": "TEST"}]
        wallet.multi_send("safe", transactions)

        wallet.safe_service.execute_safe_transaction.assert_called_once()
        wallet.transaction_service.sign_and_send.assert_not_called()


# --- Negative Tests for TransferService ---


def test_send_whitelist_rejected(wallet, mock_key_storage, mock_chain_interfaces):
    """Test send fails when destination not in whitelist."""
    # Override the auto-mock to test actual security validation
    with patch(
        "iwa.core.services.transfer.TransferService._is_whitelisted_destination",
        return_value=False,  # Simulate rejected destination
    ):
        mock_key_storage.get_account.return_value = MagicMock(
            address=VALID_ADDR_1,
            tag="sender",
        )

        result = wallet.send(
            from_address_or_tag=VALID_ADDR_1,
            to_address_or_tag=VALID_ADDR_2,  # Not in whitelist
            token_address_or_name="native",
            amount_wei=10**18,
            chain_name="gnosis",
        )

        assert result is None  # Should fail due to whitelist


def test_send_unsupported_token_rejected(wallet, mock_key_storage, mock_chain_interfaces):
    """Test send fails when token is not supported."""
    # Override the auto-mock to test actual security validation
    with patch(
        "iwa.core.services.transfer.TransferService._is_supported_token",
        return_value=False,  # Simulate unsupported token
    ):
        mock_key_storage.get_account.return_value = MagicMock(
            address=VALID_ADDR_1,
            tag="sender",
        )

        result = wallet.send(
            from_address_or_tag=VALID_ADDR_1,
            to_address_or_tag=VALID_ADDR_2,
            token_address_or_name="UNKNOWN_TOKEN",  # Not supported
            amount_wei=10**18,
            chain_name="gnosis",
        )

        assert result is None  # Should fail due to unsupported token


def test_send_zero_amount(wallet, mock_key_storage, mock_chain_interfaces):
    """Test send with zero amount."""
    mock_key_storage.get_account.return_value = MagicMock(
        address=VALID_ADDR_1,
        tag="sender",
    )

    chain_interface = mock_chain_interfaces.get.return_value
    chain_interface.web3.from_wei.return_value = 0.0
    chain_interface.send_native_transfer.return_value = (True, "0xHash")

    wallet.send(
        from_address_or_tag=VALID_ADDR_1,
        to_address_or_tag=VALID_ADDR_2,
        token_address_or_name="native",
        amount_wei=0,
        chain_name="gnosis",
    )

    # Zero amount should be handled (may succeed or fail gracefully)
    # At minimum, should not crash


def test_send_same_source_destination(
    wallet, mock_key_storage, mock_balance_service, mock_chain_interfaces
):
    """Test send when source equals destination."""
    mock_key_storage.get_account.return_value = MagicMock(
        address=VALID_ADDR_1,
        tag="sender",
    )
    mock_balance_service.get_native_balance_wei.return_value = 10**19

    chain_interface = mock_chain_interfaces.get.return_value
    chain_interface.web3.from_wei.return_value = 1.0
    chain_interface.send_native_transfer.return_value = (True, "0xHash")

    # Self-transfer should work but is unusual
    wallet.send(
        from_address_or_tag=VALID_ADDR_1,
        to_address_or_tag=VALID_ADDR_1,  # Same as source
        token_address_or_name="native",
        amount_wei=10**18,
        chain_name="gnosis",
    )

    # Should not crash


def test_send_account_not_found(wallet, mock_key_storage):
    """Test send fails when from account doesn't exist."""
    mock_key_storage.get_account.return_value = None

    result = wallet.send(
        from_address_or_tag="nonexistent_account",
        to_address_or_tag=VALID_ADDR_2,
        token_address_or_name="native",
        amount_wei=10**18,
        chain_name="gnosis",
    )

    assert result is None


def test_multi_send_empty_transactions(wallet, mock_key_storage):
    """Test multi_send with empty transaction list."""
    mock_key_storage.get_account.return_value = MagicMock(
        address=VALID_ADDR_1,
        tag="sender",
    )

    # Empty list should be handled gracefully
    wallet.multi_send(VALID_ADDR_1, [])

    # Should not crash
