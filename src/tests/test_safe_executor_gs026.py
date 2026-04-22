"""Tests for GS026 parallel nonce race handling in SafeTransactionExecutor.

These tests cover the fix for a race between NonceAllocator-pre-assigned
nonces and the safe_tx.call() simulation in parallel-nonce mode.

When a worker holds nonce N+1 but the predecessor TX with nonce N hasn't
mined yet, the Safe's signature check reads the wrong tx hash and the RPC
returns a GS026 revert encoded as raw hex (`0x...4753303236`).  The fix:
decode the hex before classifying the error, and when allow_nonce_refresh
is False (pre-assigned nonce), treat GS026 as a transient race rather
than a permanent signature failure — retry with a short fixed delay.
"""

import time
from unittest.mock import MagicMock, patch

import pytest
from safe_eth.safe.safe_tx import SafeTx

from iwa.core.services.safe_executor import (
    PARALLEL_NONCE_RACE_RETRY_DELAY,
    SAFE_TX_STATS,
    SafeTransactionExecutor,
)

# Real hex-encoded GS026 revert reason observed on Gnosis RPC:
#   0x08c379a0                                                         # Error(string) selector
#   00000000000000000000000000000000000000000000000000000000000000020 # offset
#   00000000000000000000000000000000000000000000000000000000000000005 # length = 5
#   4753303236000000000000000000000000000000000000000000000000000000  # "GS026" + padding
GS026_HEX = (
    "0x08c379a0"
    "0000000000000000000000000000000000000000000000000000000000000020"
    "0000000000000000000000000000000000000000000000000000000000000005"
    "4753303236000000000000000000000000000000000000000000000000000000"
)

# Same structure, "GS025" instead of "GS026"
GS025_HEX = (
    "0x08c379a0"
    "0000000000000000000000000000000000000000000000000000000000000020"
    "0000000000000000000000000000000000000000000000000000000000000005"
    "4753303235000000000000000000000000000000000000000000000000000000"
)

# "GS020" hex — wrong signer, not a race condition
GS020_HEX = (
    "0x08c379a0"
    "0000000000000000000000000000000000000000000000000000000000000020"
    "0000000000000000000000000000000000000000000000000000000000000005"
    "4753303230000000000000000000000000000000000000000000000000000000"
)

# "GS024" hex — wrong threshold, not a race condition
GS024_HEX = (
    "0x08c379a0"
    "0000000000000000000000000000000000000000000000000000000000000020"
    "0000000000000000000000000000000000000000000000000000000000000005"
    "4753303234000000000000000000000000000000000000000000000000000000"
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
    tx.gas_token = "0x0000000000000000000000000000000000000000"
    tx.refund_receiver = "0x0000000000000000000000000000000000000000"
    tx.to = "0xTo"
    tx.value = 0
    tx.data = b""
    tx.operation = 0
    tx.signatures = b"x" * 65
    return tx


@pytest.fixture
def mock_safe():
    s = MagicMock()
    s.estimate_tx_gas.return_value = 100000
    s.retrieve_nonce.return_value = 5
    return s


def _make_hex_revert_error(hex_data: str) -> ValueError:
    """Build an RPC revert error whose only GS0xx signal is hex-encoded.

    Matches the shape observed from web3's execution-reverted errors:
    a ValueError with two args — a human-readable prefix and the raw
    hex revert data.  The prefix intentionally does NOT contain the
    GS0xx code, so classification must decode the hex to detect it.
    """
    return ValueError("execution reverted", hex_data)


# =============================================================================
# Test 1: hex-encoded GS026 is recognized as a signature error
# =============================================================================


def test_is_signature_error_with_hex_gs026(executor):
    """_is_signature_error must decode hex revert data to detect GS026.

    Reproduces the production observation: the error arrives as raw hex
    (`0x08c379a0...4753303236`) with no textual 'GS026' anywhere.  Without
    hex decoding the classifier would miss it and fall into the generic
    retry path with exponential backoff.
    """
    error = _make_hex_revert_error(GS026_HEX)
    # Sanity check: textual form does NOT contain "gs026"
    assert "gs026" not in str(error).lower()
    # Classifier must still detect it via hex decode
    assert executor._is_signature_error(error) is True


# =============================================================================
# Test 2: GS026 with pre-assigned nonce uses fast retry (not exponential)
# =============================================================================


def test_gs026_with_pre_assigned_nonce_uses_fast_retry(
    executor, mock_chain_interface, mock_safe_tx, mock_safe
):
    """allow_nonce_refresh=False + GS026-hex → 1s fixed retry, then success.

    Disambiguates from exponential backoff by asserting the race counter,
    not just the delay value (at attempt=0 both paths coincide at 1s).
    """
    recorded_delays: list[float] = []

    def record_sleep(delay):
        recorded_delays.append(delay)

    with patch.object(executor, "_recreate_safe_client", return_value=mock_safe):
        # 1st simulation fails with GS026-hex, 2nd succeeds.
        mock_safe_tx.call.side_effect = [
            _make_hex_revert_error(GS026_HEX),
            None,
        ]
        mock_safe_tx.execute.return_value = b"tx_hash"
        mock_chain_interface.web3.eth.wait_for_transaction_receipt.return_value = (
            MagicMock(status=1)
        )

        with patch("time.sleep", side_effect=record_sleep):
            success, tx_hash, _ = executor.execute_with_retry(
                "0xSafe",
                mock_safe_tx,
                ["key1"],
                allow_nonce_refresh=False,
            )

    assert success is True
    # Exactly one retry delay recorded after the failed first attempt.
    assert len(recorded_delays) == 1
    assert recorded_delays[0] == PARALLEL_NONCE_RACE_RETRY_DELAY
    # The race counter proves the fast-retry branch was taken, not exponential.
    assert SAFE_TX_STATS["parallel_nonce_races"] == 1
    assert SAFE_TX_STATS["parallel_nonce_race_retries"] == 1


def test_gs026_parallel_nonce_uses_fast_retry_on_later_attempt(
    executor, mock_chain_interface, mock_safe_tx, mock_safe
):
    """At attempt=2 the exponential path would be ~4s; race path must stay 1s.

    This is the load-bearing assertion: when attempt >= 1 the exponential
    backoff is >= 2s, so a delay of exactly PARALLEL_NONCE_RACE_RETRY_DELAY
    (1s) proves the fast-retry branch was taken rather than the generic
    exponential path.
    """
    recorded_delays: list[float] = []

    with patch.object(executor, "_recreate_safe_client", return_value=mock_safe):
        # Fail twice with GS026-hex (forces us past the exponential-1s
        # attempt=0 ambiguity), then succeed.
        mock_safe_tx.call.side_effect = [
            _make_hex_revert_error(GS026_HEX),
            _make_hex_revert_error(GS026_HEX),
            _make_hex_revert_error(GS026_HEX),
            None,
        ]
        mock_safe_tx.execute.return_value = b"tx_hash"
        mock_chain_interface.web3.eth.wait_for_transaction_receipt.return_value = (
            MagicMock(status=1)
        )

        with patch("time.sleep", side_effect=recorded_delays.append):
            success, _, _ = executor.execute_with_retry(
                "0xSafe",
                mock_safe_tx,
                ["key1"],
                allow_nonce_refresh=False,
            )

    assert success is True
    # Three failed attempts → three retry delays, all must be the fast delay.
    # The exponential path would have produced 1s, 2s, 4s — the fast-retry
    # path produces 1s, 1s, 1s.
    assert recorded_delays == [
        PARALLEL_NONCE_RACE_RETRY_DELAY,
        PARALLEL_NONCE_RACE_RETRY_DELAY,
        PARALLEL_NONCE_RACE_RETRY_DELAY,
    ]


# =============================================================================
# Test 3: GS026 with auto-nonce still aborts (regression guard)
# =============================================================================


def test_gs026_with_auto_nonce_still_aborts(
    executor, mock_chain_interface, mock_safe_tx, mock_safe
):
    """With allow_nonce_refresh=True (default), GS026 is a real signature error.

    The parallel-nonce-race escape hatch must only engage when the caller
    explicitly signals pre-assigned nonces.  Otherwise GS026 remains a
    permanent signer-mismatch and must abort after exactly one attempt.
    """
    with patch.object(executor, "_recreate_safe_client", return_value=mock_safe):
        mock_safe_tx.call.side_effect = _make_hex_revert_error(GS026_HEX)

        with patch("time.sleep") as mock_sleep:
            success, error, _ = executor.execute_with_retry(
                "0xSafe",
                mock_safe_tx,
                ["key1"],
                allow_nonce_refresh=True,
            )

    assert success is False
    # Exactly one simulation attempt — no retry.
    assert mock_safe_tx.call.call_count == 1
    mock_sleep.assert_not_called()
    # Classified as signature error, counted as such.
    assert SAFE_TX_STATS["signature_errors"] >= 1
    assert SAFE_TX_STATS["parallel_nonce_races"] == 0


# =============================================================================
# Test 4: hex-encoded GS025 is recognized as a nonce error
# =============================================================================


def test_is_nonce_error_with_hex_gs025(executor):
    """_is_nonce_error must decode hex revert data to detect GS025.

    Same mechanism as GS026: when the RPC returns the revert reason as
    raw ABI-encoded Error(string) bytes, the word "GS025" only appears
    inside the hex payload.
    """
    error = _make_hex_revert_error(GS025_HEX)
    assert "gs025" not in str(error).lower()
    assert "nonce" not in str(error).lower()
    assert executor._is_nonce_error(error) is True


# =============================================================================
# Test 5: parallel nonce race stats incremented
# =============================================================================


def test_parallel_nonce_race_stats_incremented(
    executor, mock_chain_interface, mock_safe_tx, mock_safe
):
    """parallel_nonce_races + parallel_nonce_race_retries counters increment.

    - parallel_nonce_races: bumped once per detection in _execute_attempt
    - parallel_nonce_race_retries: bumped once per fast-retry decision
    """
    with patch.object(executor, "_recreate_safe_client", return_value=mock_safe):
        mock_safe_tx.call.side_effect = [
            _make_hex_revert_error(GS026_HEX),
            None,
        ]
        mock_safe_tx.execute.return_value = b"tx_hash"
        mock_chain_interface.web3.eth.wait_for_transaction_receipt.return_value = (
            MagicMock(status=1)
        )

        with patch("time.sleep"):
            success, _, _ = executor.execute_with_retry(
                "0xSafe",
                mock_safe_tx,
                ["key1"],
                allow_nonce_refresh=False,
            )

    assert success is True
    assert SAFE_TX_STATS["parallel_nonce_races"] == 1
    assert SAFE_TX_STATS["parallel_nonce_race_retries"] == 1
    assert SAFE_TX_STATS["parallel_nonce_races_exhausted"] == 0


# =============================================================================
# Test 6: parallel nonce race exhausted stats
# =============================================================================


def test_parallel_nonce_race_exhausted_stats(
    executor, mock_chain_interface, mock_safe_tx, mock_safe
):
    """When retries are exhausted, parallel_nonce_races_exhausted increments.

    Also verifies that parallel_nonce_races is bumped once per attempt
    (each simulation that hits the race) and parallel_nonce_race_retries
    is bumped once per retry decision (max_retries times,
    since the final attempt doesn't retry further).
    """
    executor.max_retries = 2  # 3 total attempts (0, 1, 2)

    with patch.object(executor, "_recreate_safe_client", return_value=mock_safe):
        # Every simulation hits the race — race never clears.
        mock_safe_tx.call.side_effect = _make_hex_revert_error(GS026_HEX)

        with patch("time.sleep"):
            success, _, _ = executor.execute_with_retry(
                "0xSafe",
                mock_safe_tx,
                ["key1"],
                allow_nonce_refresh=False,
            )

    assert success is False
    # 3 attempts total; each counts as one detected race.
    assert SAFE_TX_STATS["parallel_nonce_races"] == 3
    # First 2 attempts retry; last attempt hits the exhausted branch.
    assert SAFE_TX_STATS["parallel_nonce_race_retries"] == 2
    assert SAFE_TX_STATS["parallel_nonce_races_exhausted"] == 1


# =============================================================================
# Test 7: classify_error surfaces is_parallel_nonce_race only when allowed
# =============================================================================


def test_classify_error_parallel_nonce_race_only_when_pre_assigned(executor):
    """is_parallel_nonce_race requires allow_nonce_refresh=False.

    With allow_nonce_refresh=True the flag must stay False, so the normal
    signature-error abort path kicks in.  With allow_nonce_refresh=False
    the flag must be True for GS026 and False for unrelated errors.
    """
    gs026 = _make_hex_revert_error(GS026_HEX)

    # With refresh allowed → treated as a normal signature error, not a race.
    c_allowed = executor._classify_error(gs026, allow_nonce_refresh=True)
    assert c_allowed["is_signature_error"] is True
    assert c_allowed["is_parallel_nonce_race"] is False

    # With refresh forbidden → race flag flips on, signature flag is cleared.
    c_forbidden = executor._classify_error(gs026, allow_nonce_refresh=False)
    assert c_forbidden["is_parallel_nonce_race"] is True
    assert c_forbidden["is_signature_error"] is False  # mutual exclusivity

    # Non-GS026 revert with refresh forbidden → race flag stays off.
    other = ValueError("execution reverted: GS020")
    c_other = executor._classify_error(other, allow_nonce_refresh=False)
    assert c_other["is_parallel_nonce_race"] is False


# =============================================================================
# Test 8: GS020/GS024 hex with pre-assigned nonce still aborts (not a race)
# =============================================================================


def test_gs020_hex_with_pre_assigned_nonce_aborts(
    executor, mock_chain_interface, mock_safe_tx, mock_safe
):
    """Hex-encoded GS020 (wrong signer) must abort even with allow_nonce_refresh=False.

    Only GS026 is a parallel-nonce race indicator.  GS020 (owner not found)
    means the signing key is genuinely wrong — retrying won't help.
    """
    with patch.object(executor, "_recreate_safe_client", return_value=mock_safe):
        mock_safe_tx.call.side_effect = _make_hex_revert_error(GS020_HEX)

        with patch("time.sleep") as mock_sleep:
            success, _, _ = executor.execute_with_retry(
                "0xSafe",
                mock_safe_tx,
                ["key1"],
                allow_nonce_refresh=False,
            )

    assert success is False
    assert mock_safe_tx.call.call_count == 1
    mock_sleep.assert_not_called()
    assert SAFE_TX_STATS["signature_errors"] >= 1
    assert SAFE_TX_STATS["parallel_nonce_races"] == 0


def test_gs024_hex_with_pre_assigned_nonce_aborts(
    executor, mock_chain_interface, mock_safe_tx, mock_safe
):
    """Hex-encoded GS024 (threshold not reached) must abort with pre-assigned nonce.

    GS024 is a permanent signature-set failure — not a nonce race.
    """
    with patch.object(executor, "_recreate_safe_client", return_value=mock_safe):
        mock_safe_tx.call.side_effect = _make_hex_revert_error(GS024_HEX)

        with patch("time.sleep") as mock_sleep:
            success, _, _ = executor.execute_with_retry(
                "0xSafe",
                mock_safe_tx,
                ["key1"],
                allow_nonce_refresh=False,
            )

    assert success is False
    assert mock_safe_tx.call.call_count == 1
    mock_sleep.assert_not_called()
    assert SAFE_TX_STATS["parallel_nonce_races"] == 0


# =============================================================================
# Test 9: real-wall-clock check (optional; proves the fast path is actually fast)
# =============================================================================


@pytest.mark.slow
def test_gs026_fast_retry_real_time(
    executor, mock_chain_interface, mock_safe_tx, mock_safe
):
    """Real-time wall-clock sanity check: fast retry path does not wait >= 2s.

    Uses real time.sleep but caps the simulated race to 1 retry so the test
    is bounded at ~1s.  Asserts total wall time < 1.8s, which fails if the
    executor falls back to exponential backoff (2s) on the 2nd attempt.
    """
    with patch.object(executor, "_recreate_safe_client", return_value=mock_safe):
        mock_safe_tx.call.side_effect = [
            _make_hex_revert_error(GS026_HEX),
            None,
        ]
        mock_safe_tx.execute.return_value = b"tx_hash"
        mock_chain_interface.web3.eth.wait_for_transaction_receipt.return_value = (
            MagicMock(status=1)
        )

        start = time.monotonic()
        success, _, _ = executor.execute_with_retry(
            "0xSafe",
            mock_safe_tx,
            ["key1"],
            allow_nonce_refresh=False,
        )
        elapsed = time.monotonic() - start

    assert success is True
    # Fast path sleeps exactly 1s.  Add generous slack for CI jitter.
    assert elapsed < 1.8, f"Expected <1.8s wall clock, got {elapsed:.2f}s"
