from unittest.mock import MagicMock, PropertyMock, patch

import pytest
from web3 import Web3

from iwa.core.monitor import EventMonitor


@pytest.fixture
def mock_chain_interfaces():
    with patch("iwa.core.monitor.ChainInterfaces") as mock:
        instance = mock.return_value
        gnosis_interface = MagicMock()
        gnosis_interface.chain.name = "Gnosis"
        gnosis_interface.chain.rpc = "https://rpc"
        gnosis_interface.web3 = MagicMock()
        instance.get.return_value = gnosis_interface
        yield instance


@pytest.fixture
def mock_callback():
    return MagicMock()


def test_monitor_init_success(mock_chain_interfaces, mock_callback):
    chain_interface = mock_chain_interfaces.get.return_value
    chain_interface.web3.eth.block_number = 100

    monitor = EventMonitor(["0x1234567890123456789012345678901234567890"], mock_callback)

    assert monitor.last_checked_block == 100
    assert monitor.callback == mock_callback
    assert len(monitor.addresses) == 1


def test_monitor_init_rpc_fail(mock_chain_interfaces, mock_callback):
    chain_interface = mock_chain_interfaces.get.return_value
    # Use PropertyMock to raise exception on attribute access
    type(chain_interface.web3.eth).block_number = PropertyMock(side_effect=Exception("RPC Error"))

    monitor = EventMonitor(["0x1234567890123456789012345678901234567890"], mock_callback)
    # Should catch exception and set to 0
    assert monitor.last_checked_block == 0


def test_monitor_init_no_rpc(mock_chain_interfaces, mock_callback):
    chain_interface = mock_chain_interfaces.get.return_value
    chain_interface.chain.rpc = ""

    monitor = EventMonitor(["0x1234567890123456789012345678901234567890"], mock_callback)
    assert monitor.last_checked_block == 0


def test_start_no_rpc(mock_chain_interfaces, mock_callback):
    chain_interface = mock_chain_interfaces.get.return_value
    chain_interface.chain.rpc = ""

    monitor = EventMonitor(["0x1234567890123456789012345678901234567890"], mock_callback)

    # Patch time.sleep to raise SystemExit if called (invoking cleanup/failure), preventing infinite loop
    # SystemExit is not caught by 'except Exception'
    with patch("time.sleep", side_effect=SystemExit):
        monitor.start()

    assert monitor.running is False


def test_check_activity_no_new_block(mock_chain_interfaces, mock_callback):
    chain_interface = mock_chain_interfaces.get.return_value
    chain_interface.web3.eth.block_number = 100

    monitor = EventMonitor(["0x1234567890123456789012345678901234567890"], mock_callback)
    monitor.last_checked_block = 100

    monitor.check_activity()

    mock_callback.assert_not_called()
    assert monitor.last_checked_block == 100


def test_check_activity_block_fetch_failed(mock_chain_interfaces, mock_callback, caplog):
    chain_interface = mock_chain_interfaces.get.return_value
    # Reset property mock if needed or just use consistent mock

    monitor = EventMonitor(["0x1234567890123456789012345678901234567890"], mock_callback)

    # We need to mock block_number raising specifically during check_activity
    # Since we can't easily switch PropertyMock on an instance dynamically without patching the class or instance dict
    # Let's just create a monitor where web3.eth is a specific mock

    # Actually, patch.object on the INSTANCE attribute works for properties if they are data descriptors or if we patch the class.
    # Easier: Just set the side_effect on the PropertyMock if we used one, or re-assign.
    type(chain_interface.web3.eth).block_number = PropertyMock(side_effect=Exception("RPC Fail"))

    monitor.check_activity()

    assert "Failed to get block number" in caplog.text


def test_check_activity_new_native_tx(mock_chain_interfaces, mock_callback):
    chain_interface = mock_chain_interfaces.get.return_value
    chain_interface.web3.eth.block_number = 101

    # Mock Block
    block = MagicMock()
    block.timestamp = 12345
    # Transaction matching address
    tx = {
        "hash": b"hash",
        "from": "0x1234567890123456789012345678901234567890",
        "to": "0x0000000000000000000000000000000000000000",
        "value": 100,
    }
    block.transactions = [tx]

    chain_interface.web3.eth.get_block.return_value = block
    chain_interface.web3.eth.get_logs.return_value = []  # No logs

    monitor = EventMonitor(["0x1234567890123456789012345678901234567890"], mock_callback)
    monitor.last_checked_block = 100

    monitor.check_activity()

    assert monitor.last_checked_block == 101
    mock_callback.assert_called_once()
    args, _ = mock_callback.call_args
    found_txs = args[0]
    assert len(found_txs) == 1
    assert found_txs[0]["token"] == "NATIVE"
    assert found_txs[0]["from"] == "0x1234567890123456789012345678901234567890"  # Checksummed


def test_check_activity_hash_in_block(mock_chain_interfaces, mock_callback):
    # Case where get_block returns tx hash strings instead of objects
    chain_interface = mock_chain_interfaces.get.return_value
    chain_interface.web3.eth.block_number = 101

    monitor = EventMonitor(["0x1234567890123456789012345678901234567890"], mock_callback)
    monitor.last_checked_block = 100

    block = MagicMock()
    block.timestamp = 12345
    block.transactions = [b"hash_bytes"]
    chain_interface.web3.eth.get_block.return_value = block

    tx_obj = {
        "hash": b"hash_bytes",
        "from": "0x1234567890123456789012345678901234567890",
        "to": "0x0000000000000000000000000000000000000000",
        "value": 100,
    }
    chain_interface.web3.eth.get_transaction.return_value = tx_obj
    chain_interface.web3.eth.get_logs.return_value = []

    monitor.check_activity()

    chain_interface.web3.eth.get_transaction.assert_called_with(b"hash_bytes")
    mock_callback.assert_called()


def test_check_activity_logs(mock_chain_interfaces, mock_callback):
    chain_interface = mock_chain_interfaces.get.return_value
    chain_interface.web3.eth.block_number = 101
    chain_interface.web3.eth.get_block.return_value = MagicMock(transactions=[])

    # Mock Log matching address

    my_addr = "0x1234567890123456789012345678901234567890".lower()
    monitor = EventMonitor([my_addr], mock_callback)
    monitor.last_checked_block = 100

    # 20 bytes address
    addr_bytes = Web3.to_bytes(hexstr=my_addr)  # 20 bytes
    padded_addr_bytes = b"\x00" * 12 + addr_bytes  # 32 bytes

    log = {
        "topics": [
            b"sig",
            b"\x00" * 32,  # from (don't care)
            padded_addr_bytes,  # to (me) -- This MUST match the padded address logic in monitor.py
        ],
        "transactionHash": MagicMock(hex=lambda: "0xloghash"),
        "address": "0xContractAddr",
    }

    chain_interface.web3.eth.get_logs.side_effect = [[], [log]]  # sent, received

    monitor.check_activity()

    mock_callback.assert_called()
    found = mock_callback.call_args[0][0]
    assert len(found) == 1
    assert found[0]["token"] == "TOKEN"
    assert found[0]["to"] == my_addr


def test_stop(mock_chain_interfaces, mock_callback):
    monitor = EventMonitor(["0x1234567890123456789012345678901234567890"], mock_callback)
    monitor.running = True
    monitor.stop()
    assert monitor.running is False
