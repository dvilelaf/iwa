
from unittest.mock import MagicMock, patch

import pytest

from iwa.core.chain import Gnosis
from iwa.core.services.transaction import TransactionService


@pytest.fixture
def mock_chain_interfaces():
    with patch("iwa.core.services.transaction.ChainInterfaces") as mock:
        instance = mock.return_value
        gnosis_interface = MagicMock()
        mock_chain = MagicMock(spec=Gnosis)
        mock_chain.name = "Gnosis"
        mock_chain.chain_id = 100
        gnosis_interface.chain = mock_chain
        gnosis_interface.web3 = MagicMock()
        instance.get.return_value = gnosis_interface
        yield instance

@pytest.fixture
def mock_key_storage():
    return MagicMock()

@pytest.fixture
def mock_account_service():
    return MagicMock()

@pytest.fixture
def transaction_service(mock_key_storage, mock_account_service):
    return TransactionService(mock_key_storage, mock_account_service)

def test_sign_and_send_success(transaction_service, mock_key_storage, mock_chain_interfaces, mock_account_service):
    # Setup
    tx = {"to": "0x123", "value": 100, "nonce": 5, "chainId": 100}
    mock_key_storage.sign_transaction.return_value = MagicMock(raw_transaction=b"raw_tx")

    chain_interface = mock_chain_interfaces.get.return_value
    chain_interface.web3.eth.send_raw_transaction.return_value = b"tx_hash"
    chain_interface.web3.eth.wait_for_transaction_receipt.return_value = MagicMock(status=1)

    mock_account_service.resolve_account.return_value = MagicMock(address="0xSigner")

    # Call
    success, receipt = transaction_service.sign_and_send(tx, "signer")

    # Assert
    assert success is True
    assert receipt.status == 1
    mock_key_storage.sign_transaction.assert_called_with(tx, "signer")
    chain_interface.web3.eth.send_raw_transaction.assert_called_with(b"raw_tx")
    chain_interface.wait_for_no_pending_tx.assert_called_with("0xSigner")

def test_sign_and_send_retry_on_low_gas(transaction_service, mock_key_storage, mock_chain_interfaces):
    # Setup
    tx = {"to": "0x123", "value": 100, "nonce": 5, "gas": 10000}
    mock_key_storage.sign_transaction.return_value = MagicMock(raw_transaction=b"raw_tx")

    chain_interface = mock_chain_interfaces.get.return_value

    # Simulate low gas error then success
    from web3 import exceptions
    chain_interface.web3.eth.send_raw_transaction.side_effect = [
        exceptions.Web3RPCError("intrinsic gas too low"),
        b"tx_hash"
    ]
    chain_interface.web3.eth.wait_for_transaction_receipt.return_value = MagicMock(status=1)

    # Call
    with patch("time.sleep"):
        success, receipt = transaction_service.sign_and_send(tx, "signer")

    # Assert
    assert success is True
    assert chain_interface.web3.eth.send_raw_transaction.call_count == 2
    # Verify gas increase
    # arguments passed to sign_transaction should reflect updated gas
    args, _ = mock_key_storage.sign_transaction.call_args_list[1]
    assert args[0]["gas"] == 15000 # 10000 * 1.5
