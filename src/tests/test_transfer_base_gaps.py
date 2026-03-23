"""Tests for TransferService.send() dispatching logic and base helpers."""

from unittest.mock import MagicMock, patch

import pytest

from iwa.core.services.transfer import TransferService


@pytest.fixture
def mock_deps():
    """Create mock dependencies for TransferService."""
    return {
        "key_storage": MagicMock(),
        "account_service": MagicMock(),
        "balance_service": MagicMock(),
        "safe_service": MagicMock(),
        "transaction_service": MagicMock(),
    }


@pytest.fixture
def transfer_service(mock_deps):
    """Create a TransferService with mocked dependencies."""
    return TransferService(
        key_storage=mock_deps["key_storage"],
        account_service=mock_deps["account_service"],
        balance_service=mock_deps["balance_service"],
        safe_service=mock_deps["safe_service"],
        transaction_service=mock_deps["transaction_service"],
    )


# ---- send() dispatching tests ----


class TestSendDispatching:
    @patch("iwa.core.services.transfer.ChainInterfaces")
    @patch("iwa.core.services.transfer.ERC20Contract")
    def test_send_returns_none_when_from_account_not_found(self, mock_erc20, mock_ci, transfer_service):
        """send() returns None when from account cannot be resolved."""
        transfer_service.account_service.resolve_account.return_value = None

        result = transfer_service.send("unknown", "0xTo", 1000)
        assert result is None

    @patch("iwa.core.services.transfer.ChainInterfaces")
    def test_send_returns_none_when_destination_invalid(self, mock_ci, transfer_service):
        """send() returns None when destination address is invalid."""
        from_account = MagicMock()
        from_account.address = "0xFromAddr"
        transfer_service.account_service.resolve_account.side_effect = lambda tag: (
            from_account if tag == "from_tag" else None
        )

        # _resolve_destination will try resolve_account then EthereumAddress
        with patch.object(transfer_service, "_resolve_destination", return_value=(None, None)):
            result = transfer_service.send("from_tag", "invalid_dest", 1000)
            assert result is None

    @patch("iwa.core.services.transfer.ChainInterfaces")
    def test_send_returns_none_when_not_whitelisted(self, mock_ci, transfer_service):
        """send() returns None when destination is not whitelisted."""
        from_account = MagicMock()
        from_account.address = "0xFromAddr"
        transfer_service.account_service.resolve_account.return_value = from_account

        with (
            patch.object(transfer_service, "_resolve_destination", return_value=("0xTo", None)),
            patch.object(transfer_service, "_is_whitelisted_destination", return_value=False),
        ):
            result = transfer_service.send("from_tag", "0xTo", 1000)
            assert result is None

    @patch("iwa.core.services.transfer.ChainInterfaces")
    def test_send_returns_none_when_token_not_supported(self, mock_ci, transfer_service):
        """send() returns None when token is not supported."""
        from_account = MagicMock()
        from_account.address = "0xFromAddr"
        transfer_service.account_service.resolve_account.return_value = from_account

        with (
            patch.object(transfer_service, "_resolve_destination", return_value=("0xTo", None)),
            patch.object(transfer_service, "_is_whitelisted_destination", return_value=True),
            patch.object(transfer_service, "_is_supported_token", return_value=False),
        ):
            result = transfer_service.send("from_tag", "0xTo", 1000, token_address_or_name="FAKE")
            assert result is None

    @patch("iwa.core.services.transfer.ERC20Contract")
    @patch("iwa.core.services.transfer.ChainInterfaces")
    def test_send_dispatches_native_via_eoa(self, mock_ci, mock_erc20, transfer_service):
        """send() dispatches to _send_native_via_eoa for native token on EOA."""
        from iwa.core.constants import NATIVE_CURRENCY_ADDRESS

        from_account = MagicMock()
        from_account.address = "0xFromAddr"
        from_account.threshold = None  # EOA, not Safe
        transfer_service.account_service.resolve_account.return_value = from_account
        transfer_service.account_service.get_token_address.return_value = NATIVE_CURRENCY_ADDRESS
        transfer_service.account_service.get_tag_by_address.return_value = "from_tag"

        mock_interface = MagicMock()
        mock_interface.chain.native_currency = "xDAI"
        mock_interface.web3.from_wei.return_value = 0.001
        mock_ci.return_value.get.return_value = mock_interface

        with (
            patch.object(transfer_service, "_resolve_destination", return_value=("0xTo", "to_tag")),
            patch.object(transfer_service, "_is_whitelisted_destination", return_value=True),
            patch.object(transfer_service, "_is_supported_token", return_value=True),
            patch.object(transfer_service, "_send_native_via_eoa", return_value="0xHash") as mock_send,
        ):
            result = transfer_service.send("from_tag", "0xTo", 1000, "native")
            assert result == "0xHash"
            mock_send.assert_called_once()

    @patch("iwa.core.services.transfer.ERC20Contract")
    @patch("iwa.core.services.transfer.ChainInterfaces")
    def test_send_dispatches_erc20_via_safe(self, mock_ci, mock_erc20, transfer_service):
        """send() dispatches to _send_erc20_via_safe for ERC20 on Safe account."""
        from_account = MagicMock()
        from_account.address = "0xFromAddr"
        from_account.threshold = 1  # Safe account
        transfer_service.account_service.resolve_account.return_value = from_account
        transfer_service.account_service.get_token_address.return_value = "0xTokenAddr"
        transfer_service.account_service.get_tag_by_address.return_value = "safe_tag"

        mock_interface = MagicMock()
        mock_interface.web3.from_wei.return_value = 0.001
        mock_ci.return_value.get.return_value = mock_interface

        mock_erc20_instance = MagicMock()
        mock_erc20_instance.prepare_transfer_tx.return_value = {"data": "0x1234"}
        mock_erc20.return_value = mock_erc20_instance

        with (
            patch.object(transfer_service, "_resolve_destination", return_value=("0xTo", "to_tag")),
            patch.object(transfer_service, "_is_whitelisted_destination", return_value=True),
            patch.object(transfer_service, "_is_supported_token", return_value=True),
            patch.object(transfer_service, "_send_erc20_via_safe", return_value="0xHash") as mock_send,
        ):
            result = transfer_service.send("safe_tag", "0xTo", 1000, "OLAS")
            assert result == "0xHash"
            mock_send.assert_called_once()


# ---- Base helper tests ----


class TestBaseHelpers:
    @patch("iwa.core.services.transfer.base.ChainInterfaces")
    @patch("iwa.core.services.transfer.base.PriceService")
    def test_calculate_gas_info_with_receipt(self, mock_price, mock_ci, transfer_service):
        """Gas info is calculated correctly from receipt."""
        mock_price.return_value.get_token_price.return_value = 1.0
        receipt = {"gasUsed": 21000, "effectiveGasPrice": 10**9}

        gas_cost, gas_value = transfer_service._calculate_gas_info(receipt, "gnosis")

        assert gas_cost == 21000 * 10**9
        assert gas_value is not None

    def test_calculate_gas_info_without_receipt(self, transfer_service):
        """Gas info returns None tuple when receipt is None."""
        gas_cost, gas_value = transfer_service._calculate_gas_info(None, "gnosis")
        assert gas_cost is None
        assert gas_value is None

    @patch("iwa.core.services.transfer.base.ChainInterfaces")
    @patch("iwa.core.services.transfer.base.PriceService")
    def test_get_token_price_info_known_token(self, mock_price, mock_ci, transfer_service):
        """Token price info returns price and value for known tokens."""
        mock_price.return_value.get_token_price.return_value = 2.0
        mock_interface = MagicMock()
        mock_interface.chain.get_token_address.return_value = None
        mock_ci.return_value.get.return_value = mock_interface

        price, value = transfer_service._get_token_price_info("OLAS", 10**18, "gnosis")

        assert price == 2.0
        assert value == 2.0  # 1 token * 2.0 EUR

    @patch("iwa.core.services.transfer.base.ChainInterfaces")
    @patch("iwa.core.services.transfer.base.PriceService")
    def test_get_token_price_info_unknown_token(self, mock_price, mock_ci, transfer_service):
        """Token price info returns None for unknown tokens."""
        price, value = transfer_service._get_token_price_info("UNKNOWN_TOKEN", 10**18, "gnosis")
        assert price is None
        assert value is None

    @patch("iwa.core.services.transfer.base.Config")
    def test_is_whitelisted_destination_own_account(self, mock_config, transfer_service):
        """Own accounts are whitelisted."""
        transfer_service.account_service.resolve_account.return_value = MagicMock()
        assert transfer_service._is_whitelisted_destination("0x1234567890123456789012345678901234567890")

    @patch("iwa.core.services.transfer.base.Config")
    def test_is_whitelisted_destination_blocked(self, mock_config, transfer_service):
        """Non-whitelisted address is blocked."""
        transfer_service.account_service.resolve_account.return_value = None
        mock_config.return_value.core = MagicMock()
        mock_config.return_value.core.whitelist = {}
        assert not transfer_service._is_whitelisted_destination("0x1234567890123456789012345678901234567890")

    @patch("iwa.core.services.transfer.base.ChainInterfaces")
    def test_resolve_token_symbol_native(self, mock_ci, transfer_service):
        """Resolves native currency symbol correctly."""
        from iwa.core.constants import NATIVE_CURRENCY_ADDRESS

        mock_interface = MagicMock()
        mock_interface.chain.native_currency = "xDAI"
        result = transfer_service._resolve_token_symbol(NATIVE_CURRENCY_ADDRESS, "native", mock_interface)
        assert result == "xDAI"

    @patch("iwa.core.services.transfer.base.ChainInterfaces")
    def test_resolve_token_symbol_by_name(self, mock_ci, transfer_service):
        """Non-address token name is returned as-is."""
        result = transfer_service._resolve_token_symbol("0xAddr", "OLAS", MagicMock())
        assert result == "OLAS"
