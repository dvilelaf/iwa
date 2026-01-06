"""Tests for TransactionService."""

from unittest.mock import MagicMock, patch

import pytest
from web3 import exceptions as web3_exceptions

from iwa.core.keys import EncryptedAccount, KeyStorage
from iwa.core.services.transaction import TransactionService


@pytest.fixture
def mock_key_storage():
    """Mock key storage."""
    mock = MagicMock(spec=KeyStorage)

    # Mock sign_transaction
    mock_signed_tx = MagicMock()
    mock_signed_tx.raw_transaction = b"raw_tx_bytes"
    mock.sign_transaction.return_value = mock_signed_tx

    return mock


@pytest.fixture
def mock_account_service():
    """Mock account service."""
    mock = MagicMock()

    mock_account = MagicMock(spec=EncryptedAccount)
    mock_account.address = "0xSigner"
    mock_account.tag = "signer_tag"

    mock.resolve_account.return_value = mock_account
    return mock


@pytest.fixture
def mock_chain_interfaces():
    """Mock chain interfaces."""
    with patch("iwa.core.services.transaction.ChainInterfaces") as mock:
        instance = mock.return_value
        gnosis_interface = MagicMock()
        gnosis_interface.chain.chain_id = 100

        # Web3 mocks
        gnosis_interface.web3.eth.get_transaction_count.return_value = 5
        gnosis_interface.web3.eth.send_raw_transaction.return_value = b"tx_hash_bytes"

        # Receipt valid
        mock_receipt = MagicMock()
        mock_receipt.status = 1
        mock_receipt.gasUsed = 21000
        mock_receipt.effectiveGasPrice = 10
        gnosis_interface.web3.eth.wait_for_transaction_receipt.return_value = mock_receipt

        instance.get.return_value = gnosis_interface
        yield instance


@pytest.fixture
def mock_external_deps():
    """Mock logger, db, pricing."""
    with (
        patch("iwa.core.services.transaction.log_transaction") as mock_log,
        patch("iwa.core.pricing.PriceService") as mock_price,
        patch("iwa.core.services.transaction.time.sleep") as _,  # speed up tests
    ):
        mock_price.return_value.get_token_price.return_value = 1.0  # 1 EUR per Token
        yield {
            "log": mock_log,
            "price": mock_price,
        }


def test_sign_and_send_success(
    mock_key_storage, mock_account_service, mock_chain_interfaces, mock_external_deps
):
    """Test successful sign and send flow."""
    service = TransactionService(mock_key_storage, mock_account_service)

    tx = {"to": "0xDest", "value": 100}

    success, receipt = service.sign_and_send(tx, "signer")

    assert success is True
    assert receipt.status == 1

    # Check flow
    mock_account_service.resolve_account.assert_called_with("signer")
    mock_chain_interfaces.get.assert_called_with("gnosis")

    # Check nonce filling
    mock_chain_interfaces.get.return_value.web3.eth.get_transaction_count.assert_called()

    # Check signing
    mock_key_storage.sign_transaction.assert_called()

    # Check sending
    mock_chain_interfaces.get.return_value.web3.eth.send_raw_transaction.assert_called_with(
        b"raw_tx_bytes"
    )

    # Check logging
    mock_external_deps["log"].assert_called_once()
    call_args = mock_external_deps["log"].call_args[1]
    assert call_args["tx_hash"] == "74785f686173685f6279746573"  # hex of b'tx_hash_bytes'
    assert call_args["tags"] is None


def test_sign_and_send_low_gas_retry(
    mock_key_storage, mock_account_service, mock_chain_interfaces, mock_external_deps
):
    """Test retry logic on low gas error."""
    service = TransactionService(mock_key_storage, mock_account_service)

    web3_mock = mock_chain_interfaces.get.return_value.web3.eth

    # First attempt fails with "intrinsic gas too low", second succeeds
    web3_mock.send_raw_transaction.side_effect = [
        web3_exceptions.Web3RPCError("intrinsic gas too low"),
        b"tx_hash_bytes_success",
    ]

    tx = {"to": "0xDest", "value": 100, "gas": 20000}

    success, receipt = service.sign_and_send(tx, "signer")

    assert success is True

    # Check retries
    assert web3_mock.send_raw_transaction.call_count == 2

    # Verify gas increase
    # Since 'tx' is mutated in place, both mock calls point to the same dict object which now has 30000
    # We can verify that sign_transaction was called twice, and the final gas is 30000
    assert mock_key_storage.sign_transaction.call_count == 2
    final_tx_arg = mock_key_storage.sign_transaction.call_args[0][0]
    assert final_tx_arg["gas"] == 30000


def test_sign_and_send_rpc_rotation(
    mock_key_storage, mock_account_service, mock_chain_interfaces, mock_external_deps
):
    """Test RPC rotation on generic error."""
    service = TransactionService(mock_key_storage, mock_account_service)
    chain_interface = mock_chain_interfaces.get.return_value

    # Side effect: 1. Exception, 2. Success
    chain_interface.web3.eth.send_raw_transaction.side_effect = [
        Exception("Connection reset"),
        b"tx_hash_bytes",
    ]
    chain_interface.rotate_rpc.return_value = True

    tx = {"to": "0xDest", "value": 100}

    success, receipt = service.sign_and_send(tx, "signer")

    assert success is True
    chain_interface.rotate_rpc.assert_called_once()
