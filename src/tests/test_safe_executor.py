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
    """GS026 (invalid owner) should abort after exactly 1 attempt, never retried."""
    with patch.object(executor, "_recreate_safe_client", return_value=mock_safe):
        mock_safe_tx.call.side_effect = ValueError("execution reverted: GS026")

        with patch("time.sleep") as mock_sleep:
            success, error, _ = executor.execute_with_retry("0xSafe", mock_safe_tx, ["key1"])

        assert success is False
        assert "GS026" in error
        # Must have called simulation exactly once (no retries)
        assert mock_safe_tx.call.call_count == 1
        # Must never have slept (no retry delay)
        mock_sleep.assert_not_called()


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
    """Test nonce refresh and re-signing on GS025 error."""
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

        # Verify _refresh_nonce received signer_keys
        executor._refresh_nonce.assert_called_once()
        call_args = executor._refresh_nonce.call_args
        assert call_args[0][2] == ["key1"]  # signer_keys
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


# =============================================================================
# Test: Gas estimation (_estimate_safe_tx_gas)
# =============================================================================


def test_estimate_safe_tx_gas_with_buffer(executor, mock_safe):
    """Test gas estimation applies buffer correctly."""
    mock_safe.estimate_tx_gas.return_value = 100_000
    mock_safe_tx = MagicMock()
    mock_safe_tx.to = "0xDest"
    mock_safe_tx.value = 0
    mock_safe_tx.data = b""
    mock_safe_tx.operation = 0

    result = executor._estimate_safe_tx_gas(mock_safe, mock_safe_tx)

    # Default buffer is 1.5, so 100000 * 1.5 = 150000
    assert result == 150_000


def test_estimate_safe_tx_gas_caps_at_10x(executor, mock_safe):
    """Test gas estimation respects x10 cap when base_estimate is provided."""
    mock_safe.estimate_tx_gas.return_value = 500_000  # High estimate
    mock_safe_tx = MagicMock()
    mock_safe_tx.to = "0xDest"
    mock_safe_tx.value = 0
    mock_safe_tx.data = b""
    mock_safe_tx.operation = 0

    # 500000 * 1.5 = 750000, but base_estimate * 10 = 50000
    result = executor._estimate_safe_tx_gas(mock_safe, mock_safe_tx, base_estimate=5_000)

    # Should be capped at 5000 * 10 = 50000
    assert result == 50_000


def test_estimate_safe_tx_gas_fallback_on_failure(executor, mock_safe):
    """Test gas estimation uses fallback when estimation fails."""
    mock_safe.estimate_tx_gas.side_effect = Exception("Estimation failed")
    mock_safe_tx = MagicMock()
    mock_safe_tx.to = "0xDest"
    mock_safe_tx.value = 0
    mock_safe_tx.data = b""
    mock_safe_tx.operation = 0

    result = executor._estimate_safe_tx_gas(mock_safe, mock_safe_tx)

    assert result == executor.DEFAULT_FALLBACK_GAS


# =============================================================================
# Test: Error decoding (_decode_revert_reason)
# =============================================================================


def test_decode_revert_reason_with_hex_data(executor):
    """Test decoding when error contains hex data."""
    # Create an error with hex data that might be decodable
    error = ValueError("execution reverted: 0x08c379a0...")

    with patch("iwa.core.services.safe_executor.ErrorDecoder") as mock_decoder:
        mock_decoder.return_value.decode.return_value = [("Error", "Insufficient balance", "ERC20")]
        result = executor._decode_revert_reason(error)

    # Note: Due to hex matching, this should find the data and attempt decode
    assert result == "Insufficient balance (from ERC20)"


def test_decode_revert_reason_no_hex_data(executor):
    """Test decoding when error has no hex data."""
    error = ValueError("Some generic error without hex")

    result = executor._decode_revert_reason(error)

    assert result is None


def test_decode_revert_reason_decode_fails(executor):
    """Test decoding when decoder returns None."""
    error = ValueError("error: 0xdeadbeef")

    with patch("iwa.core.services.safe_executor.ErrorDecoder") as mock_decoder:
        mock_decoder.return_value.decode.return_value = None
        result = executor._decode_revert_reason(error)

    assert result is None


# =============================================================================
# Test: Error classification
# =============================================================================


def test_classify_error_gas_error(executor):
    """Test classification of gas-related errors."""
    error = ValueError("intrinsic gas too low")
    result = executor._classify_error(error)

    assert result["is_gas_error"] is True
    assert result["is_nonce_error"] is False


def test_classify_error_revert(executor):
    """Test classification of revert errors."""
    error = ValueError("execution reverted: some reason")
    result = executor._classify_error(error)

    assert result["is_revert"] is True


def test_classify_error_out_of_gas(executor):
    """Test classification of out of gas errors."""
    error = ValueError("out of gas")
    result = executor._classify_error(error)

    assert result["is_gas_error"] is True


# =============================================================================
# Test: Transaction failures
# =============================================================================


def test_transaction_reverts_onchain(executor, mock_chain_interface, mock_safe_tx, mock_safe):
    """Test handling when transaction is mined but reverts (status 0)."""
    with patch.object(executor, "_recreate_safe_client", return_value=mock_safe):
        mock_safe_tx.execute.return_value = b"tx_hash"
        # Receipt with status 0 (reverted)
        mock_chain_interface.web3.eth.wait_for_transaction_receipt.return_value = MagicMock(
            status=0
        )

        with patch("time.sleep"):
            success, error, receipt = executor.execute_with_retry(
                "0xSafe", mock_safe_tx, ["key1"]
            )

        assert success is False
        assert "reverted" in error.lower()


def test_check_receipt_status_dict_format(executor):
    """Test receipt status check with dict-style receipt."""
    # Dict-style receipt (not MagicMock)
    receipt_dict = {"status": 1, "gasUsed": 21000}
    assert executor._check_receipt_status(receipt_dict) is True

    receipt_dict_failed = {"status": 0}
    assert executor._check_receipt_status(receipt_dict_failed) is False


def test_simulation_revert_not_nonce(executor, mock_chain_interface, mock_safe_tx, mock_safe):
    """Test handling when simulation reverts with non-nonce error."""
    with patch.object(executor, "_recreate_safe_client", return_value=mock_safe):
        # Simulation fails with generic revert
        mock_safe_tx.call.side_effect = ValueError("execution reverted: insufficient funds")

        with patch("time.sleep"):
            success, error, receipt = executor.execute_with_retry(
                "0xSafe", mock_safe_tx, ["key1"]
            )

        assert success is False
        assert "insufficient funds" in error.lower() or "reverted" in error.lower()


def test_gas_error_strategy_triggers_retry(
    executor, mock_chain_interface, mock_safe_tx, mock_safe
):
    """Test that gas errors trigger retry with gas increase strategy."""
    with patch.object(executor, "_recreate_safe_client", return_value=mock_safe):
        mock_safe_tx.execute.side_effect = [
            ValueError("intrinsic gas too low"),
            b"tx_hash",
        ]
        mock_chain_interface.web3.eth.wait_for_transaction_receipt.return_value = MagicMock(
            status=1
        )

        with patch("time.sleep"):
            success, tx_hash, receipt = executor.execute_with_retry(
                "0xSafe", mock_safe_tx, ["key1"]
            )

        # Should have retried and succeeded
        assert success is True
        assert mock_safe_tx.execute.call_count == 2


def test_rpc_rotation_stops_when_should_not_retry(
    executor, mock_chain_interface, mock_safe_tx, mock_safe
):
    """Test that execution stops when RPC handler says not to retry."""
    with patch.object(executor, "_recreate_safe_client", return_value=mock_safe):
        mock_safe_tx.execute.side_effect = ValueError("Rate limit exceeded")
        mock_chain_interface._is_rate_limit_error.return_value = True
        mock_chain_interface._handle_rpc_error.return_value = {"should_retry": False}

        with patch("time.sleep"):
            success, error, receipt = executor.execute_with_retry(
                "0xSafe", mock_safe_tx, ["key1"]
            )

        assert success is False
        # Only 1 attempt because should_retry=False
        assert mock_safe_tx.execute.call_count == 1


# =============================================================================
# Test: Fee bumping on base fee errors
# =============================================================================


def test_fee_error_triggers_bump(executor, mock_chain_interface, mock_safe_tx, mock_safe):
    """Test that fee errors trigger gas price bump on retry."""
    with patch.object(executor, "_recreate_safe_client", return_value=mock_safe):
        # First attempt fails with fee error, second succeeds
        mock_safe_tx.execute.side_effect = [
            ValueError("max fee per gas less than block base fee: maxFeePerGas: 596, baseFee: 681"),
            b"tx_hash",
        ]
        mock_chain_interface.web3.eth.wait_for_transaction_receipt.return_value = MagicMock(
            status=1
        )
        # Mock fee calculation
        mock_chain_interface.web3.eth.get_block.return_value = {"baseFeePerGas": 700}
        mock_chain_interface.web3.eth.max_priority_fee = 1

        with patch("time.sleep"):
            success, tx_hash, receipt = executor.execute_with_retry(
                "0xSafe", mock_safe_tx, ["key1"]
            )

        assert success is True
        assert mock_safe_tx.execute.call_count == 2
        # Second call should have tx_gas_price (bumped), not eip1559_speed
        second_call_kwargs = mock_safe_tx.execute.call_args_list[1][1]
        assert "tx_gas_price" in second_call_kwargs


def test_fee_error_classification(executor):
    """Test classification of fee-related errors."""
    fee_errors = [
        "max fee per gas less than block base fee",
        "transaction underpriced",
        "maxFeePerGas too low",
        "fee too low for mempool",
        # Gnosis-specific: RPC sends "FeeTooLow" (no space) and
        # "EffectivePriorityFeePerGas too low 0 < 1" — must be classified as
        # fee error so fee_bump_factor gets incremented on retry.
        "FeeTooLow, EffectivePriorityFeePerGas too low 0 < 1, BaseFee: 413",
        "{'code': -32010, 'message': 'FeeTooLow, EffectivePriorityFeePerGas too low 0 < 1'}",
    ]
    for error_msg in fee_errors:
        error = ValueError(error_msg)
        result = executor._classify_error(error)
        assert result["is_fee_error"] is True, f"Should detect fee error: {error_msg}"


def test_execute_with_gas_pricing_always_forces_priority_fee(executor, mock_chain_interface):
    """First attempt must not rely on safe-eth-py's eip1559_speed=FAST.

    Gnosis RPC returns max_priority_fee=0; letting safe-eth-py set the fee
    produces maxPriorityFeePerGas=0 which is rejected with FeeTooLow.
    _execute_with_gas_pricing must always use _calculate_bumped_gas_price.
    """
    mock_chain_interface.web3.eth.get_block.return_value = {"baseFeePerGas": 413}
    mock_chain_interface.web3.eth.max_priority_fee = 0  # Gnosis returns 0

    mock_safe_tx = MagicMock()
    mock_safe_tx.execute.return_value = b"\xab" * 32

    # fee_bump_factor=1.0 (first attempt) must still calculate bumped price
    executor._execute_with_gas_pricing(mock_safe_tx, "0xkey", 1.0, "test")

    # Must call execute with tx_gas_price, NOT with eip1559_speed
    call_kwargs = mock_safe_tx.execute.call_args
    assert "tx_gas_price" in call_kwargs.kwargs or (
        len(call_kwargs.args) >= 2 and call_kwargs.args[1] is not None
    ), "Should pass tx_gas_price explicitly, not rely on eip1559_speed"
    # eip1559_speed must NOT be set (would bypass our priority fee floor)
    assert "eip1559_speed" not in call_kwargs.kwargs


def test_calculate_bumped_gas_price_zero_priority_fee_floor(executor, mock_chain_interface):
    """When RPC returns max_priority_fee=0, bumped price must include >= 1 wei priority."""
    mock_chain_interface.web3.eth.get_block.return_value = {"baseFeePerGas": 413}
    mock_chain_interface.web3.eth.max_priority_fee = 0  # Gnosis

    result = executor._calculate_bumped_gas_price(1.0)

    assert result is not None
    # base_fee * 1.0 * 1.5 + 1 (floor) = 619 + 1 = 620
    expected = int(413 * 1.0 * 1.5) + 1
    assert result == expected, f"Expected {expected}, got {result}"


def test_calculate_bumped_gas_price_eip1559(executor, mock_chain_interface):
    """Test bumped gas price calculation for EIP-1559 chains."""
    mock_chain_interface.web3.eth.get_block.return_value = {"baseFeePerGas": 1000}
    mock_chain_interface.web3.eth.max_priority_fee = 10

    # With 1.3x bump factor: base_fee * 1.3 * 1.5 + priority = 1000 * 1.3 * 1.5 + 10 = 1960
    result = executor._calculate_bumped_gas_price(1.3)

    assert result is not None
    assert result == int(1000 * 1.3 * 1.5) + 10


def test_calculate_bumped_gas_price_legacy(executor, mock_chain_interface):
    """Test bumped gas price calculation for legacy chains."""
    mock_chain_interface.web3.eth.get_block.return_value = {}  # No baseFeePerGas
    mock_chain_interface.web3.eth.gas_price = 2000

    # Legacy: gas_price * bump_factor = 2000 * 1.3 = 2600
    result = executor._calculate_bumped_gas_price(1.3)

    assert result is not None
    assert result == int(2000 * 1.3)


# =============================================================================
# Test: Signature errors abort immediately (_handle_execution_failure)
# =============================================================================


def test_gs026_in_execute_phase_aborts(executor, mock_chain_interface, mock_safe_tx, mock_safe):
    """GS026 raised during execute (not simulation) also aborts immediately."""
    with patch.object(executor, "_recreate_safe_client", return_value=mock_safe):
        # Simulation passes, but execute raises GS026
        mock_safe_tx.execute.side_effect = ValueError("execution reverted: GS026")

        with patch("time.sleep") as mock_sleep:
            success, error, _ = executor.execute_with_retry("0xSafe", mock_safe_tx, ["key1"])

        assert success is False
        assert "GS026" in error
        assert mock_safe_tx.execute.call_count == 1
        mock_sleep.assert_not_called()
        assert SAFE_TX_STATS["signature_errors"] == 1


def test_gs020_in_execute_phase_aborts(executor, mock_chain_interface, mock_safe_tx, mock_safe):
    """GS020 raised during execute phase also aborts immediately."""
    with patch.object(executor, "_recreate_safe_client", return_value=mock_safe):
        mock_safe_tx.execute.side_effect = ValueError("GS020: Signatures data too short")

        with patch("time.sleep") as mock_sleep:
            success, error, _ = executor.execute_with_retry("0xSafe", mock_safe_tx, ["key1"])

        assert success is False
        assert "GS020" in error
        assert mock_safe_tx.execute.call_count == 1
        mock_sleep.assert_not_called()


# =============================================================================
# Test: Nonce collision error classification
# =============================================================================


def test_could_not_replace_tx_classified_as_nonce(executor):
    """'could not replace existing tx' should be classified as nonce error."""
    error = ValueError("could not replace existing tx 0xabc123 with same nonce")
    assert executor._is_nonce_error(error) is True


def test_replacement_tx_underpriced_classified_as_nonce(executor):
    """'replacement transaction underpriced' should be classified as nonce error."""
    error = ValueError("replacement transaction underpriced")
    assert executor._is_nonce_error(error) is True


def test_could_not_replace_triggers_nonce_refresh(
    executor, mock_chain_interface, mock_safe_tx, mock_safe
):
    """'could not replace existing tx' triggers nonce refresh and re-signing."""
    new_tx = MagicMock(spec=SafeTx)
    new_tx.signatures = b"x" * 65

    with patch.object(executor, "_recreate_safe_client", return_value=mock_safe):
        mock_safe_tx.execute.side_effect = [
            ValueError("could not replace existing tx 0xabc"),
            b"tx_hash",
        ]
        mock_chain_interface.web3.eth.wait_for_transaction_receipt.return_value = MagicMock(
            status=1
        )
        executor._refresh_nonce = MagicMock(return_value=new_tx)

        with patch("time.sleep"):
            success, _, _ = executor.execute_with_retry("0xSafe", mock_safe_tx, ["key1"])

        # Verify _refresh_nonce received signer_keys
        executor._refresh_nonce.assert_called_once()
        call_args = executor._refresh_nonce.call_args
        assert call_args[0][2] == ["key1"]  # signer_keys
        assert SAFE_TX_STATS["nonce_retries"] >= 1


# =============================================================================
# Test: Timeout classification and handling
# =============================================================================


def test_classify_timeout_not_in_chain(executor):
    """'not in the chain after N seconds' classified as timeout."""
    error = ValueError("Transaction 0xabc not in the chain after 120 seconds")
    result = executor._classify_error(error)
    assert result["is_timeout"] is True


def test_generic_timed_out_not_classified_as_timeout(executor):
    """Generic 'timed out' is NOT classified as timeout (could be network-level)."""
    error = ValueError("Request timed out waiting for receipt")
    result = executor._classify_error(error)
    assert result["is_timeout"] is False


def test_timeout_triggers_nonce_refresh(
    executor, mock_chain_interface, mock_safe_tx, mock_safe
):
    """TX timeout triggers nonce refresh and re-signing."""
    new_tx = MagicMock(spec=SafeTx)
    new_tx.signatures = b"x" * 65

    with patch.object(executor, "_recreate_safe_client", return_value=mock_safe):
        mock_safe_tx.execute.return_value = b"tx_hash"
        # First wait_for_receipt times out, second succeeds
        mock_chain_interface.web3.eth.wait_for_transaction_receipt.side_effect = [
            ValueError("Transaction 0xabc not in the chain after 120 seconds"),
            MagicMock(status=1),
        ]
        executor._refresh_nonce = MagicMock(return_value=new_tx)

        with patch("time.sleep"):
            success, _, _ = executor.execute_with_retry("0xSafe", mock_safe_tx, ["key1"])

        # Verify _refresh_nonce received signer_keys
        executor._refresh_nonce.assert_called_once()
        call_args = executor._refresh_nonce.call_args
        assert call_args[0][2] == ["key1"]  # signer_keys
        assert SAFE_TX_STATS["nonce_retries"] >= 1


def test_nonce_refresh_resigns_transaction(executor, mock_chain_interface, mock_safe):
    """Verify _refresh_nonce re-signs the new SafeTx with all signer keys."""
    # Build a mock SafeTx that _refresh_nonce will use as input
    old_tx = MagicMock(spec=SafeTx)
    old_tx.to = "0xDest"
    old_tx.value = 0
    old_tx.data = b""
    old_tx.operation = 0
    old_tx.safe_tx_gas = 100000
    old_tx.base_gas = 0
    old_tx.gas_price = 0
    old_tx.gas_token = "0x0000000000000000000000000000000000000000"
    old_tx.refund_receiver = "0x0000000000000000000000000000000000000000"

    # The new tx returned by build_multisig_tx
    new_tx = MagicMock(spec=SafeTx)
    new_tx.signatures = b""
    mock_safe.build_multisig_tx.return_value = new_tx
    mock_safe.retrieve_nonce.return_value = 42

    signer_keys = ["0xkey1", "0xkey2"]
    result = executor._refresh_nonce(mock_safe, old_tx, signer_keys)

    assert result is new_tx
    # Must have called sign() once per key
    assert new_tx.sign.call_count == 2
    new_tx.sign.assert_any_call("0xkey1")
    new_tx.sign.assert_any_call("0xkey2")


def test_nonce_refresh_skips_empty_keys(executor, mock_safe):
    """Verify _refresh_nonce skips None/empty keys."""
    old_tx = MagicMock(spec=SafeTx)
    old_tx.to = "0xDest"
    old_tx.value = 0
    old_tx.data = b""
    old_tx.operation = 0
    old_tx.safe_tx_gas = 0
    old_tx.base_gas = 0
    old_tx.gas_price = 0
    old_tx.gas_token = "0x0000000000000000000000000000000000000000"
    old_tx.refund_receiver = "0x0000000000000000000000000000000000000000"

    new_tx = MagicMock(spec=SafeTx)
    mock_safe.build_multisig_tx.return_value = new_tx
    mock_safe.retrieve_nonce.return_value = 1

    executor._refresh_nonce(mock_safe, old_tx, ["0xkey1", "", None])

    # Only "0xkey1" should be signed (empty string and None skipped)
    assert new_tx.sign.call_count == 1
    new_tx.sign.assert_called_once_with("0xkey1")


def test_normal_error_not_classified_as_timeout(executor):
    """Regular errors should not be classified as timeout."""
    error = ValueError("intrinsic gas too low")
    result = executor._classify_error(error)
    assert result["is_timeout"] is False


# =============================================================================
# Test: InsufficientFunds aborts immediately
# =============================================================================


@pytest.mark.parametrize(
    "error_msg",
    [
        "InsufficientFunds, Balance is 403578595673862 less than sending value + gas 2230304448944600",
        "{'code': -32010, 'message': 'InsufficientFunds'}",
        "insufficient funds for gas * price + value",
        "sender doesn't have enough funds to send tx",
        "insufficient balance for transfer",
    ],
)
def test_insufficient_funds_classified(executor, error_msg):
    """Various InsufficientFunds messages are correctly classified."""
    error = ValueError(error_msg)
    result = executor._classify_error(error)
    assert result["is_insufficient_funds"] is True


def test_insufficient_funds_aborts_immediately(
    executor, mock_chain_interface, mock_safe_tx, mock_safe
):
    """InsufficientFunds should abort after exactly 1 attempt."""
    with patch.object(executor, "_recreate_safe_client", return_value=mock_safe):
        mock_safe_tx.execute.side_effect = ValueError(
            "{'code': -32010, 'message': 'InsufficientFunds, Balance is 403578595673862 "
            "less than sending value + gas 2230304448944600'}"
        )

        with patch("time.sleep") as mock_sleep:
            success, error, _ = executor.execute_with_retry("0xSafe", mock_safe_tx, ["key1"])

        assert success is False
        assert "insufficientfunds" in error.lower() or "insufficient" in error.lower()
        assert mock_safe_tx.execute.call_count == 1
        mock_sleep.assert_not_called()
        assert SAFE_TX_STATS["insufficient_funds"] == 1


def test_normal_error_not_classified_as_insufficient_funds(executor):
    """Regular errors should not be classified as insufficient funds."""
    error = ValueError("execution reverted: GS026")
    result = executor._classify_error(error)
    assert result["is_insufficient_funds"] is False


# =============================================================================
# Test: GS013 (inner call revert) is retryable
# =============================================================================


def test_gs013_classified_as_inner_revert(executor):
    """GS013 should be classified as gs013_inner_revert (retryable)."""
    error = ValueError("execution reverted: GS013")
    result = executor._classify_error(error)
    assert result["is_gs013_inner_revert"] is True


def test_gs013_not_classified_for_other_errors(executor):
    """Other Safe errors should not be classified as gs013_inner_revert."""
    for code in ["GS020", "GS025", "GS026", "intrinsic gas too low"]:
        error = ValueError(f"execution reverted: {code}")
        result = executor._classify_error(error)
        assert result["is_gs013_inner_revert"] is False, (
            f"{code} should not be gs013_inner_revert"
        )


def test_gs013_is_retried(executor, mock_chain_interface, mock_safe_tx, mock_safe):
    """GS013 raised during execute should be retried (not abort immediately)."""
    with patch.object(executor, "_recreate_safe_client", return_value=mock_safe):
        # Simulation passes, but execute raises GS013 every time
        mock_safe_tx.execute.side_effect = ValueError("execution reverted: GS013")

        with patch("time.sleep"):
            success, error, _ = executor.execute_with_retry("0xSafe", mock_safe_tx, ["key1"])

        assert success is False
        assert "GS013" in error
        # Should have retried multiple times (not just 1)
        assert mock_safe_tx.execute.call_count > 1
        assert SAFE_TX_STATS["gs013_inner_revert_retries"] > 0


def test_gs013_simulation_is_retried(
    executor, mock_chain_interface, mock_safe_tx, mock_safe
):
    """GS013 in simulation should be retried, not fail fast."""
    with patch.object(executor, "_recreate_safe_client", return_value=mock_safe):
        mock_safe_tx.call.side_effect = ValueError("execution reverted: GS013")

        with patch("time.sleep"):
            success, error, _ = executor.execute_with_retry("0xSafe", mock_safe_tx, ["key1"])

        assert success is False
        assert "GS013" in error
        # Should have retried simulation multiple times
        assert mock_safe_tx.call.call_count > 1


def test_gs013_transient_succeeds_on_retry(
    executor, mock_chain_interface, mock_safe_tx, mock_safe
):
    """GS013 that resolves after a few retries should succeed."""
    with patch.object(executor, "_recreate_safe_client", return_value=mock_safe):
        # Simulation fails twice with GS013, then succeeds
        mock_safe_tx.call.side_effect = [
            ValueError("execution reverted: GS013"),
            ValueError("execution reverted: GS013"),
            None,  # success
        ]
        mock_safe_tx.execute.return_value = {"transactionHash": b"\x01" * 32}
        mock_safe_tx.tx_hash = b"\x01" * 32
        mock_chain_interface.web3.eth.wait_for_transaction_receipt.return_value = (
            MagicMock(status=1)
        )

        with patch("time.sleep"):
            success, error, _ = executor.execute_with_retry("0xSafe", mock_safe_tx, ["key1"])

        assert success is True
        assert mock_safe_tx.call.call_count == 3


def test_gs013_execution_transient_succeeds_on_retry(
    executor, mock_chain_interface, mock_safe_tx, mock_safe
):
    """GS013 during execution (not simulation) that resolves on retry should succeed."""
    with patch.object(executor, "_recreate_safe_client", return_value=mock_safe):
        # Simulation always passes
        mock_safe_tx.call.return_value = None
        # Execute fails twice with GS013, then succeeds
        mock_safe_tx.execute.side_effect = [
            ValueError("execution reverted: GS013"),
            ValueError("execution reverted: GS013"),
            (b"\x02" * 32, None),
        ]
        mock_chain_interface.web3.eth.wait_for_transaction_receipt.return_value = (
            MagicMock(status=1)
        )

        with patch("time.sleep"):
            success, tx_hash, receipt = executor.execute_with_retry(
                "0xSafe", mock_safe_tx, ["key1"]
            )

        assert success is True
        assert mock_safe_tx.execute.call_count == 3
        assert SAFE_TX_STATS["gs013_inner_revert_retries"] == 2


def test_gs013_followed_by_different_error(
    executor, mock_chain_interface, mock_safe_tx, mock_safe
):
    """GS013 followed by a non-retryable error should abort on the second error."""
    with patch.object(executor, "_recreate_safe_client", return_value=mock_safe):
        # Simulation: GS013 first, then a signature error (non-retryable)
        mock_safe_tx.call.side_effect = [
            ValueError("execution reverted: GS013"),
            ValueError("execution reverted: GS026"),
        ]

        with patch("time.sleep"):
            success, error, _ = executor.execute_with_retry(
                "0xSafe", mock_safe_tx, ["key1"]
            )

        assert success is False
        assert "GS026" in error
        assert mock_safe_tx.call.call_count == 2
        assert SAFE_TX_STATS["signature_errors"] >= 1


def test_gs013_stats_counter_increments_each_retry(
    executor, mock_chain_interface, mock_safe_tx, mock_safe
):
    """gs013_inner_revert_retries counter should increment exactly once per GS013 retry."""
    executor.max_retries = 4
    with patch.object(executor, "_recreate_safe_client", return_value=mock_safe):
        mock_safe_tx.call.return_value = None
        # Execute always raises GS013
        mock_safe_tx.execute.side_effect = ValueError("execution reverted: GS013")

        with patch("time.sleep"):
            success, error, _ = executor.execute_with_retry(
                "0xSafe", mock_safe_tx, ["key1"]
            )

        assert success is False
        # 5 attempts total (0..4), _handle_execution_failure called each time.
        # The last attempt also goes through _handle_execution_failure but
        # GS013 branch returns should_retry=True before the max-retries check,
        # so all 5 are counted.
        assert SAFE_TX_STATS["gs013_inner_revert_retries"] == 5


def test_gs013_classification_does_not_set_signature_error(executor):
    """GS013 must not be classified as a signature error."""
    error = ValueError("execution reverted: GS013")
    result = executor._classify_error(error)
    assert result["is_gs013_inner_revert"] is True
    assert result["is_signature_error"] is False
    assert result["is_insufficient_funds"] is False


def test_gs013_permanent_simulation_exhausts_all_retries(
    executor, mock_chain_interface, mock_safe_tx, mock_safe
):
    """Permanent GS013 in simulation should exhaust max_retries+1 attempts."""
    executor.max_retries = 3
    with patch.object(executor, "_recreate_safe_client", return_value=mock_safe):
        mock_safe_tx.call.side_effect = ValueError("execution reverted: GS013")

        with patch("time.sleep"):
            success, error, _ = executor.execute_with_retry(
                "0xSafe", mock_safe_tx, ["key1"]
            )

        assert success is False
        assert "GS013" in error
        # Should attempt exactly max_retries + 1 times
        assert mock_safe_tx.call.call_count == 4


# =============================================================================
# Test: Revert data extraction (_extract_revert_hex)
# =============================================================================


def test_extract_revert_hex_from_data_attribute_str(executor):
    """Extract hex from exception .data attribute (string)."""
    error = ValueError("some error")
    error.data = "0x08c379a0000000000000000000000000000000000000000000000000"
    result = SafeTransactionExecutor._extract_revert_hex(error)
    assert result == error.data


def test_extract_revert_hex_from_data_attribute_bytes(executor):
    """Extract hex from exception .data attribute (bytes)."""
    error = ValueError("some error")
    error.data = bytes.fromhex("08c379a0000000000000000000000000")
    result = SafeTransactionExecutor._extract_revert_hex(error)
    assert result == "0x08c379a0000000000000000000000000"


def test_extract_revert_hex_from_args_hex_string(executor):
    """Extract hex from exception args containing hex string."""
    error = ValueError("execution reverted", "0xdeadbeef12345678")
    result = SafeTransactionExecutor._extract_revert_hex(error)
    assert result == "0xdeadbeef12345678"


def test_extract_revert_hex_from_args_bytes(executor):
    """Extract hex from exception args containing raw bytes."""
    raw = bytes.fromhex("deadbeef12345678")
    error = ValueError(raw)
    result = SafeTransactionExecutor._extract_revert_hex(error)
    assert result == "0xdeadbeef12345678"


def test_extract_revert_hex_from_args_dict_data(executor):
    """Extract hex from exception args containing dict with 'data' key."""
    error = ValueError({"code": -32000, "data": "0xabcdef0012345678"})
    result = SafeTransactionExecutor._extract_revert_hex(error)
    assert result == "0xabcdef0012345678"


def test_extract_revert_hex_fallback_str_regex(executor):
    """Fallback: extract hex via regex on str(error)."""
    error = ValueError("execution reverted: 0x08c379a0aabbccdd")
    result = SafeTransactionExecutor._extract_revert_hex(error)
    assert result == "0x08c379a0aabbccdd"


def test_extract_revert_hex_none_when_no_hex(executor):
    """Return None when no hex data is available anywhere."""
    error = ValueError("Some generic error without hex")
    result = SafeTransactionExecutor._extract_revert_hex(error)
    assert result is None


def test_decode_revert_reason_uses_data_attribute(executor):
    """_decode_revert_reason should find data in .data attribute."""
    error = ValueError("execution reverted")
    error.data = "0xdeadbeef12345678"

    with patch("iwa.core.services.safe_executor.ErrorDecoder") as mock_decoder:
        mock_decoder.return_value.decode.return_value = [
            ("ServiceNotStaked", "ServiceNotStaked()", "staking.json")
        ]
        result = executor._decode_revert_reason(error)

    assert result == "ServiceNotStaked() (from staking.json)"
    mock_decoder.return_value.decode.assert_called_once_with("0xdeadbeef12345678")


def test_decode_revert_reason_logs_on_decoder_failure(executor):
    """_decode_revert_reason should log at debug level when decoder raises."""
    error = ValueError("execution reverted")
    error.data = "0xdeadbeef12345678"

    with patch("iwa.core.services.safe_executor.ErrorDecoder") as mock_decoder:
        mock_decoder.return_value.decode.side_effect = RuntimeError("decode boom")
        result = executor._decode_revert_reason(error)

    assert result is None


def test_handle_failure_gs013_retries_with_decoded_reason(
    executor, mock_chain_interface, mock_safe_tx, mock_safe
):
    """GS013 retry log should include decoded revert reason when available."""
    error = ValueError("execution reverted: GS013")
    error.data = "0xdeadbeef12345678"

    with (
        patch.object(
            executor,
            "_decode_revert_reason",
            return_value="ServiceNotStaked() (from staking.json)",
        ) as mock_decode,
        patch.object(executor, "_recreate_safe_client", return_value=mock_safe),
        patch.object(executor, "_diagnose_inner_revert"),
    ):
        updated_tx, should_retry, _is_fee = executor._handle_execution_failure(
            error, "0xSafe", mock_safe_tx, ["key1"], 0, "test_op"
        )

    assert should_retry is True
    mock_decode.assert_called_once_with(error)
    assert SAFE_TX_STATS["gs013_inner_revert_retries"] == 1


def test_extract_revert_hex_from_data_attribute_dict(executor):
    """Extract hex from exception .data attribute when it's a dict with nested 'data' key."""
    error = ValueError("some error")
    error.data = {"code": -32000, "data": "0x08c379a0000000000000000000000000"}
    result = SafeTransactionExecutor._extract_revert_hex(error)
    assert result == "0x08c379a0000000000000000000000000"


def test_max_retries_exhausted_includes_decoded_reason(
    executor, mock_chain_interface, mock_safe_tx, mock_safe
):
    """Max-retries-exhausted log should include decoded revert reason."""
    error = ValueError("execution reverted: some unknown error")
    error.data = "0xdeadbeef12345678"

    with (
        patch.object(
            executor,
            "_decode_revert_reason",
            return_value="CustomError() (from contract.json)",
        ) as mock_decode,
        patch.object(executor, "_recreate_safe_client", return_value=mock_safe),
    ):
        # Set attempt = max_retries to trigger the exhausted path
        updated_tx, should_retry, _is_fee = executor._handle_execution_failure(
            error, "0xSafe", mock_safe_tx, ["key1"], executor.max_retries, "test_op"
        )

    assert should_retry is False
    mock_decode.assert_called_once_with(error)


# --- Security: _sanitize_error and _extract_revert_hex URL protection ---


def test_sanitize_error_strips_rpc_api_keys(executor):
    """_sanitize_error should redact API keys from RPC URLs in error messages."""
    # Realistic hex API key in URL path (32 hex chars)
    api_key = "ab1c2d3e4f5a6b7c8d9e0f1a2b3c4d5e"  # gitleaks:allow
    error = ConnectionError(
        f"HTTPSConnectionPool(host='gnosis-mainnet.rpc.blastapi.io'): "
        f"request to https://gnosis-mainnet.rpc.blastapi.io/{api_key} failed"
    )
    result = executor._sanitize_error(error)
    # The 32+ hex-char path segment should be redacted
    assert api_key not in result
    assert "***" in result


def test_sanitize_error_preserves_safe_error_codes(executor):
    """_sanitize_error should preserve Safe error codes like GS013."""
    error = ValueError("execution reverted: GS013")
    result = executor._sanitize_error(error)
    assert "GS013" in result


def test_extract_revert_hex_skips_url_path_hex(executor):
    """_extract_revert_hex should NOT match hex segments in URLs."""
    # Error message containing a hex API key in URL path
    error = ValueError(
        "Connection failed: https://rpc.example.com/0xABCDEF1234567890ABCDEF1234567890"
    )
    # Clear other extraction paths
    assert not hasattr(error, "data")
    result = SafeTransactionExecutor._extract_revert_hex(error)
    # Should NOT match the hex in the URL path (preceded by '/')
    assert result is None


def test_extract_revert_hex_matches_standalone_hex(executor):
    """_extract_revert_hex should match standalone 0x hex data in error messages."""
    error = ValueError("execution reverted 0x08c379a0deadbeef")
    result = SafeTransactionExecutor._extract_revert_hex(error)
    assert result == "0x08c379a0deadbeef"


def test_gs013_triggers_rpc_rotation(executor, mock_chain_interface, mock_safe_tx, mock_safe):
    """GS013 must call _handle_rpc_error to rotate away from the stale node.

    Root cause: GS013 from Gnosis RPC is a stale-state error from the provider,
    not a real contract failure.  Rotating immediately lets the next attempt hit
    a fresh node instead of waiting through exponential backoff (up to 63s).
    """
    with patch.object(executor, "_recreate_safe_client", return_value=mock_safe):
        mock_safe_tx.call.side_effect = ValueError("execution reverted: GS013")

        with patch("time.sleep"):
            executor.execute_with_retry("0xSafe", mock_safe_tx, ["key1"])

    # _handle_rpc_error must have been called at least once to rotate the RPC
    assert mock_chain_interface._handle_rpc_error.call_count >= 1
    assert SAFE_TX_STATS["rpc_rotations"] >= 1


def test_gs013_rpc_rotation_counted_separately_from_plain_rpc_errors(
    executor, mock_chain_interface, mock_safe_tx, mock_safe
):
    """GS013 rotations are tracked in rpc_rotations counter, not only on is_rpc_error."""
    initial_rotations = SAFE_TX_STATS["rpc_rotations"]
    with patch.object(executor, "_recreate_safe_client", return_value=mock_safe):
        mock_safe_tx.call.side_effect = [
            ValueError("execution reverted: GS013"),
            None,  # succeeds on next attempt
        ]
        mock_safe_tx.execute.return_value = {"transactionHash": b"\x01" * 32}
        mock_chain_interface.web3.eth.wait_for_transaction_receipt.return_value = (
            MagicMock(status=1)
        )

        with patch("time.sleep"):
            success, _, _ = executor.execute_with_retry("0xSafe", mock_safe_tx, ["key1"])

    assert success is True
    assert SAFE_TX_STATS["rpc_rotations"] > initial_rotations
