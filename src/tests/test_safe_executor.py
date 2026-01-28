"""Tests for SafeTransactionExecutor."""

from unittest.mock import MagicMock, patch

import pytest
from safe_eth.safe.safe_tx import SafeTx

from iwa.core.services.safe_executor import (
    MIN_SIGNATURE_LENGTH,
    SAFE_TX_STATS,
    SafeTransactionExecutor,
)


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
    """Mock SafeTx with valid 65-byte signature."""
    tx = MagicMock(spec=SafeTx)
    tx.safe_tx_gas = 100000
    tx.base_gas = 0
    tx.gas_price = 1000000000
    tx.to = "0xTo"
    tx.value = 0
    tx.data = b""
    tx.operation = 0
    # Valid signatures must be >= 65 bytes (one ECDSA signature)
    tx.signatures = b"x" * 65
    return tx


@pytest.fixture
def mock_safe():
    s = MagicMock()
    s.estimate_tx_gas.return_value = 100000
    s.retrieve_nonce.return_value = 5
    return s


# =============================================================================
# Test: Basic execution success
# =============================================================================


def test_execute_success_first_try(executor, mock_chain_interface, mock_safe_tx, mock_safe):
    """Test successful execution on first attempt."""
    with patch.object(executor, "_recreate_safe_client", return_value=mock_safe):
        mock_chain_interface.web3.eth.wait_for_transaction_receipt.return_value = MagicMock(
            status=1
        )
        mock_safe_tx.execute.return_value = b"tx_hash"

        success, tx_hash, receipt = executor.execute_with_retry("0xSafe", mock_safe_tx, ["key1"])

        assert success is True
        assert tx_hash == "0x" + b"tx_hash".hex()
        assert mock_safe_tx.execute.call_count == 1


# =============================================================================
# Test: Tuple vs bytes return handling
# =============================================================================


def test_execute_handles_tuple_return(executor, mock_chain_interface, mock_safe_tx, mock_safe):
    """Test that executor handles safe_tx.execute() returning tuple (tx_hash, tx)."""
    with patch.object(executor, "_recreate_safe_client", return_value=mock_safe):
        mock_chain_interface.web3.eth.wait_for_transaction_receipt.return_value = MagicMock(
            status=1
        )
        # Simulate tuple return: (tx_hash_bytes, tx_data)
        mock_safe_tx.execute.return_value = (b"tx_hash", {"gas": 21000})

        success, tx_hash, receipt = executor.execute_with_retry("0xSafe", mock_safe_tx, ["key1"])

        assert success is True
        assert tx_hash == "0x" + b"tx_hash".hex()


def test_execute_handles_bytes_return(executor, mock_chain_interface, mock_safe_tx, mock_safe):
    """Test that executor handles safe_tx.execute() returning raw bytes."""
    with patch.object(executor, "_recreate_safe_client", return_value=mock_safe):
        mock_chain_interface.web3.eth.wait_for_transaction_receipt.return_value = MagicMock(
            status=1
        )
        mock_safe_tx.execute.return_value = b"raw_hash"

        success, tx_hash, receipt = executor.execute_with_retry("0xSafe", mock_safe_tx, ["key1"])

        assert success is True
        assert tx_hash.startswith("0x")


def test_execute_handles_string_return(executor, mock_chain_interface, mock_safe_tx, mock_safe):
    """Test that executor handles safe_tx.execute() returning hex string."""
    with patch.object(executor, "_recreate_safe_client", return_value=mock_safe):
        mock_chain_interface.web3.eth.wait_for_transaction_receipt.return_value = MagicMock(
            status=1
        )
        mock_safe_tx.execute.return_value = "0xabcdef1234567890"

        success, tx_hash, receipt = executor.execute_with_retry("0xSafe", mock_safe_tx, ["key1"])

        assert success is True
        assert tx_hash == "0xabcdef1234567890"


# =============================================================================
# Test: Signature validation
# =============================================================================


def test_execute_fails_on_empty_signatures(executor, mock_chain_interface, mock_safe_tx, mock_safe):
    """Verify we fail immediately if no signatures exist."""
    mock_safe_tx.signatures = b""  # Empty signatures

    with patch.object(executor, "_recreate_safe_client", return_value=mock_safe):
        with patch("time.sleep"):
            success, error, _ = executor.execute_with_retry("0xSafe", mock_safe_tx, ["key1"])

    assert success is False
    assert "No valid signatures" in error
    assert mock_safe_tx.execute.call_count == 0  # Never tried to execute


def test_execute_fails_on_truncated_signatures(
    executor, mock_chain_interface, mock_safe_tx, mock_safe
):
    """Verify we detect signatures shorter than 65 bytes."""
    mock_safe_tx.signatures = b"x" * 30  # Too short (need 65)

    with patch.object(executor, "_recreate_safe_client", return_value=mock_safe):
        with patch("time.sleep"):
            success, error, _ = executor.execute_with_retry("0xSafe", mock_safe_tx, ["key1"])

    assert success is False
    assert "No valid signatures" in error or str(MIN_SIGNATURE_LENGTH) in error


def test_execute_fails_on_none_signatures(executor, mock_chain_interface, mock_safe_tx, mock_safe):
    """Verify we handle None signatures gracefully."""
    mock_safe_tx.signatures = None

    with patch.object(executor, "_recreate_safe_client", return_value=mock_safe):
        with patch("time.sleep"):
            success, error, _ = executor.execute_with_retry("0xSafe", mock_safe_tx, ["key1"])

    assert success is False
    assert "No valid signatures" in error


# =============================================================================
# Test: Error classification (GS0xx codes)
# =============================================================================


def test_gs020_fails_fast(executor, mock_chain_interface, mock_safe_tx, mock_safe):
    """GS020 (signatures too short) should not trigger retries."""
    with patch.object(executor, "_recreate_safe_client", return_value=mock_safe):
        mock_safe_tx.call.side_effect = ValueError("execution reverted: GS020")

        with patch("time.sleep"):
            success, error, _ = executor.execute_with_retry("0xSafe", mock_safe_tx, ["key1"])

        assert success is False
        assert "GS020" in error
        assert mock_safe_tx.execute.call_count == 0  # Never got to execute


def test_gs026_fails_fast(executor, mock_chain_interface, mock_safe_tx, mock_safe):
    """GS026 (invalid owner) should not trigger retries."""
    with patch.object(executor, "_recreate_safe_client", return_value=mock_safe):
        mock_safe_tx.call.side_effect = ValueError("execution reverted: GS026")

        with patch("time.sleep"):
            success, error, _ = executor.execute_with_retry("0xSafe", mock_safe_tx, ["key1"])

        assert success is False
        assert "GS026" in error


@pytest.mark.parametrize(
    "error_code,is_signature_error",
    [
        ("GS020", True),  # Signatures data too short
        ("GS021", True),  # Invalid signature data pointer
        ("GS024", True),  # Invalid contract signature
        ("GS026", True),  # Invalid owner
        ("GS025", False),  # Invalid nonce (not a signature error)
        ("GS010", False),  # Not enough gas
        ("GS013", False),  # Safe transaction failed
    ],
)
def test_error_classification(executor, error_code, is_signature_error):
    """Verify correct classification of Safe error codes."""
    error = ValueError(f"execution reverted: {error_code}")
    result = executor._is_signature_error(error)
    assert result == is_signature_error


# =============================================================================
# Test: Retry behavior
# =============================================================================


def test_retry_on_transient_error(executor, mock_chain_interface, mock_safe_tx, mock_safe):
    """Test that transient errors trigger retries without modifying tx."""
    with patch.object(executor, "_recreate_safe_client", return_value=mock_safe):
        mock_safe_tx.execute.side_effect = [ConnectionError("Network timeout"), b"success_hash"]
        mock_chain_interface.web3.eth.wait_for_transaction_receipt.return_value = MagicMock(
            status=1
        )
        mock_chain_interface._is_connection_error.return_value = True

        with patch("time.sleep"):
            success, tx_hash, receipt = executor.execute_with_retry(
                "0xSafe", mock_safe_tx, ["key1"]
            )

        assert success is True
        assert mock_safe_tx.execute.call_count == 2
        # Gas should NOT have changed (we don't modify after signing)
        assert mock_safe_tx.safe_tx_gas == 100000


def test_retry_on_nonce_error(executor, mock_chain_interface, mock_safe_tx, mock_safe):
    """Test nonce refresh on GS025 error."""
    with patch.object(executor, "_recreate_safe_client", return_value=mock_safe):
        mock_safe_tx.execute.side_effect = [ValueError("GS025: invalid nonce"), b"success_hash"]
        mock_chain_interface.web3.eth.wait_for_transaction_receipt.return_value = MagicMock(
            status=1
        )

        new_tx = MagicMock(spec=SafeTx)
        new_tx.signatures = b"x" * 65
        executor._refresh_nonce = MagicMock(return_value=new_tx)

        with patch("time.sleep"):
            executor.execute_with_retry("0xSafe", mock_safe_tx, ["key1"])

        assert executor._refresh_nonce.called
        assert new_tx.execute.called


def test_retry_on_rpc_error(executor, mock_chain_interface, mock_safe_tx, mock_safe):
    """Test RPC rotation on rate limit error."""
    with patch.object(executor, "_recreate_safe_client", return_value=mock_safe):
        mock_safe_tx.execute.side_effect = [ValueError("Rate limit exceeded"), b"success_hash"]
        mock_chain_interface._is_rate_limit_error.return_value = True
        mock_chain_interface.web3.eth.wait_for_transaction_receipt.return_value = MagicMock(
            status=1
        )

        with patch("time.sleep"):
            executor.execute_with_retry("0xSafe", mock_safe_tx, ["key1"])

        assert mock_chain_interface._handle_rpc_error.called
        assert mock_chain_interface._handle_rpc_error.call_count == 1


def test_fail_after_max_retries(executor, mock_chain_interface, mock_safe_tx, mock_safe):
    """Test failure after exhausting all retries."""
    executor.max_retries = 2
    with patch.object(executor, "_recreate_safe_client", return_value=mock_safe):
        mock_safe_tx.execute.side_effect = ValueError("Persistent error")

        with patch("time.sleep"):
            success, tx_hash_or_err, receipt = executor.execute_with_retry(
                "0xSafe", mock_safe_tx, ["key1"]
            )

        assert success is False
        assert mock_safe_tx.execute.call_count == 3  # 1 initial + 2 retries


# =============================================================================
# Test: State preservation during retries
# =============================================================================


def test_retry_preserves_signatures_despite_clearing(
    executor, mock_chain_interface, mock_safe_tx, mock_safe
):
    """Verify that retries don't corrupt/lose signatures even if library clears them."""
    original_signatures = mock_safe_tx.signatures

    # Define a side effect that clears signatures on success (mimicking safe-eth-py)
    def execute_side_effect(key, **kwargs):
        # Simulate library behavior: clears signatures after "executing"
        mock_safe_tx.signatures = b""
        return b"hash"

    with patch.object(executor, "_recreate_safe_client", return_value=mock_safe):
        # Scenario:
        # 1. Execute success (sigs cleared) but Receipt not found (triggering retry)
        # 2. Retry: Execute called again (must have restored sigs) -> Success -> Receipt found

        mock_chain_interface.web3.eth.wait_for_transaction_receipt.side_effect = [
            ValueError("Transaction not found"),
            MagicMock(status=1),
        ]

        mock_safe_tx.execute.side_effect = execute_side_effect
        mock_chain_interface._is_connection_error.return_value = False

        with patch("time.sleep"):
            success, tx_hash, receipt = executor.execute_with_retry(
                "0xSafe", mock_safe_tx, ["key1"]
            )

        assert success is True
        # Signatures should be restored after the loop (or at least valid during 2nd call)
        # We assert they match original at the end because the finally block restores if changed?
        # Wait, finally restores IF signatures != backup.
        # If call 2 succeeds, execute() sets signatures to b"" AGAIN at the end of call 2.
        # So at the end of execution, signatures ARE empty locally if we updated them?
        # NO, the finally block runs AFTER safe_tx.execute returns.
        # So after call 2 returns (sigs=b""), finally restores them (sigs=original).
        # So they should be original.
        assert mock_safe_tx.signatures == original_signatures
        assert mock_safe_tx.execute.call_count == 2


def test_retry_preserves_gas(executor, mock_chain_interface, mock_safe_tx, mock_safe):
    """Verify that retries don't modify safe_tx_gas (which would invalidate signatures)."""
    original_gas = mock_safe_tx.safe_tx_gas

    with patch.object(executor, "_recreate_safe_client", return_value=mock_safe):
        mock_safe_tx.execute.side_effect = [ConnectionError("timeout"), b"hash"]
        mock_chain_interface.web3.eth.wait_for_transaction_receipt.return_value = MagicMock(
            status=1
        )
        mock_chain_interface._is_connection_error.return_value = True

        with patch("time.sleep"):
            executor.execute_with_retry("0xSafe", mock_safe_tx, ["key1"])

        assert mock_safe_tx.safe_tx_gas == original_gas
