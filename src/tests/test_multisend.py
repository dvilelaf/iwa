from unittest.mock import patch

import pytest
from safe_eth.safe import SafeOperationEnum

from iwa.core.contracts.multisend import MultiSendCallOnlyContract, MultiSendContract


@pytest.fixture
def mock_contract_instance():
    with (
        patch("iwa.core.contracts.contract.ContractInstance.__init__", return_value=None),
        patch("iwa.core.contracts.contract.ContractInstance.call") as mock_call,
        patch("iwa.core.contracts.contract.ContractInstance.prepare_transaction") as mock_prep,
    ):
        yield mock_call, mock_prep


def test_encode_data():
    tx = {
        "operation": SafeOperationEnum.CALL,
        "to": "0x1111111111111111111111111111111111111111",
        "value": 100,
        "data": b"\x01\x02",
    }
    encoded = MultiSendCallOnlyContract.encode_data(tx)
    # Operation (1 byte) + To (20 bytes) + Value (32 bytes) + Data Length (32 bytes) + Data (2 bytes)
    # But wait, implementation uses HexBytes formatting which might produce different output if not careful.
    # Let's check length.
    # 1 + 20 + 32 + 32 + 2 = 87 bytes.
    assert len(encoded) == 87
    assert encoded[0] == 0  # CALL is 0


def test_to_bytes():
    tx1 = {
        "operation": SafeOperationEnum.CALL,
        "to": "0x1111111111111111111111111111111111111111",
        "value": 100,
        "data": b"\x01",
    }
    tx2 = {
        "operation": SafeOperationEnum.DELEGATE_CALL,
        "to": "0x2222222222222222222222222222222222222222",
        "value": 0,
        "data": b"",
    }
    encoded = MultiSendCallOnlyContract.to_bytes([tx1, tx2])
    # tx1: 1+20+32+32+1 = 86
    # tx2: 1+20+32+32+0 = 85
    # Total: 171
    assert len(encoded) == 171


def test_prepare_tx(mock_contract_instance):
    mock_call, mock_prep = mock_contract_instance
    mock_prep.return_value = {"data": "0x"}

    multisend = MultiSendCallOnlyContract("0xMulti", "gnosis")

    transactions = [
        {
            "operation": SafeOperationEnum.CALL,
            "to": "0x1111111111111111111111111111111111111111",
            "value": 100,
            "data": b"",
        }
    ]

    tx = multisend.prepare_tx("0xFrom", transactions)
    assert tx == {"data": "0x"}

    mock_prep.assert_called_once()
    call_args = mock_prep.call_args[1]
    assert call_args["method_name"] == "multiSend"
    assert "encoded_multisend_data" in call_args["method_kwargs"]
    assert call_args["tx_params"]["from"] == "0xFrom"
    assert call_args["tx_params"]["value"] == 100


def test_multisend_contract_init(mock_contract_instance):
    # Just verify it can be instantiated and has correct name
    ms = MultiSendContract("0xMulti", "gnosis")
    assert ms.name == "multisend"
