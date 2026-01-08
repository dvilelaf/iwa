"""Tests for SafeService coverage."""

from unittest.mock import MagicMock, patch

import pytest

from iwa.core.models import StoredSafeAccount
from iwa.core.services.safe import SafeService


@pytest.fixture
def mock_deps():
    """Mock dependencies for SafeService."""
    mock_key_storage = MagicMock()
    mock_account_service = MagicMock()

    return {
        "key_storage": mock_key_storage,
        "account_service": mock_account_service,
    }


@pytest.fixture
def safe_service(mock_deps):
    """SafeService instance."""
    return SafeService(mock_deps["key_storage"], mock_deps["account_service"])


def test_execute_safe_transaction_success(safe_service, mock_deps):
    """Test execute_safe_transaction success."""
    # Mock inputs
    safe_address = "0xSafe"
    to_address = "0xTo"
    value = 1000
    chain_name = "gnosis"

    # Mock Safe Account
    mock_account = MagicMock(spec=StoredSafeAccount)
    mock_account.address = safe_address
    mock_account.signers = ["0xSigner1", "0xSigner2"]
    mock_account.threshold = 1
    mock_deps["key_storage"].find_stored_account.return_value = mock_account

    # Mock Private Keys
    mock_deps["key_storage"]._get_private_key.return_value = "0xPrivKey"

    # Mock SafeMultisig via patch
    # The import is inside the method: from iwa.plugins.gnosis.safe import SafeMultisig
    # We need to patch where it is IMPORTED from
    with patch("iwa.plugins.gnosis.safe.SafeMultisig") as mock_safe_multisig_cls:
        # But wait, execute_safe_transaction does local import.
        # patch('iwa.core.services.safe.SafeMultisig') won't work if it's not global.
        # We must patch 'iwa.plugins.gnosis.safe.SafeMultisig'.
        # And since it's imported INSIDE the function, patching the source module works.

        mock_safe_instance = mock_safe_multisig_cls.return_value
        mock_safe_tx = MagicMock()
        mock_safe_instance.build_tx.return_value = mock_safe_tx
        mock_safe_tx.tx_hash.hex.return_value = "0xTxHash"

        # Execute
        tx_hash = safe_service.execute_safe_transaction(safe_address, to_address, value, chain_name)

        # Verify
        assert tx_hash == "0xTxHash"
        mock_safe_tx.sign.assert_called()
        mock_safe_tx.execute.assert_called()


def test_execute_safe_transaction_account_not_found(safe_service, mock_deps):
    """Test execute_safe_transaction fails if account not found."""
    mock_deps["key_storage"].find_stored_account.return_value = None

    with pytest.raises(ValueError, match="Safe account '0xSafe' not found"):
        safe_service.execute_safe_transaction("0xSafe", "0xTo", 0, "gnosis")


def test_get_sign_and_execute_callback(safe_service, mock_deps):
    """Test get_sign_and_execute_callback returns working callback."""
    safe_address = "0xSafe"
    mock_account = MagicMock(spec=StoredSafeAccount)
    mock_account.address = safe_address
    mock_account.signers = ["0xSigner1"]
    mock_account.threshold = 1
    mock_deps["key_storage"].find_stored_account.return_value = mock_account
    mock_deps["key_storage"]._get_private_key.return_value = "0xPrivKey"

    callback = safe_service.get_sign_and_execute_callback(safe_address)
    assert callable(callback)

    # Test executing callback
    mock_safe_tx = MagicMock()
    mock_safe_tx.tx_hash.hex.return_value = "0xTxHash"

    result = callback(mock_safe_tx)

    assert result == "0xTxHash"
    mock_safe_tx.sign.assert_called()
    mock_safe_tx.execute.assert_called()


def test_get_sign_and_execute_callback_fail(safe_service, mock_deps):
    """Test callback generation fails if account missing."""
    mock_deps["key_storage"].find_stored_account.return_value = None
    with pytest.raises(ValueError):
        safe_service.get_sign_and_execute_callback("0xSafe")


def test_redeploy_safes(safe_service, mock_deps):
    """Test redeploy_safes logic."""
    # Mock accounts
    account1 = MagicMock(spec=StoredSafeAccount)
    account1.address = "0xSafe1"
    account1.chains = ["gnosis"]
    account1.signers = ["0xSigner"]
    account1.threshold = 1
    # account1.tag needs to be accessible
    account1.tag = " Safe1"

    mock_deps["key_storage"].accounts = {"0xSafe1": account1}

    with patch("iwa.core.services.safe.settings") as mock_settings:
        mock_settings.gnosis_rpc.get_secret_value.return_value = "http://rpc"

        with patch("iwa.core.services.safe.EthereumClient") as mock_eth_client:
            with patch.object(safe_service, "create_safe") as mock_create:
                mock_w3 = mock_eth_client.return_value.w3

                # Case 1: Code exists (no redeploy)
                mock_w3.eth.get_code.return_value = b"code"
                safe_service.redeploy_safes()
                mock_create.assert_not_called()

                # Case 2: No code (redeploy)
                mock_w3.eth.get_code.return_value = b""
                # Need to mock remove_account
                safe_service.redeploy_safes()
                mock_deps["key_storage"].remove_account.assert_called_with("0xSafe1")
                mock_create.assert_called()
