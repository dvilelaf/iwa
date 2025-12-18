import sys
from unittest.mock import MagicMock, patch

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

from unittest.mock import AsyncMock, MagicMock

import pytest

from iwa.core.chain import Gnosis
from iwa.core.models import StoredAccount, StoredSafeAccount
from iwa.core.wallet import Wallet
from iwa.plugins.gnosis.cow import OrderType


@pytest.fixture
def mock_key_storage():
    with patch("iwa.core.wallet.KeyStorage") as mock:
        instance = mock.return_value
        instance.accounts = {}
        instance.get_account.return_value = None
        yield instance


@pytest.fixture
def mock_chain_interfaces():
    with (
        patch("iwa.core.wallet.ChainInterfaces") as mock,
        patch("iwa.core.managers.ChainInterfaces", new=mock),
    ):
        instance = mock.return_value
        gnosis_interface = MagicMock()

        # Use a mock for the chain instead of the real Gnosis object
        mock_chain = MagicMock(spec=Gnosis)
        mock_chain.name = "Gnosis"
        mock_chain.native_currency = "xDAI"
        mock_chain.chain_id = 100
        mock_chain.tokens = {}
        mock_chain.get_token_address = MagicMock()
        gnosis_interface.chain = mock_chain

        gnosis_interface.web3 = MagicMock()
        instance.get.return_value = gnosis_interface
        yield instance


@pytest.fixture
def mock_cow_swap():
    with patch("iwa.core.wallet.CowSwap") as mock:
        yield mock


@pytest.fixture
def wallet(mock_key_storage, mock_chain_interfaces, mock_cow_swap):
    with patch("iwa.core.wallet.init_db"):
        return Wallet()


def test_wallet_init(wallet, mock_key_storage):
    assert wallet.key_storage == mock_key_storage


def test_get_token_address_native(wallet):
    chain = Gnosis()
    addr = wallet.get_token_address("native", chain)
    assert addr == "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE"


def test_get_token_address_valid_address(wallet):
    chain = Gnosis()
    valid_addr = "0x1234567890123456789012345678901234567890"
    addr = wallet.get_token_address(valid_addr, chain)
    assert addr == valid_addr


def test_get_token_address_by_name(wallet):
    chain = Gnosis()
    # Assuming OLAS is in Gnosis tokens
    addr = wallet.get_token_address("OLAS", chain)
    assert addr == chain.tokens["OLAS"]


def test_get_token_address_invalid(wallet):
    chain = Gnosis()
    addr = wallet.get_token_address("INVALID_TOKEN", chain)
    assert addr is None


def test_sign_and_send_transaction_account_not_found(wallet, mock_key_storage):
    mock_key_storage.get_account.return_value = None
    success, _ = wallet.sign_and_send_transaction({}, "unknown_account")
    assert success is False


def test_sign_and_send_transaction_success(wallet, mock_key_storage, mock_chain_interfaces):
    account = MagicMock(spec=StoredAccount)
    account.key = "private_key"
    account.address = "0x78731D3Ca6b7E34aC0F824c42a7cC18A495cabaB"
    mock_key_storage.get_account.return_value = account

    chain_interface = mock_chain_interfaces.get.return_value
    # Mock web3 calls used by TransactionManager
    chain_interface.web3.eth.get_transaction_count.return_value = 0
    chain_interface.web3.eth.send_raw_transaction.return_value = b"hash"
    receipt = MagicMock(status=1)
    chain_interface.web3.eth.wait_for_transaction_receipt.return_value = receipt

    # Mock KeyStorage.sign_transaction
    mock_signed_tx = MagicMock(rawTransaction=b"raw")
    mock_key_storage.sign_transaction.return_value = mock_signed_tx

    with patch.object(chain_interface, "wait_for_no_pending_tx", return_value=True):
        success, receipt = wallet.sign_and_send_transaction({}, "known_account")
        assert success is True
        mock_key_storage.sign_transaction.assert_called_once()
        chain_interface.web3.eth.send_raw_transaction.assert_called_once()


def test_list_accounts(wallet, mock_key_storage, mock_chain_interfaces):
    with patch("iwa.core.wallet.list_accounts") as mock_list_accounts:
        wallet.list_accounts("gnosis")
        mock_list_accounts.assert_called_once()


def test_get_native_balance_eth(wallet, mock_chain_interfaces):
    chain_interface = mock_chain_interfaces.get.return_value
    chain_interface.get_native_balance_eth.return_value = 1.5

    balance = wallet.get_native_balance_eth("0xAddress")
    assert balance == 1.5
    chain_interface.get_native_balance_eth.assert_called_with("0xAddress")


def test_get_native_balance_wei(wallet, mock_chain_interfaces):
    chain_interface = mock_chain_interfaces.get.return_value
    chain_interface.get_native_balance_wei.return_value = 1500000000000000000

    balance = wallet.get_native_balance_wei("0xAddress")
    assert balance == 1500000000000000000
    chain_interface.get_native_balance_wei.assert_called_with("0xAddress")


def test_send_native_success(wallet, mock_key_storage, mock_chain_interfaces):
    account = MagicMock(spec=StoredAccount)
    account.address = "0xSender"
    account.key = "private_key"
    mock_key_storage.get_account.return_value = account

    chain_interface = mock_chain_interfaces.get.return_value
    chain_interface.get_native_balance_wei.return_value = 2000000000000000000  # 2 ETH
    chain_interface.web3.eth.gas_price = 1000000000
    chain_interface.web3.eth.estimate_gas.return_value = 21000
    chain_interface.web3.from_wei.side_effect = lambda val, unit: float(val) / 10**18  # Simple mock

    # Mock return values for success
    chain_interface.sign_and_send_transaction.return_value = (True, {})
    chain_interface.send_native_transfer.return_value = (True, "0xHash")

    wallet.send("sender", "recipient", "native", 1000000000000000000)  # 1 ETH

    chain_interface.send_native_transfer.assert_called_once()


def test_send_erc20_success(wallet, mock_key_storage, mock_chain_interfaces):
    account = MagicMock(spec=StoredAccount)
    account.address = "0x78731D3Ca6b7E34aC0F824c42a7cC18A495cabaB"
    account.key = "private_key"
    mock_key_storage.get_account.return_value = account

    chain_interface = mock_chain_interfaces.get.return_value
    chain_interface.chain.tokens = {"TEST": "0xTokenAddress"}
    chain_interface.web3.from_wei.side_effect = lambda val, unit: float(val) / 10**18

    with patch("iwa.core.wallet.ERC20Contract") as mock_erc20:
        erc20_instance = mock_erc20.return_value
        erc20_instance.address = "0x5B38Da6a701c568545dCfcB03FcB875f56beddC4"
        erc20_instance.prepare_transfer_tx.return_value = {
            "data": b"transfer_data",
            "to": "0x5B38Da6a701c568545dCfcB03FcB875f56beddC4",
            "value": 0,
        }

        # Mock TransactionManager deps
        chain_interface.web3.eth.get_transaction_count.return_value = 0
        chain_interface.web3.eth.send_raw_transaction.return_value = b"hash"
        chain_interface.web3.eth.wait_for_transaction_receipt.return_value = MagicMock(status=1)
        mock_key_storage.sign_transaction.return_value = MagicMock(rawTransaction=b"raw")

        with patch.object(chain_interface, "wait_for_no_pending_tx", return_value=True):
            wallet.send("sender", "recipient", "TEST", 1000)

            erc20_instance.prepare_transfer_tx.assert_called_once()
            chain_interface.web3.eth.send_raw_transaction.assert_called_once()


def test_approve_erc20_success(wallet, mock_key_storage, mock_chain_interfaces):
    account = MagicMock(spec=StoredAccount)
    account.address = "0x78731D3Ca6b7E34aC0F824c42a7cC18A495cabaB"
    account.key = "private_key"
    mock_key_storage.get_account.return_value = account

    chain_interface = mock_chain_interfaces.get.return_value
    chain_interface.web3.from_wei.side_effect = lambda val, unit: float(val) / 10**18

    with patch("iwa.core.wallet.ERC20Contract") as mock_erc20:
        erc20_instance = mock_erc20.return_value
        erc20_instance.allowance_wei.return_value = 0
        erc20_instance.prepare_approve_tx.return_value = {
            "data": b"approve_data",
            "to": "0x5B38Da6a701c568545dCfcB03FcB875f56beddC4",
            "value": 0,
        }

        # Mock TransactionManager deps
        chain_interface.web3.eth.get_transaction_count.return_value = 0
        chain_interface.web3.eth.send_raw_transaction.return_value = b"hash"
        chain_interface.web3.eth.wait_for_transaction_receipt.return_value = MagicMock(status=1)
        mock_key_storage.sign_transaction.return_value = MagicMock(rawTransaction=b"raw")

        with patch.object(chain_interface, "wait_for_no_pending_tx", return_value=True):
            wallet.approve_erc20("owner", "spender", "TEST", 1000)

            erc20_instance.prepare_approve_tx.assert_called_once()
            chain_interface.web3.eth.send_raw_transaction.assert_called_once()


def test_approve_erc20_already_sufficient(wallet, mock_key_storage, mock_chain_interfaces):
    account = MagicMock(spec=StoredAccount)
    account.address = "0x78731D3Ca6b7E34aC0F824c42a7cC18A495cabaB"
    mock_key_storage.get_account.return_value = account

    with patch("iwa.core.wallet.ERC20Contract") as mock_erc20:
        erc20_instance = mock_erc20.return_value
        erc20_instance.allowance_wei.return_value = 2000

        wallet.approve_erc20("owner", "spender", "TEST", 1000)

        erc20_instance.prepare_approve_tx.assert_not_called()


def test_multi_send_success(wallet, mock_key_storage, mock_chain_interfaces):
    account = MagicMock(spec=StoredAccount)
    account.address = "0x78731D3Ca6b7E34aC0F824c42a7cC18A495cabaB"
    account.key = "private_key"
    mock_key_storage.get_account.return_value = account

    chain_interface = mock_chain_interfaces.get.return_value
    chain_interface.web3.to_wei.return_value = 1000
    # Mock TransactionManager deps
    chain_interface.web3.eth.get_transaction_count.return_value = 0
    chain_interface.web3.eth.send_raw_transaction.return_value = b"hash"
    chain_interface.web3.eth.wait_for_transaction_receipt.return_value = MagicMock(status=1)
    mock_key_storage.sign_transaction.return_value = MagicMock(rawTransaction=b"raw")

    with patch("iwa.core.wallet.MultiSendCallOnlyContract") as mock_multisend:
        multisend_instance = mock_multisend.return_value
        multisend_instance.prepare_tx.return_value = {
            "data": b"multisend_data",
            "to": "0xMultiSend",
            "value": 0,
        }

        transactions = [
            {
                "to": "0xRecipient",
                "amount": 1.0,
                "token": "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE",
            }
        ]

        with patch.object(chain_interface, "wait_for_no_pending_tx", return_value=True):
            wallet.multi_send("sender", transactions)

            multisend_instance.prepare_tx.assert_called_once()
            chain_interface.web3.eth.send_raw_transaction.assert_called_once()


def test_drain_native_success(wallet, mock_key_storage, mock_chain_interfaces):
    account = MagicMock(spec=StoredAccount)
    account.address = "0xSender"
    account.key = "private_key"
    mock_key_storage.get_account.return_value = account

    chain_interface = mock_chain_interfaces.get.return_value
    chain_interface.chain.tokens = {}
    chain_interface.get_native_balance_wei.return_value = 2000000000000000000  # 2 ETH
    chain_interface.web3.eth.gas_price = 1000000000
    chain_interface.web3.from_wei.side_effect = lambda val, unit: float(val) / 10**18

    # Mock return values
    chain_interface.sign_and_send_transaction.return_value = (True, {})
    chain_interface.send_native_transfer.return_value = (True, "0xHash")

    wallet.drain("sender", "recipient")

    chain_interface.send_native_transfer.assert_called_once()


def test_drain_erc20_success(wallet, mock_key_storage, mock_chain_interfaces):
    account = MagicMock(spec=StoredAccount)
    account.address = "0x78731D3Ca6b7E34aC0F824c42a7cC18A495cabaB"
    account.key = "private_key"
    mock_key_storage.get_account.return_value = account

    chain_interface = mock_chain_interfaces.get.return_value
    chain_interface.chain.tokens = {"TEST": "0xTokenAddress"}
    chain_interface.get_native_balance_wei.return_value = 0
    chain_interface.web3.from_wei.side_effect = lambda val, unit: float(val) / 10**18

    with patch("iwa.core.wallet.ERC20Contract") as mock_erc20:
        erc20_instance = mock_erc20.return_value
        erc20_instance.address = "0x5B38Da6a701c568545dCfcB03FcB875f56beddC4"
        erc20_instance.balance_of_wei.return_value = 1000
        erc20_instance.prepare_transfer_tx.return_value = {
            "data": b"transfer_data",
            "to": "0x5B38Da6a701c568545dCfcB03FcB875f56beddC4",
            "value": 0,
        }

        # Mock TransactionManager deps
        chain_interface.web3.eth.get_transaction_count.return_value = 0
        chain_interface.web3.eth.send_raw_transaction.return_value = b"hash"
        chain_interface.web3.eth.wait_for_transaction_receipt.return_value = MagicMock(status=1)
        mock_key_storage.sign_transaction.return_value = MagicMock(rawTransaction=b"raw")

        with patch.object(chain_interface, "wait_for_no_pending_tx", return_value=True):
            wallet.drain("sender", "recipient")

            erc20_instance.prepare_transfer_tx.assert_called_once()
            chain_interface.web3.eth.send_raw_transaction.assert_called_once()


@pytest.mark.asyncio
async def test_swap_success(wallet, mock_key_storage, mock_chain_interfaces, mock_cow_swap):
    account = MagicMock(spec=StoredAccount)
    account.address = "0x78731D3Ca6b7E34aC0F824c42a7cC18A495cabaB"
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

    with patch("iwa.core.wallet.ERC20Contract") as mock_erc20:
        erc20_instance = mock_erc20.return_value
        erc20_instance.allowance_wei.return_value = 0
        erc20_instance.prepare_approve_tx.return_value = {
            "data": b"approve_data",
            "to": "0x5B38Da6a701c568545dCfcB03FcB875f56beddC4",
            "value": 0,
        }
        chain_interface.sign_and_send_transaction.return_value = (True, {})

        success = await wallet.swap("sender", 1.0, "SELL", "BUY")

        assert success is True
        cow_instance.swap.assert_called_once()


def test_transfer_from_erc20_success(wallet, mock_key_storage, mock_chain_interfaces):
    from_account = MagicMock(spec=StoredAccount)
    from_account.address = "0x78731D3Ca6b7E34aC0F824c42a7cC18A495cabaB"
    from_account.key = "private_key"

    sender_account = MagicMock(spec=StoredAccount)
    sender_account.address = "0x61a4f49e9dD1f90EB312889632FA956a21353720"

    mock_key_storage.get_account.side_effect = (
        lambda tag: from_account if tag == "from" else sender_account if tag == "sender" else None
    )

    chain_interface = mock_chain_interfaces.get.return_value
    chain_interface.chain.tokens = {"TEST": "0xTokenAddress"}

    with patch("iwa.core.wallet.ERC20Contract") as mock_erc20:
        erc20_instance = mock_erc20.return_value
        erc20_instance.address = "0x5B38Da6a701c568545dCfcB03FcB875f56beddC4"
        erc20_instance.prepare_transfer_from_tx.return_value = {
            "data": b"transfer_from_data",
            "to": "0x5B38Da6a701c568545dCfcB03FcB875f56beddC4",
            "value": 0,
        }

        # Mock TransactionManager deps
        chain_interface.web3.eth.get_transaction_count.return_value = 0
        chain_interface.web3.eth.send_raw_transaction.return_value = b"hash"
        chain_interface.web3.eth.wait_for_transaction_receipt.return_value = MagicMock(status=1)
        mock_key_storage.sign_transaction.return_value = MagicMock(rawTransaction=b"raw")

        with patch.object(chain_interface, "wait_for_no_pending_tx", return_value=True):
            wallet.transfer_from_erc20("from", "sender", "recipient", "TEST", 1000)

            erc20_instance.prepare_transfer_from_tx.assert_called_once()
            chain_interface.web3.eth.send_raw_transaction.assert_called_once()


def test_master_account(wallet, mock_key_storage):
    mock_account = MagicMock(spec=StoredSafeAccount)
    mock_key_storage.master_account = mock_account
    assert wallet.master_account == mock_account


def test_send_invalid_from_account(wallet, mock_key_storage):
    mock_key_storage.get_account.return_value = None
    wallet.send("unknown", "recipient", "native", 1000)
    # Should log error and return, no exception
    # Should log error and return


def test_send_invalid_token(wallet, mock_key_storage, mock_chain_interfaces):
    account = MagicMock(spec=StoredAccount)
    account.address = "0xSender"
    mock_key_storage.get_account.return_value = account
    chain_interface = mock_chain_interfaces.get.return_value
    chain_interface.chain.get_token_address.return_value = None

    wallet.send("sender", "recipient", "INVALID", 1000)
    # Should log error and return


def test_send_native_safe(wallet, mock_key_storage, mock_chain_interfaces):
    account = MagicMock(spec=StoredSafeAccount)
    account.address = "0xSafe"
    mock_key_storage.get_account.return_value = account
    mock_key_storage.sign_safe_transaction.side_effect = lambda tag, callback: callback(["key1"])

    chain_interface = mock_chain_interfaces.get.return_value
    chain_interface.web3.from_wei.return_value = 1.0

    with patch("iwa.core.wallet.SafeMultisig") as mock_safe:
        safe_instance = mock_safe.return_value
        wallet.send("safe", "recipient", "native", 1000)
        safe_instance.send_tx.assert_called_once()


def test_send_erc20_safe(wallet, mock_key_storage, mock_chain_interfaces):
    account = MagicMock(spec=StoredSafeAccount)
    account.address = "0xSafe"
    mock_key_storage.get_account.return_value = account
    mock_key_storage.sign_safe_transaction.side_effect = lambda tag, callback: callback(["key1"])

    chain_interface = mock_chain_interfaces.get.return_value
    chain_interface.chain.tokens = {"TEST": "0xToken"}
    chain_interface.web3.from_wei.return_value = 1.0

    with (
        patch("iwa.core.wallet.ERC20Contract") as mock_erc20,
        patch("iwa.core.wallet.SafeMultisig") as mock_safe,
    ):
        erc20_instance = mock_erc20.return_value
        erc20_instance.address = "0xToken"
        erc20_instance.prepare_transfer_tx.return_value = {"data": b"data"}

        safe_instance = mock_safe.return_value

        wallet.send("safe", "recipient", "TEST", 1000)
        safe_instance.send_tx.assert_called_once()


def test_multi_send_invalid_from_account(wallet, mock_key_storage):
    mock_key_storage.get_account.return_value = None
    wallet.multi_send("unknown", [])
    # Should log error and return


def test_multi_send_erc20_not_safe(wallet, mock_key_storage):
    account = MagicMock(spec=StoredAccount)  # Not a Safe account
    mock_key_storage.get_account.return_value = account

    transactions = [{"to": "0xRecipient", "amount": 1.0, "token": "TEST"}]

    with pytest.raises(ValueError, match="Multisend with ERC20 tokens requires a Safe account"):
        wallet.multi_send("sender", transactions)


def test_multi_send_safe(wallet, mock_key_storage, mock_chain_interfaces):
    account = MagicMock(spec=StoredSafeAccount)
    account.address = "0xSafe"
    mock_key_storage.get_account.return_value = account
    mock_key_storage.sign_safe_transaction.side_effect = lambda tag, callback: callback(["key1"])

    chain_interface = mock_chain_interfaces.get.return_value
    chain_interface.web3.to_wei.return_value = 1000

    with (
        patch("iwa.core.wallet.MultiSendContract") as mock_multisend,
        patch("iwa.core.wallet.SafeMultisig") as mock_safe,
    ):
        multisend_instance = mock_multisend.return_value
        multisend_instance.prepare_tx.return_value = {
            "data": b"multisend_data",
            "to": "0xMultiSend",
            "value": 0,
        }

        safe_instance = mock_safe.return_value

        transactions = [
            {
                "to": "0xRecipient",
                "amount": 1.0,
                "token": "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE",
            }
        ]
        wallet.multi_send("safe", transactions)

        safe_instance.send_tx.assert_called_once()


def test_get_erc20_balance_eth_success(wallet, mock_key_storage, mock_chain_interfaces):
    account = MagicMock(spec=StoredAccount)
    account.address = "0xAccount"
    mock_key_storage.get_account.return_value = account

    chain_interface = mock_chain_interfaces.get.return_value
    chain_interface.chain.tokens = {"TEST": "0xToken"}

    with patch("iwa.core.wallet.ERC20Contract") as mock_erc20:
        erc20_instance = mock_erc20.return_value
        erc20_instance.balance_of_eth.return_value = 10.0

        balance = wallet.get_erc20_balance_eth("account", "TEST")
        assert balance == 10.0


def test_get_erc20_balance_eth_token_not_found(wallet, mock_chain_interfaces):
    chain_interface = mock_chain_interfaces.get.return_value
    chain_interface.chain.get_token_address.return_value = None

    balance = wallet.get_erc20_balance_eth("account", "INVALID")
    assert balance is None


def test_get_erc20_balance_eth_account_not_found(wallet, mock_key_storage, mock_chain_interfaces):
    mock_key_storage.get_account.return_value = None
    chain_interface = mock_chain_interfaces.get.return_value
    chain_interface.chain.tokens = {"TEST": "0xToken"}

    balance = wallet.get_erc20_balance_eth("unknown", "TEST")
    assert balance is None


def test_get_erc20_balance_wei_token_not_found(wallet, mock_chain_interfaces):
    chain_interface = mock_chain_interfaces.get.return_value
    chain_interface.chain.get_token_address.return_value = None

    balance = wallet.get_erc20_balance_wei("account", "INVALID")
    assert balance is None


def test_get_erc20_balance_wei_account_not_found(wallet, mock_key_storage, mock_chain_interfaces):
    mock_key_storage.get_account.return_value = None
    chain_interface = mock_chain_interfaces.get.return_value
    chain_interface.chain.tokens = {"TEST": "0xToken"}

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
    account.address = "0xAccount"
    mock_key_storage.get_account.return_value = account

    chain_interface = mock_chain_interfaces.get.return_value
    chain_interface.chain.tokens = {"TEST": "0xToken"}

    with patch("iwa.core.wallet.ERC20Contract") as mock_erc20:
        erc20_instance = mock_erc20.return_value
        erc20_instance.allowance_wei.return_value = 0
        erc20_instance.prepare_approve_tx.return_value = None

        wallet.approve_erc20("owner", "spender", "TEST", 1000)
        # Should return


def test_approve_erc20_safe(wallet, mock_key_storage, mock_chain_interfaces):
    account = MagicMock(spec=StoredSafeAccount)
    account.address = "0xSafe"
    mock_key_storage.get_account.return_value = account
    mock_key_storage.sign_safe_transaction.side_effect = lambda tag, callback: callback(["key1"])

    chain_interface = mock_chain_interfaces.get.return_value
    chain_interface.chain.tokens = {"TEST": "0xToken"}
    chain_interface.web3.from_wei.return_value = 1.0

    with (
        patch("iwa.core.wallet.ERC20Contract") as mock_erc20,
        patch("iwa.core.wallet.SafeMultisig") as mock_safe,
    ):
        erc20_instance = mock_erc20.return_value
        erc20_instance.allowance_wei.return_value = 0
        erc20_instance.prepare_approve_tx.return_value = {"data": b"data"}

        safe_instance = mock_safe.return_value

        wallet.approve_erc20("safe", "spender", "TEST", 1000)
        safe_instance.send_tx.assert_called_once()


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
    account.address = "0xAccount"
    mock_key_storage.get_account.return_value = account

    chain_interface = mock_chain_interfaces.get.return_value
    chain_interface.chain.tokens = {"TEST": "0xToken"}

    with patch("iwa.core.wallet.ERC20Contract") as mock_erc20:
        erc20_instance = mock_erc20.return_value
        erc20_instance.prepare_transfer_from_tx.return_value = None

        wallet.transfer_from_erc20("from", "sender", "recipient", "TEST", 1000)
        # Should return


def test_transfer_from_erc20_safe(wallet, mock_key_storage, mock_chain_interfaces):
    from_account = MagicMock(spec=StoredSafeAccount)
    from_account.address = "0xSafe"
    sender_account = MagicMock(spec=StoredAccount)
    sender_account.address = "0xSender"

    mock_key_storage.get_account.side_effect = (
        lambda tag: from_account if tag == "safe" else sender_account
    )

    def side_effect(tag, callback):
        return callback(["key1"])

    mock_key_storage.sign_safe_transaction.side_effect = side_effect

    chain_interface = mock_chain_interfaces.get.return_value
    chain_interface.chain.tokens = {"TEST": "0xToken"}

    with (
        patch("iwa.core.wallet.ERC20Contract") as mock_erc20,
        patch("iwa.core.wallet.SafeMultisig") as mock_safe,
    ):
        erc20_instance = mock_erc20.return_value
        erc20_instance.prepare_transfer_from_tx.return_value = {"data": b"data"}

        safe_instance = mock_safe.return_value

        wallet.transfer_from_erc20("safe", "sender", "recipient", "TEST", 1000)
        safe_instance.send_tx.assert_called_once()


@pytest.mark.asyncio
async def test_swap_buy_no_amount(wallet):
    with pytest.raises(ValueError, match="Amount must be specified for buy orders"):
        await wallet.swap("account", None, "SELL", "BUY", order_type=OrderType.BUY)


@pytest.mark.asyncio
async def test_swap_max_retries(wallet, mock_key_storage, mock_chain_interfaces, mock_cow_swap):
    account = MagicMock(spec=StoredAccount)
    account.address = "0x78731D3Ca6b7E34aC0F824c42a7cC18A495cabaB"
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

    with patch("iwa.core.wallet.ERC20Contract") as mock_erc20:
        mock_erc20.return_value.allowance_wei.return_value = 0
        await wallet.swap("account", 1.0, "SELL", "BUY")
        # Should log error after retries


def test_drain_from_account_not_found(wallet, mock_key_storage):
    mock_key_storage.get_account.return_value = None
    wallet.drain("unknown")
    # Should log error and return


def test_drain_no_token_balance(wallet, mock_key_storage, mock_chain_interfaces):
    account = MagicMock(spec=StoredAccount)
    account.address = "0xAccount"
    mock_key_storage.get_account.return_value = account

    chain_interface = mock_chain_interfaces.get.return_value
    chain_interface.chain.tokens = {"TEST": "0xToken"}
    chain_interface.get_native_balance_wei.return_value = 0

    with patch("iwa.core.wallet.ERC20Contract") as mock_erc20:
        erc20_instance = mock_erc20.return_value
        erc20_instance.balance_of_wei.return_value = 0

        wallet.drain("account")
        # Should log info and continue


def test_drain_native_safe(wallet, mock_key_storage, mock_chain_interfaces):
    account = MagicMock(spec=StoredSafeAccount)
    account.address = "0xSafe"
    mock_key_storage.get_account.return_value = account
    mock_key_storage.sign_safe_transaction.side_effect = lambda tag, callback: callback(["key1"])

    chain_interface = mock_chain_interfaces.get.return_value
    chain_interface.chain.tokens = {}
    chain_interface.get_native_balance_wei.return_value = 2000000000000000000
    chain_interface.web3.from_wei.return_value = 2.0

    with patch("iwa.core.wallet.SafeMultisig") as mock_safe:
        safe_instance = mock_safe.return_value
        wallet.drain("safe")
        safe_instance.send_tx.assert_called_once()


def test_drain_not_enough_native_balance(wallet, mock_key_storage, mock_chain_interfaces):
    account = MagicMock(spec=StoredAccount)
    account.address = "0xAccount"
    mock_key_storage.get_account.return_value = account

    chain_interface = mock_chain_interfaces.get.return_value
    chain_interface.chain.tokens = {}
    chain_interface.get_native_balance_wei.return_value = 1000  # Very low balance
    chain_interface.web3.eth.gas_price = 1000000000

    wallet.drain("account")
    # Should log info and return


def test_send_erc20_tx_prep_failed(wallet, mock_key_storage, mock_chain_interfaces):
    account = MagicMock(spec=StoredAccount)
    account.address = "0xSender"
    mock_key_storage.get_account.return_value = account

    chain_interface = mock_chain_interfaces.get.return_value
    chain_interface.chain.tokens = {"TEST": "0xToken"}

    with patch("iwa.core.wallet.ERC20Contract") as mock_erc20:
        erc20_instance = mock_erc20.return_value
        erc20_instance.prepare_transfer_tx.return_value = None

        wallet.send("sender", "recipient", "TEST", 1000)
        # Should return


def test_multi_send_tx_prep_failed(wallet, mock_key_storage, mock_chain_interfaces):
    account = MagicMock(spec=StoredSafeAccount)
    account.address = "0xSafe"
    mock_key_storage.get_account.return_value = account

    chain_interface = mock_chain_interfaces.get.return_value
    chain_interface.web3.to_wei.return_value = 1000

    with patch("iwa.core.wallet.MultiSendContract") as mock_multisend:
        multisend_instance = mock_multisend.return_value
        multisend_instance.prepare_tx.return_value = None

        transactions = [
            {
                "to": "0xRecipient",
                "amount": 1.0,
                "token": "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE",
            }
        ]
        wallet.multi_send("safe", transactions)
        # Should return


@pytest.mark.asyncio
async def test_swap_entire_balance(wallet, mock_key_storage, mock_chain_interfaces, mock_cow_swap):
    account = MagicMock(spec=StoredAccount)
    account.address = "0x78731D3Ca6b7E34aC0F824c42a7cC18A495cabaB"
    account.key = "private_key"
    mock_key_storage.get_account.return_value = account

    chain_interface = mock_chain_interfaces.get.return_value
    chain_interface.chain.tokens = {"SELL": "0xSellToken"}
    chain_interface.web3.from_wei.side_effect = lambda val, unit: float(val) / 10**18
    chain_interface.sign_and_send_transaction.return_value = (True, {})

    cow_instance = mock_cow_swap.return_value
    cow_instance.swap = AsyncMock(return_value=True)

    with patch("iwa.core.wallet.ERC20Contract") as mock_erc20:
        erc20_instance = mock_erc20.return_value
        erc20_instance.balance_of_wei.return_value = 1000
        erc20_instance.allowance_wei.return_value = 0
        erc20_instance.prepare_approve_tx.return_value = {
            "data": b"approve_data",
            "to": "0x5B38Da6a701c568545dCfcB03FcB875f56beddC4",
            "value": 0,
        }

        await wallet.swap("account", None, "SELL", "BUY")

        cow_instance.swap.assert_called_once()


def test_multi_send_erc20_safe_success(wallet, mock_key_storage, mock_chain_interfaces):
    account = MagicMock(spec=StoredSafeAccount)
    account.address = "0xSafe"
    mock_key_storage.get_account.return_value = account
    mock_key_storage.sign_safe_transaction.side_effect = lambda tag, callback: callback(["key1"])

    chain_interface = mock_chain_interfaces.get.return_value
    chain_interface.web3.to_wei.return_value = 1000
    chain_interface.chain.tokens = {"TEST": "0xToken"}

    with (
        patch("iwa.core.wallet.MultiSendContract") as mock_multisend,
        patch("iwa.core.wallet.SafeMultisig") as mock_safe,
        patch("iwa.core.wallet.ERC20Contract") as mock_erc20,
    ):
        multisend_instance = mock_multisend.return_value
        multisend_instance.prepare_tx.return_value = {
            "data": b"multisend_data",
            "to": "0xMultiSend",
            "value": 0,
        }

        safe_instance = mock_safe.return_value

        erc20_instance = mock_erc20.return_value
        erc20_instance.address = "0xToken"
        erc20_instance.prepare_transfer_tx.return_value = {"data": b"transfer_data"}

        transactions = [{"to": "0xRecipient", "amount": 1.0, "token": "TEST"}]
        wallet.multi_send("safe", transactions)

        safe_instance.send_tx.assert_called_once()
        erc20_instance.prepare_transfer_tx.assert_called_once()


def test_transaction_retry_rpc_rotation(wallet, mock_key_storage, mock_chain_interfaces):
    # Setup account
    account = MagicMock(spec=StoredAccount)
    account.address = "0x78731D3Ca6b7E34aC0F824c42a7cC18A495cabaB"
    account.key = "private_key"
    mock_key_storage.get_account.return_value = account
    mock_key_storage.sign_transaction.return_value = MagicMock(rawTransaction=b"raw")

    # Setup chain interface
    chain_interface = mock_chain_interfaces.get.return_value
    # Mock chain info
    chain_interface.chain.chain_id = 100
    chain_interface.chain.rpcs = ["http://rpc1", "http://rpc2"]
    chain_interface.web3.eth.get_transaction_count.return_value = 0
    chain_interface.web3.eth.wait_for_transaction_receipt.return_value = MagicMock(status=1)

    # First attempt fails with connection error
    # Second attempt succeeds
    chain_interface.web3.eth.send_raw_transaction.side_effect = [
        Exception("Connection error"),
        b"hash",
    ]

    # Mock rotate_rpc to succeed
    chain_interface.rotate_rpc.return_value = True

    with patch.object(chain_interface, "wait_for_no_pending_tx", return_value=True):
        # We use a simple send to trigger transaction manager
        with patch.object(wallet.transaction_manager, "_is_gas_too_low_error", return_value=False):
            # Speed up sleep
            with patch("time.sleep"):
                success, receipt = wallet.sign_and_send_transaction({}, "account")

                assert success is True
                assert chain_interface.rotate_rpc.called
                assert chain_interface.web3.eth.send_raw_transaction.call_count == 2
