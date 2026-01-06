"""Security tests for TransferService."""

from unittest.mock import MagicMock, patch

import pytest
from eth_account import Account

from iwa.core.models import EthereumAddress
from iwa.core.services.transfer import TransferService


@pytest.fixture
def transfer_service():
    """Create a TransferService instance with mocked dependencies."""
    return TransferService(
        key_storage=MagicMock(),
        account_service=MagicMock(),
        balance_service=MagicMock(),
        safe_service=MagicMock(),
        transaction_service=MagicMock(),
    )


def test_is_whitelisted_destination_fail_closed(transfer_service):
    """Verify that destination whitelist fails closed (returns False) by default.

    This addresses TRANS-S1 (Whitelist Bypass).
    """
    # 1. Not an internal account
    transfer_service.account_service.resolve_account.return_value = None

    # 2. No config whitelist (simulating config.core is None or whitelist empty)
    with patch("iwa.core.services.transfer.base.Config") as mock_config_cls:
        mock_config = MagicMock()
        mock_config.core = None  # SIMULATE MISSING CONFIG
        mock_config_cls.return_value = mock_config

        # Should return False (Blocked)
        random_addr = Account.create().address
        assert transfer_service._is_whitelisted_destination(random_addr) is False


def test_is_whitelisted_destination_explicit_allow(transfer_service):
    """Verify that destination whitelist allows explicitly listed addresses."""
    # 1. Not an internal account
    transfer_service.account_service.resolve_account.return_value = None

    allowed_addr = Account.create().address

    # 2. In config whitelist
    with patch("iwa.core.services.transfer.base.Config") as mock_config_cls:
        mock_config = MagicMock()
        mock_config.core.whitelist.values.return_value = [EthereumAddress(allowed_addr)]
        mock_config_cls.return_value = mock_config

        # Should return True (Allowed)
        assert transfer_service._is_whitelisted_destination(allowed_addr) is True


def test_is_supported_token_strict_validation(transfer_service):
    """Verify that token validation is strict and rejects arbitrary addresses.

    This addresses TRANS-S2 (Explicit Token Whitelist).
    """
    chain_name = "Gnosis"
    valid_token_addr = Account.create().address
    invalid_token_addr = Account.create().address

    # Mock chain interface
    mock_chain_interface = MagicMock()
    mock_chain_interface.tokens = {"OLAS": EthereumAddress(valid_token_addr)}

    with patch("iwa.core.services.transfer.base.ChainInterfaces") as mock_ci_cls:
        mock_ci_cls.return_value.get.return_value = mock_chain_interface

        # 1. Native currency -> Allowed
        from iwa.core.constants import NATIVE_CURRENCY_ADDRESS

        assert transfer_service._is_supported_token(NATIVE_CURRENCY_ADDRESS, chain_name) is True
        assert transfer_service._is_supported_token("native", chain_name) is True

        # 2. Explicitly supported token (ByName) -> Allowed
        assert transfer_service._is_supported_token("OLAS", chain_name) is True

        # 3. Explicitly supported token (ByAddress) -> Allowed
        assert transfer_service._is_supported_token(valid_token_addr, chain_name) is True

        # 4. Arbitrary address -> BLOCKED
        # Even if it's a valid ETH address, if it's not in the map, it must be False
        assert transfer_service._is_supported_token(invalid_token_addr, chain_name) is False

        # 5. Garbage input -> BLOCKED
        assert transfer_service._is_supported_token("NOT_A_TOKEN", chain_name) is False
