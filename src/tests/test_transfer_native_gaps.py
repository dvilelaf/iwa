"""Tests for NativeTransferMixin gaps: _send_native_via_safe receipt, _send_native_via_eoa failure."""

from unittest.mock import MagicMock, patch

import pytest

from iwa.core.services.transfer.native import NativeTransferMixin


class MockNativeService(NativeTransferMixin):
    """Minimal mock for testing NativeTransferMixin methods."""

    def __init__(self):
        self.account_service = MagicMock()
        self.safe_service = MagicMock()
        self.transaction_service = MagicMock()
        self._calculate_gas_info = MagicMock(return_value=(1000, 0.001))
        self._get_token_price_info = MagicMock(return_value=(1.5, 15.0))


@pytest.fixture
def svc():
    return MockNativeService()


# ---- _send_native_via_safe tests ----


class TestSendNativeViaSafe:
    @patch("iwa.core.services.transfer.native.log_transaction")
    @patch("iwa.core.services.transfer.native.ChainInterfaces")
    def test_receipt_retrieval_success(self, mock_ci, mock_log, svc):
        """Successful receipt retrieval and gas logging."""
        svc.safe_service.execute_safe_transaction.return_value = "0xSafeTxHash"

        mock_interface = MagicMock()
        mock_receipt = {"gasUsed": 50000, "effectiveGasPrice": 20, "logs": []}
        mock_interface.web3.eth.get_transaction_receipt.return_value = mock_receipt
        mock_ci.return_value.get.return_value = mock_interface

        from_account = MagicMock()
        from_account.address = "0xFromAddr"

        result = svc._send_native_via_safe(
            from_account=from_account,
            from_address_or_tag="from_tag",
            to_address="0xToAddr",
            amount_wei=1000,
            chain_name="gnosis",
            from_tag="from_tag",
            to_tag="to_tag",
            token_symbol="xDAI",
        )

        assert result == "0xSafeTxHash"
        mock_log.assert_called_once()
        call_kwargs = mock_log.call_args.kwargs
        assert "native-transfer" in call_kwargs["tags"]
        assert "safe-transaction" in call_kwargs["tags"]

    @patch("iwa.core.services.transfer.native.log_transaction")
    @patch("iwa.core.services.transfer.native.ChainInterfaces")
    def test_receipt_retrieval_failure_still_logs(self, mock_ci, mock_log, svc):
        """When receipt fails, the transaction is still logged with None gas info."""
        svc.safe_service.execute_safe_transaction.return_value = "0xSafeTxHash"

        mock_interface = MagicMock()
        mock_interface.web3.eth.get_transaction_receipt.side_effect = Exception("RPC error")
        mock_ci.return_value.get.return_value = mock_interface

        from_account = MagicMock()
        from_account.address = "0xFromAddr"

        result = svc._send_native_via_safe(
            from_account=from_account,
            from_address_or_tag="from_tag",
            to_address="0xToAddr",
            amount_wei=1000,
            chain_name="gnosis",
            from_tag="from_tag",
            to_tag=None,
            token_symbol="xDAI",
        )

        assert result == "0xSafeTxHash"
        mock_log.assert_called_once()


# ---- _send_native_via_eoa tests ----


class TestSendNativeViaEOA:
    @patch("iwa.core.services.transfer.native.log_transaction")
    def test_success_returns_tx_hash(self, mock_log, svc):
        """Successful EOA native transfer returns tx hash."""
        mock_receipt = {
            "transactionHash": b"\xab" * 32,
            "gasUsed": 21000,
            "effectiveGasPrice": 10,
            "logs": [],
        }
        svc.transaction_service.sign_and_send.return_value = (True, mock_receipt)

        from_account = MagicMock()
        from_account.address = "0xFromAddr"
        chain_interface = MagicMock()
        chain_interface.calculate_transaction_params.return_value = {
            "from": "0xFromAddr",
            "to": "0xToAddr",
            "value": 1000,
        }

        result = svc._send_native_via_eoa(
            from_account=from_account,
            to_address="0xToAddr",
            amount_wei=1000,
            chain_name="gnosis",
            chain_interface=chain_interface,
            from_tag="from_tag",
            to_tag="to_tag",
            token_symbol="xDAI",
        )

        assert result is not None
        mock_log.assert_called_once()

    @patch("iwa.core.services.transfer.native.log_transaction")
    def test_failure_returns_none(self, mock_log, svc):
        """Failed EOA native transfer returns None."""
        svc.transaction_service.sign_and_send.return_value = (False, {})

        from_account = MagicMock()
        from_account.address = "0xFromAddr"
        chain_interface = MagicMock()
        chain_interface.calculate_transaction_params.return_value = {
            "from": "0xFromAddr",
            "to": "0xToAddr",
            "value": 1000,
        }

        result = svc._send_native_via_eoa(
            from_account=from_account,
            to_address="0xToAddr",
            amount_wei=1000,
            chain_name="gnosis",
            chain_interface=chain_interface,
            from_tag="from_tag",
            to_tag="to_tag",
            token_symbol="xDAI",
        )

        assert result is None
        mock_log.assert_not_called()

    @patch("iwa.core.services.transfer.native.log_transaction")
    def test_tx_hash_bytes_hex_conversion(self, mock_log, svc):
        """Tx hash in various formats is properly converted."""
        # Test with bytes that have .hex() method
        mock_tx_hash = MagicMock()
        mock_tx_hash.hex.return_value = "aabbcc"
        mock_receipt = {
            "transactionHash": mock_tx_hash,
            "gasUsed": 21000,
            "effectiveGasPrice": 10,
            "logs": [],
        }
        svc.transaction_service.sign_and_send.return_value = (True, mock_receipt)

        from_account = MagicMock()
        from_account.address = "0xFromAddr"
        chain_interface = MagicMock()
        chain_interface.calculate_transaction_params.return_value = {
            "from": "0xFromAddr",
            "to": "0xToAddr",
            "value": 1000,
        }

        result = svc._send_native_via_eoa(
            from_account=from_account,
            to_address="0xToAddr",
            amount_wei=1000,
            chain_name="gnosis",
            chain_interface=chain_interface,
            from_tag=None,
            to_tag=None,
            token_symbol="xDAI",
        )

        assert result == "aabbcc"
