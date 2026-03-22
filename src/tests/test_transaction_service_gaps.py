"""Tests for TransactionService gaps: sign_and_send edge cases, TransferLogger log_transfers."""

from unittest.mock import MagicMock, patch

import pytest

from iwa.core.keys import KeyStorage
from iwa.core.models import StoredSafeAccount
from iwa.core.services.transaction import TransactionService, TransferLogger


@pytest.fixture
def mock_key_storage():
    mock = MagicMock(spec=KeyStorage)
    mock_signed = MagicMock()
    mock_signed.raw_transaction = b"raw_tx"
    mock.sign_transaction.return_value = mock_signed
    return mock


@pytest.fixture
def mock_account_service():
    mock = MagicMock()
    account = MagicMock()
    account.address = "0xSigner"
    account.tag = "signer_tag"
    # Not a safe by default
    account.threshold = None
    mock.resolve_account.return_value = account
    mock.get_tag_by_address.return_value = None
    return mock


@pytest.fixture
def mock_chain_interfaces():
    with patch("iwa.core.services.transaction.ChainInterfaces") as mock:
        instance = mock.return_value
        gnosis = MagicMock()
        gnosis.chain.chain_id = 100
        gnosis.chain.native_currency = "xDAI"
        gnosis.web3.eth.get_transaction_count.return_value = 5
        gnosis.web3.eth.send_raw_transaction.return_value = b"tx_hash"

        receipt = MagicMock()
        receipt.status = 1
        receipt.gasUsed = 21000
        receipt.effectiveGasPrice = 10
        receipt.logs = []
        gnosis.web3.eth.wait_for_transaction_receipt.return_value = receipt

        def mock_with_retry(op, max_retries=6, **kwargs):
            last_error = None
            for attempt in range(max_retries + 1):
                try:
                    return op()
                except Exception as e:
                    last_error = e
                    if attempt >= max_retries:
                        raise
            raise last_error

        gnosis.with_retry.side_effect = mock_with_retry
        instance.get.return_value = gnosis
        yield instance


@pytest.fixture
def mock_external_deps():
    with (
        patch("iwa.core.services.transaction.log_transaction") as mock_log,
        patch("iwa.core.pricing.PriceService") as mock_price,
    ):
        mock_price.return_value.get_token_price.return_value = 1.0
        yield {"log": mock_log, "price": mock_price}


# ---- sign_and_send: signer not found ----


class TestSignAndSendEdgeCases:
    def test_signer_not_found(self, mock_key_storage, mock_account_service, mock_chain_interfaces):
        """Returns (False, {}) when signer cannot be resolved."""
        mock_account_service.resolve_account.return_value = None
        service = TransactionService(mock_key_storage, mock_account_service)
        success, receipt = service.sign_and_send({"to": "0xDest"}, "unknown")
        assert success is False
        assert receipt == {}

    def test_safe_transaction_without_safe_service(
        self, mock_key_storage, mock_account_service, mock_chain_interfaces, mock_external_deps
    ):
        """Safe transaction fails when SafeService is not initialized."""
        safe_account = MagicMock(spec=StoredSafeAccount)
        safe_account.address = "0xSafe"
        safe_account.tag = "my_safe"
        mock_account_service.resolve_account.return_value = safe_account

        service = TransactionService(mock_key_storage, mock_account_service, safe_service=None)
        success, receipt = service.sign_and_send({"to": "0xDest"}, "my_safe")
        assert success is False

    def test_tags_appended_for_approve(
        self, mock_key_storage, mock_account_service, mock_chain_interfaces, mock_external_deps
    ):
        """Approve transactions get the 'approve' tag."""
        service = TransactionService(mock_key_storage, mock_account_service)
        # approve function selector
        tx = {"to": "0xDest", "data": "0x095ea7b3" + "0" * 128}
        success, receipt = service.sign_and_send(tx, "signer", tags=["custom"])
        assert success is True
        call_kwargs = mock_external_deps["log"].call_args.kwargs
        assert "approve" in call_kwargs["tags"]
        assert "custom" in call_kwargs["tags"]

    def test_transaction_reverted_returns_false(
        self, mock_key_storage, mock_account_service, mock_chain_interfaces, mock_external_deps
    ):
        """Transaction that mines but reverts (status=0) returns False."""
        chain_interface = mock_chain_interfaces.get.return_value
        bad_receipt = MagicMock()
        bad_receipt.status = 0
        chain_interface.web3.eth.wait_for_transaction_receipt.return_value = bad_receipt

        service = TransactionService(mock_key_storage, mock_account_service)
        success, receipt = service.sign_and_send({"to": "0xDest"}, "signer")
        assert success is False


# ---- _is_gas_too_low_error ----


class TestGasErrorDetection:
    def test_feetoolow(self, mock_key_storage, mock_account_service):
        service = TransactionService(mock_key_storage, mock_account_service)
        assert service._is_gas_too_low_error("FeeTooLow: increase gas")

    def test_intrinsic_gas(self, mock_key_storage, mock_account_service):
        service = TransactionService(mock_key_storage, mock_account_service)
        assert service._is_gas_too_low_error("intrinsic gas too low")

    def test_underpriced(self, mock_key_storage, mock_account_service):
        service = TransactionService(mock_key_storage, mock_account_service)
        assert service._is_gas_too_low_error("replacement transaction underpriced")

    def test_unrelated_error(self, mock_key_storage, mock_account_service):
        service = TransactionService(mock_key_storage, mock_account_service)
        assert not service._is_gas_too_low_error("some random error")

    def test_none_error(self, mock_key_storage, mock_account_service):
        service = TransactionService(mock_key_storage, mock_account_service)
        assert not service._is_gas_too_low_error(None)


# ---- TransferLogger.log_transfers ----


class TestTransferLoggerLogTransfers:
    @patch("iwa.core.services.transaction.log_transaction")
    def test_log_transfers_with_native_value(self, mock_log_tx):
        """log_transfers logs native value from transaction."""
        account_service = MagicMock()
        account_service.get_tag_by_address.return_value = None
        chain_interface = MagicMock()
        chain_interface.chain.native_currency = "xDAI"
        chain_interface.chain.get_token_name.return_value = None

        # Mock tx as a non-dict with explicit "from" attribute.
        # "from" is a Python keyword so we must use configure_mock.
        tx_obj = MagicMock()
        tx_obj.value = 10**18
        tx_obj.to = "0xTo"
        tx_obj.configure_mock(**{"from": "0xFrom"})
        chain_interface.web3.eth.get_transaction.return_value = tx_obj

        receipt = {
            "transactionHash": b"\xab" * 32,
            "logs": [],
        }

        logger = TransferLogger(account_service, chain_interface)
        logger.log_transfers(receipt)

        # Verify _log_native_transfer was reached: it logs via
        # logger.info so we check the transaction was fetched
        chain_interface.web3.eth.get_transaction.assert_called_once()

    def test_log_transfers_with_erc20_events(self):
        """log_transfers processes ERC20 Transfer events from logs."""
        from iwa.core.services.transaction import TRANSFER_EVENT_TOPIC

        account_service = MagicMock()
        account_service.get_tag_by_address.return_value = None
        chain_interface = MagicMock()
        chain_interface.chain.native_currency = "xDAI"
        chain_interface.chain.get_token_name.return_value = None
        chain_interface.get_token_decimals.return_value = 18
        chain_interface.web3.eth.get_transaction.side_effect = (
            Exception("skip")
        )

        from_topic = "0x" + "0" * 24 + "aa" * 20
        to_topic = "0x" + "0" * 24 + "bb" * 20
        data = (10**18).to_bytes(32, "big")

        receipt = {
            "transactionHash": b"\xab" * 32,
            "logs": [{
                "topics": [
                    TRANSFER_EVENT_TOPIC, from_topic, to_topic,
                ],
                "data": data,
                "address": "0xTokenContract",
            }],
        }

        transfer_logger = TransferLogger(
            account_service, chain_interface,
        )
        transfer_logger.log_transfers(receipt)

        # Verify the ERC20 Transfer event was processed:
        # _log_erc20_transfer calls get_token_decimals
        chain_interface.get_token_decimals.assert_called_once_with(
            "0xTokenContract", fallback_to_18=False,
        )

    def test_log_transfers_no_tx_hash(self):
        """log_transfers skips native transfer when no transactionHash."""
        account_service = MagicMock()
        chain_interface = MagicMock()
        chain_interface.chain.native_currency = "xDAI"

        receipt = {"logs": []}

        transfer_logger = TransferLogger(
            account_service, chain_interface,
        )
        transfer_logger.log_transfers(receipt)

        # Without tx hash, get_transaction should NOT be called
        chain_interface.web3.eth.get_transaction.assert_not_called()
