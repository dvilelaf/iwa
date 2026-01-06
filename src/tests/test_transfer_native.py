"""Tests for NativeTransferMixin (wrap/unwrap)."""

from unittest.mock import MagicMock, patch

import pytest

from iwa.core.services.transfer import TransferService


@pytest.fixture
def mock_deps():
    """Mock dependencies for TransferService."""
    with (
        patch("iwa.core.services.transfer.base.ChainInterfaces") as mock_chain,
        patch("iwa.core.services.transfer.native.ChainInterfaces", new=mock_chain),
    ):
        mock_account_service = MagicMock()
        mock_key_storage = MagicMock()
        mock_balance_service = MagicMock()
        mock_safe_service = MagicMock()
        mock_txn_service = MagicMock()

        # Setup Chain Interface
        mock_w3 = MagicMock()
        # Mock eth.contract
        mock_contract = MagicMock()
        mock_w3._web3.eth.contract.return_value = mock_contract
        mock_w3._web3.eth.gas_price = 1000000000
        mock_w3._web3.eth.get_transaction_count.return_value = 5

        # Mock chain info
        mock_chain_instance = mock_chain.return_value.get.return_value
        mock_chain_instance.web3 = mock_w3
        mock_chain_instance.chain.tokens = {"WXDAI": "0xe91D153E0b41518A2Ce8Dd3D7944Fa863463a97d"}

        deps = {
            "account_service": mock_account_service,
            "key_storage": mock_key_storage,
            "balance_service": mock_balance_service,
            "safe_service": mock_safe_service,
            "transaction_service": mock_txn_service,
            "chain_interface": mock_chain_instance,
            "contract": mock_contract,
        }
        yield deps


def test_wrap_native_success(mock_deps):
    """Test successful wrap of native currency."""
    service = TransferService(
        mock_deps["account_service"],
        mock_deps["key_storage"],
        mock_deps["balance_service"],
        mock_deps["safe_service"],
        mock_deps["transaction_service"],
    )

    # Mock Account
    mock_account = MagicMock(name="mock_account")
    mock_account.address = "0xUser"
    service.account_service.resolve_account.return_value = mock_account

    # Mock Contract Function build_transaction
    mock_function = mock_deps["contract"].functions.deposit.return_value
    mock_function.build_transaction.return_value = {
        "to": "0xWXDAI",
        "value": 1000,
        "data": "0x",
    }

    # Mock Sign and Send
    mock_signed_tx = MagicMock()
    mock_signed_tx.raw_transaction = b"signed_tx"
    service.key_storage.sign_transaction.return_value = mock_signed_tx
    mock_deps["chain_interface"].web3._web3.eth.send_raw_transaction.return_value = b"tx_hash"

    # Mock Receipt
    mock_receipt = MagicMock()
    mock_receipt.status = 1
    mock_deps[
        "chain_interface"
    ].web3._web3.eth.wait_for_transaction_receipt.return_value = mock_receipt

    result = service.wrap_native("user", 1000)

    assert result == "74785f68617368"  # "tx_hash".hex()
    mock_deps["contract"].functions.deposit.assert_called()
    service.key_storage.sign_transaction.assert_called()


def test_wrap_native_account_not_found(mock_deps):
    """Test wrap fails when account not found."""
    service = TransferService(
        mock_deps["account_service"],
        mock_deps["key_storage"],
        mock_deps["balance_service"],
        mock_deps["safe_service"],
        mock_deps["transaction_service"],
    )
    service.account_service.resolve_account.return_value = None

    result = service.wrap_native("invalid", 1000)
    assert result is None


def test_wrap_native_token_not_found(mock_deps):
    """Test wrap fails when WXDAI token not configured."""
    service = TransferService(
        mock_deps["account_service"],
        mock_deps["key_storage"],
        mock_deps["balance_service"],
        mock_deps["safe_service"],
        mock_deps["transaction_service"],
    )
    service.account_service.resolve_account.return_value = MagicMock()
    mock_deps["chain_interface"].chain.tokens = {}  # Empty tokens

    result = service.wrap_native("user", 1000)
    assert result is None


def test_unwrap_native_success(mock_deps):
    """Test successful unwrap of wrapped token."""
    service = TransferService(
        mock_deps["account_service"],
        mock_deps["key_storage"],
        mock_deps["balance_service"],
        mock_deps["safe_service"],
        mock_deps["transaction_service"],
    )

    # Mock Account
    mock_account = MagicMock(name="mock_account")
    mock_account.address = "0xUser"
    service.account_service.resolve_account.return_value = mock_account

    # Mock Contract Function build_transaction
    mock_function = mock_deps["contract"].functions.withdraw.return_value
    mock_function.build_transaction.return_value = {
        "to": "0xWXDAI",
        "data": "0x",
    }

    # Mock Sign and Send
    mock_signed_tx = MagicMock()
    mock_signed_tx.raw_transaction = b"signed_tx"
    service.key_storage.sign_transaction.return_value = mock_signed_tx
    mock_deps["chain_interface"].web3._web3.eth.send_raw_transaction.return_value = b"tx_hash"

    # Mock Receipt
    mock_receipt = MagicMock()
    mock_receipt.status = 1
    mock_deps[
        "chain_interface"
    ].web3._web3.eth.wait_for_transaction_receipt.return_value = mock_receipt

    result = service.unwrap_native("user", 1000)

    assert result == "74785f68617368"
    mock_deps["contract"].functions.withdraw.assert_called_with(1000)


def test_unwrap_native_auto_balance(mock_deps):
    """Test unwrap with auto-balance detection."""
    service = TransferService(
        mock_deps["account_service"],
        mock_deps["key_storage"],
        mock_deps["balance_service"],
        mock_deps["safe_service"],
        mock_deps["transaction_service"],
    )

    mock_account = MagicMock(name="mock_account")
    mock_account.address = "0xUser"
    service.account_service.resolve_account.return_value = mock_account

    # Mock Balance
    mock_deps["balance_service"].get_erc20_balance_wei.return_value = 500

    # Mock Contract Function
    mock_function = mock_deps["contract"].functions.withdraw.return_value
    mock_function.build_transaction.return_value = {}

    # Mock Sign/Send/Receipt
    mock_signed_tx = MagicMock()
    mock_signed_tx.raw_transaction = b"signed_tx"
    service.key_storage.sign_transaction.return_value = mock_signed_tx
    mock_deps["chain_interface"].web3._web3.eth.send_raw_transaction.return_value = b"tx_hash"
    mock_receipt = MagicMock()
    mock_receipt.status = 1
    mock_deps[
        "chain_interface"
    ].web3._web3.eth.wait_for_transaction_receipt.return_value = mock_receipt

    # Call without amount
    result = service.unwrap_native("user")

    assert result == "74785f68617368"
    mock_deps["balance_service"].get_erc20_balance_wei.assert_called_with(
        "0xUser", "WXDAI", "gnosis"
    )
    mock_deps["contract"].functions.withdraw.assert_called_with(500)


def test_unwrap_native_no_balance(mock_deps):
    """Test unwrap fails when no balance available."""
    service = TransferService(
        mock_deps["account_service"],
        mock_deps["key_storage"],
        mock_deps["balance_service"],
        mock_deps["safe_service"],
        mock_deps["transaction_service"],
    )

    mock_account = MagicMock()
    service.account_service.resolve_account.return_value = mock_account
    mock_deps["balance_service"].get_erc20_balance_wei.return_value = 0

    result = service.unwrap_native("user")
    assert result is None
