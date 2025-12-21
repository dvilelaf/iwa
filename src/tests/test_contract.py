from pathlib import Path
from unittest.mock import MagicMock, mock_open, patch

import pytest
from web3.exceptions import ContractCustomError

from iwa.core.contracts.contract import ContractInstance


@pytest.fixture
def mock_chain_interface():
    with patch("iwa.core.contracts.contract.ChainInterfaces") as mock:
        mock_ci = mock.return_value.get.return_value
        mock_ci.web3.eth.contract.return_value = MagicMock()
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
