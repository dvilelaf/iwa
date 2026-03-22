"""Tests for ERC20TransferMixin gaps: _send_erc20_via_safe receipt polling, _send_erc20_via_eoa failure."""

from unittest.mock import MagicMock, patch

import pytest

from iwa.core.services.transfer.erc20 import ERC20TransferMixin


class MockERC20Service(ERC20TransferMixin):
    """Minimal mock for testing ERC20TransferMixin methods."""

    def __init__(self):
        self.account_service = MagicMock()
        self.safe_service = MagicMock()
        self.transaction_service = MagicMock()
        self._calculate_gas_info = MagicMock(return_value=(1000, 0.001))
        self._get_token_price_info = MagicMock(return_value=(1.5, 15.0))


@pytest.fixture
def svc():
    return MockERC20Service()


# ---- _send_erc20_via_safe tests ----


class TestSendERC20ViaSafe:
    @patch("iwa.core.services.transfer.erc20.log_transaction")
    @patch("iwa.core.services.transfer.erc20.ChainInterfaces")
    def test_receipt_polling_success(self, mock_ci, mock_log, svc):
        """Successful receipt retrieval after safe execution."""
        svc.safe_service.execute_safe_transaction.return_value = "0xSafeTxHash"

        mock_interface = MagicMock()
        mock_receipt = {"gasUsed": 50000, "effectiveGasPrice": 20, "logs": []}
        mock_interface.web3.eth.get_transaction_receipt.return_value = mock_receipt
        mock_ci.return_value.get.return_value = mock_interface

        from_account = MagicMock()
        from_account.address = "0xFromAddr"
        erc20 = MagicMock()
        erc20.address = "0xTokenAddr"

        result = svc._send_erc20_via_safe(
            from_account=from_account,
            from_address_or_tag="from_tag",
            to_address="0xToAddr",
            amount_wei=1000,
            chain_name="gnosis",
            erc20=erc20,
            transaction={"data": "0x1234"},
            from_tag="from_tag",
            to_tag="to_tag",
            token_symbol="OLAS",
        )

        assert result == "0xSafeTxHash"
        mock_log.assert_called_once()
        call_kwargs = mock_log.call_args.kwargs
        assert call_kwargs["token"] == "OLAS"
        assert call_kwargs["tags"] == ["erc20-transfer", "safe-transaction"]

    @patch("iwa.core.services.transfer.erc20.log_transaction")
    @patch("iwa.core.services.transfer.erc20.ChainInterfaces")
    def test_receipt_polling_failure_still_logs(self, mock_ci, mock_log, svc):
        """When receipt can't be retrieved, transaction is still logged."""
        svc.safe_service.execute_safe_transaction.return_value = "0xSafeTxHash"

        mock_interface = MagicMock()
        mock_interface.web3.eth.get_transaction_receipt.side_effect = Exception("RPC error")
        mock_ci.return_value.get.return_value = mock_interface

        from_account = MagicMock()
        from_account.address = "0xFromAddr"
        erc20 = MagicMock()
        erc20.address = "0xTokenAddr"

        result = svc._send_erc20_via_safe(
            from_account=from_account,
            from_address_or_tag="from_tag",
            to_address="0xToAddr",
            amount_wei=1000,
            chain_name="gnosis",
            erc20=erc20,
            transaction={"data": "0x1234"},
            from_tag="from_tag",
            to_tag="to_tag",
            token_symbol="OLAS",
        )

        assert result == "0xSafeTxHash"
        # Still logs even without receipt
        mock_log.assert_called_once()


# ---- _send_erc20_via_eoa tests ----


class TestSendERC20ViaEOA:
    @patch("iwa.core.services.transfer.erc20.log_transaction")
    def test_success_returns_tx_hash(self, mock_log, svc):
        """Successful EOA transfer returns tx hash and logs."""
        mock_receipt = MagicMock()
        mock_receipt.__getitem__ = lambda self, key: b"\xab" * 32 if key == "transactionHash" else None
        mock_receipt.get = lambda key, default=None: b"\xab" * 32 if key == "transactionHash" else default
        svc.transaction_service.sign_and_send.return_value = (True, mock_receipt)

        from_account = MagicMock()
        from_account.address = "0xFromAddr"

        result = svc._send_erc20_via_eoa(
            from_account=from_account,
            from_address_or_tag="from_tag",
            to_address="0xToAddr",
            amount_wei=1000,
            chain_name="gnosis",
            transaction={"data": "0x1234"},
            from_tag="from_tag",
            to_tag="to_tag",
            token_symbol="OLAS",
        )

        assert result == "ab" * 32
        mock_log.assert_called_once()
        call_kwargs = mock_log.call_args.kwargs
        assert call_kwargs["token"] == "OLAS"
        assert call_kwargs["amount_wei"] == 1000
        assert call_kwargs["tags"] == ["erc20-transfer"]

    @patch("iwa.core.services.transfer.erc20.log_transaction")
    def test_failure_returns_none(self, mock_log, svc):
        """Failed EOA transfer returns None and does not log."""
        svc.transaction_service.sign_and_send.return_value = (False, {})

        from_account = MagicMock()
        from_account.address = "0xFromAddr"

        result = svc._send_erc20_via_eoa(
            from_account=from_account,
            from_address_or_tag="from_tag",
            to_address="0xToAddr",
            amount_wei=1000,
            chain_name="gnosis",
            transaction={"data": "0x1234"},
            from_tag="from_tag",
            to_tag="to_tag",
            token_symbol="OLAS",
        )

        assert result is None
        mock_log.assert_not_called()


# ---- _resolve_label tests ----


class TestResolveLabel:
    @patch("iwa.core.services.transfer.erc20.ChainInterfaces")
    def test_resolve_label_with_tag(self, mock_ci, svc):
        """Resolve returns tag if known."""
        svc.account_service.get_tag_by_address.return_value = "master"
        assert svc._resolve_label("0xAddr") == "master"

    @patch("iwa.core.services.transfer.erc20.ChainInterfaces")
    def test_resolve_label_with_token_name(self, mock_ci, svc):
        """Resolve returns token name if address is a known token."""
        svc.account_service.get_tag_by_address.return_value = None
        mock_ci.return_value.get.return_value.chain.get_token_name.return_value = "OLAS"
        assert svc._resolve_label("0xAddr") == "OLAS"

    @patch("iwa.core.services.transfer.erc20.ChainInterfaces")
    def test_resolve_label_fallback_to_address(self, mock_ci, svc):
        """Resolve returns address if nothing matches."""
        svc.account_service.get_tag_by_address.return_value = None
        mock_ci.return_value.get.return_value.chain.get_token_name.return_value = None
        assert svc._resolve_label("0xAddr") == "0xAddr"

    def test_resolve_label_empty_address(self, svc):
        """Resolve returns 'None' for empty address."""
        assert svc._resolve_label("") == "None"
