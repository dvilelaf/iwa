"""Tests for SafeTransactionExecutor."""

from unittest.mock import MagicMock, patch

import pytest
from safe_eth.safe.safe_tx import SafeTx

from iwa.core.services.safe_executor import SAFE_TX_STATS, SafeTransactionExecutor


@pytest.fixture(autouse=True)
def reset_stats():
    """Reset SAFE_TX_STATS before each test to prevent state leakage."""
    for key in SAFE_TX_STATS:
        SAFE_TX_STATS[key] = 0
    yield

@pytest.fixture
def mock_chain_interface():
    ci = MagicMock()
    ci.current_rpc = "http://mock-rpc"
    ci.DEFAULT_MAX_RETRIES = 6
    ci._is_rate_limit_error.return_value = False
    ci._is_connection_error.return_value = False
    ci._handle_rpc_error.return_value = {"should_retry": True}
    return ci

@pytest.fixture
def executor(mock_chain_interface):
    return SafeTransactionExecutor(mock_chain_interface)

@pytest.fixture
def mock_safe_tx():
    tx = MagicMock(spec=SafeTx)
    tx.safe_tx_gas = 100000
    tx.base_gas = 0
    tx.gas_price = 1000000000
    tx.to = "0xTo"
    tx.value = 0
    tx.data = b""
    tx.operation = 0
    tx.signatures = b""
    return tx

@pytest.fixture
def mock_safe():
    s = MagicMock()
    s.estimate_tx_gas.return_value = 100000
    s.retrieve_nonce.return_value = 5
    return s

def test_execute_success_first_try(executor, mock_chain_interface, mock_safe_tx, mock_safe):
    with patch.object(executor, '_recreate_safe_client', return_value=mock_safe):
        mock_chain_interface.web3.eth.wait_for_transaction_receipt.return_value = MagicMock(status=1)
        mock_safe_tx.execute.return_value = b"tx_hash"

        success, tx_hash, receipt = executor.execute_with_retry("0xSafe", mock_safe_tx, ["key1"])

        assert success is True
        assert tx_hash == "0x" + b"tx_hash".hex()
        assert mock_safe_tx.execute.call_count == 1

def test_execute_retry_on_transient_error(executor, mock_chain_interface, mock_safe_tx, mock_safe):
    """Test that transient errors (non-gas, non-nonce) trigger retries without modifying tx."""
    with patch.object(executor, '_recreate_safe_client', return_value=mock_safe):
        # First execution fails with transient error, second succeeds
        mock_safe_tx.execute.side_effect = [
            ConnectionError("Network timeout"),
            b"success_hash"
        ]
        mock_chain_interface.web3.eth.wait_for_transaction_receipt.return_value = MagicMock(status=1)
        mock_chain_interface._is_connection_error.return_value = True

        with patch("time.sleep"):  # Avoid delays
            success, tx_hash, receipt = executor.execute_with_retry("0xSafe", mock_safe_tx, ["key1"])

        assert success is True
        assert mock_safe_tx.execute.call_count == 2
        # Gas should NOT have changed (we don't modify after signing)
        assert mock_safe_tx.safe_tx_gas == 100000

def test_execute_signature_error_fails_fast(executor, mock_chain_interface, mock_safe_tx, mock_safe):
    """Test that GS026 (invalid signatures) fails immediately without retrying."""
    with patch.object(executor, '_recreate_safe_client', return_value=mock_safe):
        # Simulate GS026 signature error
        mock_safe_tx.call.side_effect = ValueError("execution reverted: GS026")

        with patch("time.sleep"):
            success, error, receipt = executor.execute_with_retry("0xSafe", mock_safe_tx, ["key1"])

        assert success is False
        # Should fail on first attempt without retrying (signature errors are not recoverable)
        assert mock_safe_tx.execute.call_count == 0  # Never got to execute
        assert "GS026" in error

def test_execute_retry_on_nonce_error(executor, mock_chain_interface, mock_safe_tx, mock_safe):
    with patch.object(executor, '_recreate_safe_client', return_value=mock_safe):
        # Set up nonce error (GS025 = invalid nonce, NOT GS026 which is invalid signatures)
        mock_safe_tx.execute.side_effect = [
            ValueError("GS025: invalid nonce"),
            b"success_hash"
        ]
        mock_chain_interface.web3.eth.wait_for_transaction_receipt.return_value = MagicMock(status=1)

        # Mock refresh_nonce to return a slightly different tx (simulated)
        new_tx = MagicMock(spec=SafeTx)
        executor._refresh_nonce = MagicMock(return_value=new_tx)

        with patch("time.sleep"):
            executor.execute_with_retry("0xSafe", mock_safe_tx, ["key1"])

        assert executor._refresh_nonce.called
        assert new_tx.execute.called

def test_execute_retry_on_rpc_error(executor, mock_chain_interface, mock_safe_tx, mock_safe):
    with patch.object(executor, '_recreate_safe_client', return_value=mock_safe):
        mock_safe_tx.execute.side_effect = [
            ValueError("Rate limit exceeded"),
            b"success_hash"
        ]
        mock_chain_interface._is_rate_limit_error.return_value = True
        mock_chain_interface.web3.eth.wait_for_transaction_receipt.return_value = MagicMock(status=1)

        with patch("time.sleep"):
            executor.execute_with_retry("0xSafe", mock_safe_tx, ["key1"])

        assert mock_chain_interface._handle_rpc_error.called
        assert mock_chain_interface._handle_rpc_error.call_count == 1

def test_execute_fail_after_max_retries(executor, mock_chain_interface, mock_safe_tx, mock_safe):
    executor.max_retries = 2
    with patch.object(executor, '_recreate_safe_client', return_value=mock_safe):
        mock_safe_tx.execute.side_effect = ValueError("Persistent error")

        with patch("time.sleep"):
            success, tx_hash_or_err, receipt = executor.execute_with_retry("0xSafe", mock_safe_tx, ["key1"])

        assert success is False
        assert mock_safe_tx.execute.call_count == 3  # 1 initial + 2 retries
