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
    # Valid checksum addresses
    safe_address = "0xbEC49fa140ACaa83533f900357DCD37866d50618"

    # Mock Safe Account
    mock_account = MagicMock(spec=StoredSafeAccount)
    mock_account.address = safe_address
    mock_account.signers = ["0x5A0b54D5dc17e0AadC383d2db43B0a0D3E029c4c"]
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
        # IMPORTANT: safe_tx_gas must be int for comparisons
        mock_safe_tx.safe_tx_gas = 0
        mock_safe_tx.base_gas = 0
        mock_safe_instance.build_tx.return_value = mock_safe_tx
        mock_safe_tx.tx_hash.hex.return_value = "TxHash"

        # Mock SafeTransactionExecutor to avoid sleeps and network calls
        with patch("iwa.core.services.safe_executor.SafeTransactionExecutor") as mock_executor_cls:
            mock_executor = mock_executor_cls.return_value
            # Return (success, tx_hash, receipt)
            mock_executor.execute_with_retry.return_value = (True, "0xTxHash", {})

            # Execute
            tx_hash = safe_service.execute_safe_transaction(
                "safe_tag", "to_addr", 100, "gnosis", data="0x", operation=0
            )

            # Verify
            assert tx_hash == "0xTxHash"
            mock_executor.execute_with_retry.assert_called()


def test_execute_safe_transaction_account_not_found(safe_service, mock_deps):
    """Test execute_safe_transaction fails if account not found."""
    mock_deps["key_storage"].find_stored_account.return_value = None

    with pytest.raises(ValueError, match="Safe account '0xSafe' not found"):
        safe_service.execute_safe_transaction("0xSafe", "0xTo", 0, "gnosis")


def test_get_sign_and_execute_callback(safe_service, mock_deps):
    """Test get_sign_and_execute_callback returns working callback."""
    safe_address = "0xbEC49fa140ACaa83533f900357DCD37866d50618"
    mock_account = MagicMock(spec=StoredSafeAccount)
    mock_account.address = safe_address
    mock_account.signers = ["0x5A0b54D5dc17e0AadC383d2db43B0a0D3E029c4c"]
    mock_account.threshold = 1
    mock_deps["key_storage"].find_stored_account.return_value = mock_account
    mock_deps["key_storage"]._get_private_key.return_value = "0xPrivKey"

    with patch("iwa.plugins.gnosis.safe.SafeMultisig") as mock_safe_multisig:
        mock_safe_multisig.return_value.send_tx.return_value = "0xhash"

        callback = safe_service.get_sign_and_execute_callback("safe_tag", "gnosis")
        assert callable(callback)

        # Test executing callback
        mock_safe_tx = MagicMock()
        mock_safe_tx.safe_tx_gas = 0
        mock_safe_tx.base_gas = 0
        mock_safe_tx.tx_hash.hex.return_value = "TxHash"

        with patch("iwa.core.services.safe_executor.SafeTransactionExecutor") as mock_executor_cls:
            mock_executor_cls.return_value.execute_with_retry.return_value = (True, "0xTxHash", {})

            result = callback(mock_safe_tx)

            assert result == "0xTxHash"


def test_get_sign_and_execute_callback_fail(safe_service, mock_deps):
    """Test callback generation fails if account missing."""
    mock_deps["key_storage"].find_stored_account.return_value = None
    with pytest.raises(ValueError):
        safe_service.get_sign_and_execute_callback("unknown_tag", "gnosis")


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

    with patch("iwa.core.chain.models.secrets") as mock_settings:
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
