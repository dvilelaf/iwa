import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from web3 import Web3
from web3 import exceptions as web3_exceptions
from iwa.core.chain import (
    SupportedChain,
    Gnosis,
    Ethereum,
    Base,
    SupportedChains,
    ChainInterface,
    ChainInterfaces,
)
from iwa.core.models import EthereumAddress

@pytest.fixture
def mock_web3():
    with patch("iwa.core.chain.Web3") as mock:
        yield mock

@pytest.fixture
def mock_secrets():
    with patch("iwa.core.chain.Secrets") as mock:
        yield mock

def test_supported_chain_get_token_address():
    chain = SupportedChain(
        name="Test",
        rpc="http://rpc",
        chain_id=1,
        native_currency="TEST",
        tokens={"TKN": EthereumAddress("0x1234567890123456789012345678901234567890")}
    )

    # Test getting by name
    assert chain.get_token_address("TKN") == "0x1234567890123456789012345678901234567890"

    # Test getting by address
    assert chain.get_token_address("0x1234567890123456789012345678901234567890") == "0x1234567890123456789012345678901234567890"

    # Test invalid
    assert chain.get_token_address("INVALID") is None
    assert chain.get_token_address("0xInvalid") is None

    # Test valid address NOT in tokens
    valid_addr_not_in_tokens = "0x0000000000000000000000000000000000000001"
    assert chain.get_token_address(valid_addr_not_in_tokens) is None

def test_chain_classes(mock_secrets):
    mock_secrets.return_value.gnosis_rpc.get_secret_value.return_value = "https://gnosis"
    mock_secrets.return_value.ethereum_rpc.get_secret_value.return_value = "https://eth"
    mock_secrets.return_value.base_rpc.get_secret_value.return_value = "https://base"

    # Reset singletons
    Gnosis._instance = None
    Ethereum._instance = None
    Base._instance = None

    assert Gnosis().name == "Gnosis"
    assert Ethereum().name == "Ethereum"
    assert Base().name == "Base"

def test_chain_interface_init(mock_web3, mock_secrets):
    mock_secrets.return_value.gnosis_rpc.get_secret_value.return_value = "https://gnosis"
    Gnosis._instance = None

    ci = ChainInterface()
    assert ci.chain.name == "Gnosis"
    mock_web3.assert_called()

    ci_eth = ChainInterface("ethereum")
    assert ci_eth.chain.name == "Ethereum"

def test_chain_interface_insecure_rpc_warning(mock_web3, caplog):
    chain = MagicMock(spec=SupportedChain)
    chain.name = "Insecure"
    chain.rpc = "http://insecure"

    ChainInterface(chain)
    assert "Using insecure RPC URL" in caplog.text

def test_is_contract(mock_web3):
    ci = ChainInterface(MagicMock(spec=SupportedChain, rpc="https://rpc"))
    ci.web3.eth.get_code.return_value = b"code"
    assert ci.is_contract("0xAddress") is True

    ci.web3.eth.get_code.return_value = b""
    assert ci.is_contract("0xAddress") is False

def test_get_native_balance(mock_web3):
    ci = ChainInterface(MagicMock(spec=SupportedChain, rpc="https://rpc"))
    ci.web3.eth.get_balance.return_value = 10**18
    ci.web3.from_wei.return_value = 1.0

    assert ci.get_native_balance_wei("0xAddress") == 10**18
    assert ci.get_native_balance_eth("0xAddress") == 1.0

def test_sign_and_send_transaction_success(mock_web3):
    ci = ChainInterface(MagicMock(spec=SupportedChain, rpc="https://rpc"))
    ci.web3.eth.account.sign_transaction.return_value = MagicMock(raw_transaction=b"raw")
    ci.web3.eth.send_raw_transaction.return_value = b"hash"
    receipt = MagicMock(status=1)
    ci.web3.eth.wait_for_transaction_receipt.return_value = receipt

    # Mock wait_for_no_pending_tx to return immediately
    with patch.object(ci, "wait_for_no_pending_tx", return_value=True):
        success, res = ci.sign_and_send_transaction({"from": "0xSender"}, "key")
        assert success is True
        assert res == receipt

def test_sign_and_send_transaction_failure(mock_web3):
    ci = ChainInterface(MagicMock(spec=SupportedChain, rpc="https://rpc"))
    ci.web3.eth.account.sign_transaction.return_value = MagicMock(raw_transaction=b"raw")
    ci.web3.eth.send_raw_transaction.return_value = b"hash"
    receipt = MagicMock(status=0)
    ci.web3.eth.wait_for_transaction_receipt.return_value = receipt

    success, res = ci.sign_and_send_transaction({"from": "0xSender"}, "key")
    assert success is False

def test_sign_and_send_transaction_gas_retry(mock_web3):
    ci = ChainInterface(MagicMock(spec=SupportedChain, rpc="https://rpc"))
    ci.web3.eth.account.sign_transaction.return_value = MagicMock(raw_transaction=b"raw")

    # First attempt raises RPC error with "FeeTooLow"
    # Second attempt succeeds
    error = web3_exceptions.Web3RPCError("FeeTooLow", 123)
    ci.web3.eth.send_raw_transaction.side_effect = [error, b"hash"]
    receipt = MagicMock(status=1)
    ci.web3.eth.wait_for_transaction_receipt.return_value = receipt

    with patch.object(ci, "wait_for_no_pending_tx", return_value=True):
        with patch("time.sleep"): # speed up test
            success, res = ci.sign_and_send_transaction({"from": "0xSender", "gas": 10000}, "key")
            assert success is True
            assert ci.web3.eth.send_raw_transaction.call_count == 2

def test_sign_and_send_transaction_exception(mock_web3):
    ci = ChainInterface(MagicMock(spec=SupportedChain, rpc="https://rpc"))
    ci.web3.eth.account.sign_transaction.side_effect = Exception("Error")

    success, res = ci.sign_and_send_transaction({"from": "0xSender"}, "key")
    assert success is False

def test_estimate_gas(mock_web3):
    ci = ChainInterface(MagicMock(spec=SupportedChain, rpc="https://rpc"))
    built_method = MagicMock()
    built_method.estimate_gas.return_value = 1000

    # Not a contract
    ci.web3.eth.get_code.return_value = b""
    assert ci.estimate_gas(built_method, {"from": "0xSender"}) == 1100

    # Is a contract
    ci.web3.eth.get_code.return_value = b"code"
    assert ci.estimate_gas(built_method, {"from": "0xSender"}) == 0

def test_calculate_transaction_params(mock_web3):
    ci = ChainInterface(MagicMock(spec=SupportedChain, rpc="https://rpc"))
    ci.web3.eth.get_transaction_count.return_value = 5
    ci.web3.eth.gas_price = 20

    with patch.object(ci, "estimate_gas", return_value=1000):
        params = ci.calculate_transaction_params(MagicMock(), {"from": "0xSender"})
        assert params["nonce"] == 5
        assert params["gas"] == 1000
        assert params["gasPrice"] == 20

def test_wait_for_no_pending_tx(mock_web3):
    ci = ChainInterface(MagicMock(spec=SupportedChain, rpc="https://rpc"))

    # pending == latest
    ci.web3.eth.get_transaction_count.side_effect = [10, 10]
    assert ci.wait_for_no_pending_tx("0xSender") is True

    # pending != latest then pending == latest
    ci.web3.eth.get_transaction_count.side_effect = [10, 11, 11, 11]
    with patch("time.sleep"):
        assert ci.wait_for_no_pending_tx("0xSender") is True

    # Timeout
    ci.web3.eth.get_transaction_count.return_value = 10
    # Mock pending to be always different
    def side_effect(address, block_identifier):
        if block_identifier == "latest": return 10
        return 11
    ci.web3.eth.get_transaction_count.side_effect = side_effect

    with patch("time.time", side_effect=[0, 1, 61]):
        with patch("time.sleep"):
            assert ci.wait_for_no_pending_tx("0xSender") is False

def test_send_native_transfer(mock_web3):
    ci = ChainInterface(MagicMock(spec=SupportedChain, rpc="https://rpc", chain_id=1, native_currency="ETH"))
    account = MagicMock(address="0xSender", key="key")

    ci.web3.eth.get_transaction_count.return_value = 0
    ci.web3.eth.gas_price = 10
    ci.web3.eth.estimate_gas.return_value = 21000

    # Sufficient balance
    ci.web3.eth.get_balance.return_value = 10**18 # plenty
    with patch.object(ci, "sign_and_send_transaction", return_value=(True, {})):
        assert ci.send_native_transfer(account, "0xReceiver", 1000) is True

    # Insufficient balance
    ci.web3.eth.get_balance.return_value = 0
    ci.web3.from_wei.return_value = 0.0
    assert ci.send_native_transfer(account, "0xReceiver", 1000) is False

def test_chain_interfaces_get():
    ChainInterfaces._instance = None
    interfaces = ChainInterfaces()
    assert interfaces.get("gnosis").chain.name == "Gnosis"

    with pytest.raises(ValueError):
        interfaces.get("invalid")

def test_sign_and_send_transaction_rpc_error_not_gas(mock_web3):
    ci = ChainInterface(MagicMock(spec=SupportedChain, rpc="https://rpc"))
    ci.web3.eth.account.sign_transaction.return_value = MagicMock(raw_transaction=b"raw")

    # RPC error NOT gas related
    error = web3_exceptions.Web3RPCError("OtherError", 123)
    ci.web3.eth.send_raw_transaction.side_effect = error

    success, res = ci.sign_and_send_transaction({"from": "0xSender"}, "key")
    assert success is False

def test_chain_interface_get_token_address(mock_web3):
    chain = MagicMock(spec=SupportedChain)
    chain.rpc = "https://rpc"
    chain.get_token_address.return_value = "0xToken"
    ci = ChainInterface(chain)

    assert ci.get_token_address("Token") == "0xToken"
    chain.get_token_address.assert_called_with("Token")
