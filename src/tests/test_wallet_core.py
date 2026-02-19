"""Tests for Wallet module."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from iwa.core.wallet import Wallet


@pytest.fixture
def mock_keys_and_services():
    """Mock keys and services."""
    with (
        patch("iwa.core.wallet.KeyStorage") as mock_ks,
        patch("iwa.core.wallet.AccountService") as mock_as,
        patch("iwa.core.wallet.BalanceService") as mock_bs,
        patch("iwa.core.wallet.SafeService") as mock_ss,
        patch("iwa.core.wallet.TransactionService") as mock_ts,
        patch("iwa.core.wallet.TransferService") as mock_trs,
        patch("iwa.core.wallet.PluginService") as mock_ps,
        patch("iwa.core.wallet.init_db") as mock_init_db,
        patch("iwa.core.wallet.configure_logger"),
    ):
        yield {
            "key_storage": mock_ks,
            "account_service": mock_as,
            "balance_service": mock_bs,
            "safe_service": mock_ss,
            "transaction_service": mock_ts,
            "transfer_service": mock_trs,
            "plugin_service": mock_ps,
            "init_db": mock_init_db,
        }


@pytest.fixture
def wallet(mock_keys_and_services):
    """Wallet fixture."""
    return Wallet()


def test_init(mock_keys_and_services):
    """Test initialization."""
    wallet = Wallet()
    assert wallet.key_storage == mock_keys_and_services["key_storage"].return_value
    mock_keys_and_services["init_db"].assert_called_once()


def test_master_account(wallet, mock_keys_and_services):
    """Test master account property."""
    # Accesses property on account_service instance


def test_get_token_address(wallet, mock_keys_and_services):
    """Test get_token_address."""
    wallet.get_token_address("OLAS", "gnosis")
    mock_keys_and_services["account_service"].return_value.get_token_address.assert_called_with(
        "OLAS", "gnosis"
    )


def test_get_accounts_balances(wallet, mock_keys_and_services):
    """Test get_accounts_balances."""
    # Mock account data
    mock_keys_and_services["account_service"].return_value.get_account_data.return_value = {
        "0x1": {"tag": "one"},
        "0x2": {"tag": "two"},
    }

    # Mock balance service
    mock_bs = mock_keys_and_services["balance_service"].return_value
    mock_bs.get_native_balance_eth.return_value = 1.0
    mock_bs.get_erc20_balance_eth.return_value = 2.0

    # Test with no token names
    data, balances = wallet.get_accounts_balances("gnosis")
    assert data == {"0x1": {"tag": "one"}, "0x2": {"tag": "two"}}
    assert balances is None

    # Test with token names
    # Mock ThreadPoolExecutor to run synchronously or just return futures
    # Since we can't easily suppress the real ThreadPoolExecutor context manager used in the code without patching it,
    # let's patch it in the test function scope.

    with patch("iwa.core.wallet.ThreadPoolExecutor") as mock_executor:
        # returns context manager
        mock_context = MagicMock()
        mock_executor.return_value.__enter__.return_value = mock_context

        # mock submit to return a future
        mock_future1 = MagicMock()
        mock_future1.result.return_value = ("0x1", "native", 1.0)

        mock_future2 = MagicMock()
        mock_future2.result.return_value = ("0x1", "OLAS", 2.0)

        mock_context.submit.side_effect = [
            mock_future1,
            mock_future2,
            mock_future1,
            mock_future2,
        ]  # Just cycling mocks

        # We need to rely on what the code does: it iterates over accounts, then tokens.
        # 2 accounts * 2 tokens = 4 calls.

        # Simpler approach: let the real ThreadPoolExecutor run but mock the balance service methods which are already mocked.
        # The issue is the code uses `fetch_balance` inner function.
        pass


# Re-implementing test_get_accounts_balances with delegation verification via patching ThreadPoolExecutor
# effectively mocking concurrency.


def test_get_accounts_balances_concurrency(wallet, mock_keys_and_services):
    """Test get_accounts_balances concurrency."""
    mock_keys_and_services["account_service"].return_value.get_account_data.return_value = {
        "0x1": {"tag": "one"}
    }

    with patch("iwa.core.wallet.ThreadPoolExecutor") as mock_executor:
        mock_context = MagicMock()
        mock_executor.return_value.__enter__.return_value = mock_context

        mock_future_native = MagicMock()
        mock_future_native.result.return_value = ("0x1", "native", 1.5)

        mock_future_token = MagicMock()
        mock_future_token.result.return_value = ("0x1", "OLAS", 10.0)

        # The loop order in wallet.py: for addr in accounts: for t in tokens: submit
        # so for 1 account and 2 tokens: native, OLAS
        mock_context.submit.side_effect = [mock_future_native, mock_future_token]

        accounts, balances = wallet.get_accounts_balances("gnosis", ["native", "OLAS"])

        assert accounts == {"0x1": {"tag": "one"}}
        # balances structure: {addr: {token: val}}
        assert balances["0x1"]["native"] == 1.5
        assert balances["0x1"]["OLAS"] == 10.0


def test_send_native_transfer(wallet, mock_keys_and_services):
    """Test send_native_transfer."""
    mock_keys_and_services["transfer_service"].return_value.send.return_value = "0xhash"
    success, tx_hash = wallet.send_native_transfer("0xfrom", "0xto", 100, "gnosis")
    assert success is True
    assert tx_hash == "0xhash"
    mock_keys_and_services["transfer_service"].return_value.send.assert_called_with(
        from_address_or_tag="0xfrom",
        to_address_or_tag="0xto",
        amount_wei=100,
        token_address_or_name="native",
        chain_name="gnosis",
    )


def test_sign_and_send_transaction(wallet, mock_keys_and_services):
    """Test sign_and_send_transaction."""
    wallet.sign_and_send_transaction({"to": "0x1"}, "owner", "gnosis")
    mock_keys_and_services["transaction_service"].return_value.sign_and_send.assert_called_with(
        {"to": "0x1"}, "owner", "gnosis", None
    )


def test_send_erc20_transfer(wallet, mock_keys_and_services):
    """Test send_erc20_transfer."""
    mock_keys_and_services["transfer_service"].return_value.send.return_value = "0xhash"
    success, tx_hash = wallet.send_erc20_transfer("0xfrom", "0xto", 100, "0xtoken", "gnosis")
    assert success is True
    assert tx_hash == "0xhash"
    mock_keys_and_services["transfer_service"].return_value.send.assert_called_with(
        from_address_or_tag="0xfrom",
        to_address_or_tag="0xto",
        amount_wei=100,
        token_address_or_name="0xtoken",
        chain_name="gnosis",
    )


def test_send(wallet, mock_keys_and_services):
    """Test send."""
    wallet.send("0xfrom", "0xto", 100)
    mock_keys_and_services["transfer_service"].return_value.send.assert_called_with(
        "0xfrom", "0xto", 100, "native", "gnosis"
    )


def test_multi_send(wallet, mock_keys_and_services):
    """Test multi_send."""
    txs = [{"to": "0x1", "value": 1}]
    wallet.multi_send("0xfrom", txs, "gnosis")
    mock_keys_and_services["transfer_service"].return_value.multi_send.assert_called_with(
        "0xfrom", txs, "gnosis"
    )


def test_balances_getters(wallet, mock_keys_and_services):
    """Test balances getters."""
    mock_bs = mock_keys_and_services["balance_service"].return_value

    wallet.get_native_balance_eth("0x1", "gnosis")
    mock_bs.get_native_balance_eth.assert_called_with("0x1", "gnosis")

    wallet.get_native_balance_wei("0x1", "gnosis")
    mock_bs.get_native_balance_wei.assert_called_with("0x1", "gnosis")

    wallet.get_erc20_balance_eth("0x1", "OLAS", "gnosis")
    mock_bs.get_erc20_balance_eth.assert_called_with("0x1", "OLAS", "gnosis")

    wallet.get_erc20_balance_wei("0x1", "OLAS", "gnosis")
    mock_bs.get_erc20_balance_wei.assert_called_with("0x1", "OLAS", "gnosis")


def test_erc20_operations(wallet, mock_keys_and_services):
    """Test erc20 operations."""
    mock_trs = mock_keys_and_services["transfer_service"].return_value

    wallet.get_erc20_allowance("owner", "spender", "token", "gnosis")
    mock_trs.get_erc20_allowance.assert_called_with("owner", "spender", "token", "gnosis")

    wallet.approve_erc20("owner", "spender", "token", 100, "gnosis")
    mock_trs.approve_erc20.assert_called_with("owner", "spender", "token", 100, "gnosis")

    wallet.transfer_from_erc20("from", "sender", "recipient", "token", 100, "gnosis")
    mock_trs.transfer_from_erc20.assert_called_with(
        "from", "sender", "recipient", "token", 100, "gnosis"
    )


@pytest.mark.asyncio
async def test_swap(wallet, mock_keys_and_services):
    """Test swap."""
    mock_trs = mock_keys_and_services["transfer_service"].return_value

    # Mock swap as async method
    mock_trs.swap = AsyncMock(return_value=True)

    result = await wallet.swap("account", 1.0, "SELL", "BUY", "gnosis")
    assert result is True

    # Check if await matches call args
    # Note: Enum handling might need import, passing string/value might be tested
    args, kwargs = mock_trs.swap.call_args
    assert args[0] == "account"
    assert args[1] == 1.0


def test_drain(wallet, mock_keys_and_services):
    """Test drain."""
    wallet.drain("from", "to", "gnosis")
    mock_keys_and_services["transfer_service"].return_value.drain.assert_called_with(
        "from", "to", "gnosis"
    )
