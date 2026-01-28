"""Integration tests for SafeTransactionExecutor using REAL SafeTx class.

These tests do NOT mock SafeTx methods. They use the real SafeTx class from safe-eth-py
to ensure that we correctly handle its internal state changes (like signature clearing).
We only mock the EthereumClient/w3 layer to avoid actual network calls.
"""

from unittest.mock import MagicMock, patch

import pytest
from hexbytes import HexBytes
from safe_eth.eth import EthereumClient
from safe_eth.safe.safe_tx import SafeTx

from iwa.core.services.safe_executor import SafeTransactionExecutor

# Valid 65-byte mock signature
MOCK_SIGNATURE = b"x" * 65
MOCK_TX_HASH = HexBytes("0x" + "a" * 64)


@pytest.fixture
def mock_chain_interface():
    ci = MagicMock()
    ci.current_rpc = "http://mock-rpc"
    ci.DEFAULT_MAX_RETRIES = 6
    ci._is_rate_limit_error.return_value = False
    ci._is_connection_error.return_value = False
    ci._handle_rpc_error.return_value = {"should_retry": True}

    # Needs a web3 instance
    ci.web3 = MagicMock()
    return ci


@pytest.fixture
def real_safe_tx_mock_eth(mock_chain_interface):
    """Create a REAL SafeTx object but with mocked EthereumClient."""

    # 1. Setup Mock EthereumClient
    mock_eth_client = MagicMock(spec=EthereumClient)
    mock_eth_client.w3 = mock_chain_interface.web3

    # 2. Setup Mock Contract for SafeTx internals
    # SafeTx calls get_safe_contract(self.w3, address)
    # We need to mock the contract function calls to avoid errors
    mock_contract = MagicMock()
    # Mock execTransaction function build_transaction
    mock_contract.functions.execTransaction.return_value.build_transaction.return_value = {
        "to": "0xSafe",
        "data": b"",
        "value": 0,
        "gas": 500000,
        "nonce": 5,
        "from": "0xExecutor",
    }
    # Mock nonce call
    mock_contract.functions.nonce().call.return_value = 5
    # Mock VERSION call
    mock_contract.functions.VERSION().call.return_value = "1.3.0"

    # We must patch get_safe_contract to return our mock
    # because SafeTx uses it internally via @cached_property
    with patch("safe_eth.safe.safe_tx.get_safe_contract", return_value=mock_contract):
        safe_tx = SafeTx(
            mock_eth_client,
            "0xSafeAddress",
            "0xTo",
            0,
            b"",
            0,
            200000,  # safe_tx_gas
            0,
            0,
            None,
            None,
            signatures=MOCK_SIGNATURE,
            safe_nonce=5,
            chain_id=1,
        )

        # HACK: Force initialize properties that rely on cached_property + network
        # safe_tx.contract calls get_safe_contract (mocked above)
        _ = safe_tx.contract

        yield safe_tx, mock_eth_client


def test_integration_full_execution_flow(mock_chain_interface, real_safe_tx_mock_eth):
    """
    Test execution flow using REAL SafeTx.
    This verifies that our executor handles the SafeTx.execute() side-effects (clearing signatures).
    """
    safe_tx, mock_eth_client = real_safe_tx_mock_eth
    executor = SafeTransactionExecutor(mock_chain_interface)

    # Setup successful broadcast mock
    mock_eth_client.send_unsigned_transaction.return_value = MOCK_TX_HASH
    mock_chain_interface.web3.eth.wait_for_transaction_receipt.return_value = MagicMock(status=1)

    # Use a dummy key (needs to be valid hex for account generation if SafeTx uses it)
    dummy_key = "0x" + "1" * 64

    with patch.object(executor, "_recreate_safe_client", return_value=MagicMock()):
        # Pre-execution check
        assert len(safe_tx.signatures) == 65

        success, tx_hash, receipt = executor.execute_with_retry("0xSafe", safe_tx, [dummy_key])

        assert success is True
        assert tx_hash == "0x" + MOCK_TX_HASH.hex()

        # VITAL CHECK: Signatures must be present after execution!
        # If backup/restore logic isn't working, this will fail because SafeTx clears them.
        assert len(safe_tx.signatures) == 65
        assert safe_tx.signatures == MOCK_SIGNATURE


def test_integration_retry_preserves_signatures(mock_chain_interface, real_safe_tx_mock_eth):
    """
    Test retry flow with REAL SafeTx.
    Simulate:
    1. Exec -> SafeTx clears sigs -> Network sends
    2. Wait -> Timeout (failure)
    3. Retry -> Exec again (Needs sigs!) -> Success
    """
    safe_tx, mock_eth_client = real_safe_tx_mock_eth
    executor = SafeTransactionExecutor(mock_chain_interface)

    # Setup mocks
    mock_eth_client.send_unsigned_transaction.return_value = MOCK_TX_HASH

    # First attempt: Transaction not found (Timeout)
    # Second attempt: Success (status 1)
    mock_chain_interface.web3.eth.wait_for_transaction_receipt.side_effect = [
        ValueError("Transaction not found"),
        MagicMock(status=1),
    ]

    dummy_key = "0x" + "1" * 64

    with patch.object(executor, "_recreate_safe_client", return_value=MagicMock()):
        with patch("time.sleep"):  # Skip sleep
            success, tx_hash, receipt = executor.execute_with_retry("0xSafe", safe_tx, [dummy_key])

    assert success is True

    # Verify we actually called send twice (retry happened)
    assert mock_eth_client.send_unsigned_transaction.call_count == 2

    # Verify signatures preserved at the end
    assert len(safe_tx.signatures) == 65
    assert safe_tx.signatures == MOCK_SIGNATURE
