from pathlib import Path
from unittest.mock import MagicMock, mock_open, patch

import pytest
from web3.exceptions import ContractCustomError

from iwa.core.contracts.contract import ContractInstance, clear_abi_cache


@pytest.fixture(autouse=True)
def clean_abi_cache():
    """Clear global ABI cache before each test."""
    clear_abi_cache()
    yield
    clear_abi_cache()


@pytest.fixture
def mock_chain_interface():
    with patch("iwa.core.contracts.contract.ChainInterfaces") as mock:
        mock_ci = mock.return_value.get.return_value
        # contract.py now uses web3._web3.eth.contract directly for RPC rotation compatibility
        mock_ci.web3._web3.eth.contract.return_value = MagicMock()
        yield mock_ci


@pytest.fixture
def mock_abi_file():
    abi_content = '[{"type": "function", "name": "testFunc", "inputs": []}, {"type": "error", "name": "CustomError", "inputs": [{"type": "uint256", "name": "code"}]}, {"type": "event", "name": "TestEvent", "inputs": []}]'
    with patch("builtins.open", mock_open(read_data=abi_content)):
        yield


class MockContract(ContractInstance):
    name = "test_contract"
    abi_path = Path("test.json")


def test_init(mock_chain_interface, mock_abi_file):
    contract = MockContract("0xAddress", "gnosis")
    assert contract.address == "0xAddress"
    assert contract.abi is not None
    assert "0x" in str(contract.error_selectors.keys())  # Check if selector generated


def test_init_abi_dict(mock_chain_interface):
    abi_content = '{"abi": [{"type": "function", "name": "testFunc"}]}'
    with patch("builtins.open", mock_open(read_data=abi_content)):
        contract = MockContract("0xAddress", "gnosis")
        assert contract.abi == [{"type": "function", "name": "testFunc"}]


def test_call(mock_chain_interface, mock_abi_file):
    contract = MockContract("0xAddress", "gnosis")
    contract.contract.functions.testFunc.return_value.call.return_value = "result"
    # with_retry now wraps the call - make it execute the lambda
    mock_chain_interface.with_retry.side_effect = lambda fn, **kwargs: fn()
    assert contract.call("testFunc") == "result"


def test_prepare_transaction_success(mock_chain_interface, mock_abi_file):
    contract = MockContract("0xAddress", "gnosis")
    mock_chain_interface.calculate_transaction_params.return_value = {"gas": 100}
    contract.contract.functions.testFunc.return_value.build_transaction.return_value = {
        "data": "0x"
    }

    tx = contract.prepare_transaction("testFunc", {}, {})
    assert tx == {"data": "0x"}


def test_prepare_transaction_custom_error_known(mock_chain_interface, mock_abi_file):
    contract = MockContract("0xAddress", "gnosis")
    # Selector for CustomError(uint256)
    # We need to calculate it or capture what load_error_selectors produced
    selector = list(contract.error_selectors.keys())[0]  # 0x...
    # Encode args: uint256(123)
    encoded_args = "0" * 62 + "7b"  # 123 hex
    error_data = f"{selector}{encoded_args}"

    contract.contract.functions.testFunc.return_value.build_transaction.side_effect = (
        ContractCustomError(error_data)
    )

    # Now the function returns None and logs the error instead of raising
    with patch("iwa.core.contracts.contract.logger") as mock_logger:
        result = contract.prepare_transaction("testFunc", {}, {})
        assert result is None
        # Verify error was logged
        mock_logger.error.assert_called()


def test_prepare_transaction_custom_error_unknown(mock_chain_interface, mock_abi_file):
    contract = MockContract("0xAddress", "gnosis")
    error_data = "0x12345678"  # Unknown selector

    contract.contract.functions.testFunc.return_value.build_transaction.side_effect = (
        ContractCustomError(error_data)
    )

    # Now the function returns None and logs the error instead of raising
    with patch("iwa.core.contracts.contract.logger") as mock_logger:
        result = contract.prepare_transaction("testFunc", {}, {})
        assert result is None
        # Verify error was logged
        mock_logger.error.assert_called()


def test_prepare_transaction_revert_string(mock_chain_interface, mock_abi_file):
    contract = MockContract("0xAddress", "gnosis")
    # Encoded Error(string) with "Error" as the message
    encoded_error = "0x08c379a0000000000000000000000000000000000000000000000000000000000000002000000000000000000000000000000000000000000000000000000000000000054572726f72000000000000000000000000000000000000000000000000000000"
    e = Exception("msg", encoded_error)

    contract.contract.functions.testFunc.return_value.build_transaction.side_effect = e

    with patch("iwa.core.contracts.contract.logger") as mock_logger:
        tx = contract.prepare_transaction("testFunc", {}, {})
        assert tx is None
        # Should log the decoded error
        mock_logger.error.assert_called()


def test_prepare_transaction_other_exception(mock_chain_interface, mock_abi_file):
    contract = MockContract("0xAddress", "gnosis")
    # The code expects e.args[1] to exist, so we must provide it
    e = Exception("Generic Error", "Some Data")
    contract.contract.functions.testFunc.return_value.build_transaction.side_effect = e

    with patch("iwa.core.contracts.contract.logger") as mock_logger:
        tx = contract.prepare_transaction("testFunc", {}, {})
        assert tx is None
        mock_logger.error.assert_called()


def test_extract_events(mock_chain_interface, mock_abi_file):
    contract = MockContract("0xAddress", "gnosis")
    receipt = MagicMock()

    # Mock event class and its process_receipt method
    mock_event_instance = MagicMock()

    # Create a log object that supports both ["event"] and .args
    mock_log = MagicMock()
    mock_log.__getitem__.side_effect = lambda key: "TestEvent" if key == "event" else None
    mock_log.args = {"arg1": 1}

    mock_event_instance.process_receipt.return_value = [mock_log]
    mock_event_class = MagicMock(return_value=mock_event_instance)

    # Mock contract.events dictionary-like access
    contract.contract.events = MagicMock()

    def get_event(name):
        if name == "TestEvent":
            return mock_event_class
        raise KeyError(name)

    contract.contract.events.__getitem__.side_effect = get_event

    # Explicitly set abi on the mock contract object
    contract.contract.abi = contract.abi

    events = contract.extract_events(receipt)
    assert len(events) == 1
    assert events[0]["name"] == "TestEvent"


def test_extract_events_edge_cases(mock_chain_interface):
    # Custom ABI with multiple event types to test different paths
    abi_content = '[{"type": "event", "name": "MissingEvent", "inputs": []}, {"type": "event", "name": "EmptyLogsEvent", "inputs": []}, {"type": "event", "name": "ErrorEvent", "inputs": []}, {"type": "function", "name": "NotAnEvent", "inputs": []}]'

    with patch("builtins.open", mock_open(read_data=abi_content)):
        contract = MockContract("0xAddress", "gnosis")

    receipt = MagicMock()

    # Mock contract.events
    contract.contract.events = MagicMock()

    # 1. MissingEvent: raises KeyError when accessed
    # 2. EmptyLogsEvent: returns empty list from process_receipt
    # 3. ErrorEvent: raises Exception from process_receipt

    mock_empty_logs_event = MagicMock()
    mock_empty_logs_event.return_value.process_receipt.return_value = []

    mock_error_event = MagicMock()
    mock_error_event.return_value.process_receipt.side_effect = Exception("Processing error")

    def get_event(name):
        if name == "MissingEvent":
            raise KeyError(name)
        if name == "EmptyLogsEvent":
            return mock_empty_logs_event
        if name == "ErrorEvent":
            return mock_error_event
        return MagicMock()

    contract.contract.events.__getitem__.side_effect = get_event

    # Explicitly set abi on the mock contract object
    contract.contract.abi = contract.abi

    events = contract.extract_events(receipt)
    assert len(events) == 0


# =============================================================================
# RPC ROTATION TESTS - Verify fix for contract.call() re-evaluating on retry
# =============================================================================


def test_call_reevaluates_contract_on_retry(mock_chain_interface, mock_abi_file):
    """Verify that self.contract is re-evaluated on each retry attempt.

    This test verifies the fix for the bug where the contract method was
    captured once outside the retry lambda, causing retries to use the
    stale provider after RPC rotation.
    """
    contract = MockContract("0xAddress", "gnosis")

    # Track how many times web3.eth.contract is called (proxy for contract property access)
    contract_creation_count = [0]

    def counting_contract_factory(address, abi):
        contract_creation_count[0] += 1
        mock = MagicMock()
        # First call fails, second succeeds
        if contract_creation_count[0] == 1:
            mock.functions.testFunc.return_value.call.side_effect = Exception(
                "429 Too Many Requests"
            )
        else:
            mock.functions.testFunc.return_value.call.return_value = "success"
        return mock

    mock_chain_interface.web3._web3.eth.contract.side_effect = counting_contract_factory

    # Implement with_retry that actually retries on 429
    def real_with_retry(fn, max_retries=6, operation_name="operation"):
        for attempt in range(max_retries + 1):
            try:
                return fn()
            except Exception as e:
                if "429" in str(e) and attempt < max_retries:
                    continue
                raise

    mock_chain_interface.with_retry.side_effect = real_with_retry

    # Execute - should fail first, then succeed
    result = contract.call("testFunc")

    assert result == "success"
    # KEY ASSERTION: contract property (and thus web3.eth.contract) should be called
    # once per attempt. With the fix, this should be 2. Before the fix, it would be 1.
    assert contract_creation_count[0] == 2, (
        f"Expected contract to be created 2 times (once per retry attempt), "
        f"but was created {contract_creation_count[0]} times. "
        "This suggests the fix for re-evaluating self.contract on retry is not working."
    )


def test_call_uses_fresh_provider_after_rotation(mock_chain_interface, mock_abi_file):
    """Verify that after RPC rotation, the contract uses the new provider.

    This simulates the scenario where:
    1. First call fails with 429
    2. RPC rotates to new provider
    3. Retry should use the NEW provider, not the old one
    """
    contract = MockContract("0xAddress", "gnosis")

    # Track which provider version is being used
    provider_versions = []
    current_provider_version = [1]  # Mutable to track version changes

    def mock_contract_factory(address, abi):
        mock = MagicMock()
        # Capture which provider version was used when this contract was created
        mock._provider_version = current_provider_version[0]
        provider_versions.append(current_provider_version[0])
        return mock

    mock_chain_interface.web3._web3.eth.contract.side_effect = mock_contract_factory

    # Simulate RPC rotation by incrementing provider version
    def simulate_rotation():
        current_provider_version[0] += 1
        return True

    mock_chain_interface.rotate_rpc = simulate_rotation

    # Make with_retry call rotation between attempts
    attempt_count = [0]

    def mock_with_retry(fn, **kwargs):
        attempt_count[0] += 1
        if attempt_count[0] == 1:
            # First attempt: simulate 429 then rotation
            simulate_rotation()
            # Call again after rotation
            return fn()
        return fn()

    mock_chain_interface.with_retry.side_effect = mock_with_retry

    # Execute call (this should access contract property, which creates new contract)
    contract.call("testFunc")

    # Verify: contract was created at least once with the rotated provider
    # If the fix works, the provider_versions list should show provider version 2
    # (because rotation happened before the successful call)
    assert len(provider_versions) >= 1
    # The last contract should have been created with the rotated provider
    assert provider_versions[-1] == 2, f"Expected provider version 2, got {provider_versions}"


def test_call_with_429_triggers_retry_with_new_contract(mock_chain_interface, mock_abi_file):
    """Integration test: 429 error should trigger retry which uses fresh contract.

    This test verifies the complete flow:
    1. Call fails with 429
    2. with_retry handles it and retries
    3. The retry uses a fresh contract instance (new provider)
    """
    contract = MockContract("0xAddress", "gnosis")

    # Create distinct mock contracts for each call
    mock_contract_1 = MagicMock()
    mock_contract_1.functions.testFunc.return_value.call.side_effect = Exception(
        "429 Too Many Requests"
    )

    mock_contract_2 = MagicMock()
    mock_contract_2.functions.testFunc.return_value.call.return_value = "success_from_rotated_rpc"

    contracts_returned = [mock_contract_1, mock_contract_2]
    contract_call_count = [0]

    def mock_contract_factory(address, abi):
        result = contracts_returned[min(contract_call_count[0], len(contracts_returned) - 1)]
        contract_call_count[0] += 1
        return result

    mock_chain_interface.web3._web3.eth.contract.side_effect = mock_contract_factory

    # Implement with_retry that actually retries
    def real_with_retry(fn, max_retries=6, operation_name="operation"):
        last_error = None
        for attempt in range(max_retries + 1):
            try:
                return fn()
            except Exception as e:
                last_error = e
                if "429" in str(e) and attempt < max_retries:
                    continue  # Retry
                raise
        raise last_error

    mock_chain_interface.with_retry.side_effect = real_with_retry

    # Execute - should succeed on second attempt with rotated RPC
    result = contract.call("testFunc")

    assert result == "success_from_rotated_rpc"
    # Verify we created 2 contract instances (one per attempt)
    assert contract_call_count[0] == 2, (
        f"Expected 2 contract creations, got {contract_call_count[0]}"
    )
