from unittest.mock import MagicMock, PropertyMock, patch

import pytest
from web3 import exceptions as web3_exceptions

from iwa.core.chain import (
    Base,
    ChainInterface,
    ChainInterfaces,
    Ethereum,
    Gnosis,
    SupportedChain,
)
from iwa.core.models import EthereumAddress


@pytest.fixture
def mock_web3():
    with patch("iwa.core.chain.Web3") as mock:
        yield mock


@pytest.fixture
def mock_secrets():
    with patch("iwa.core.chain.settings") as mock:
        yield mock


def test_supported_chain_get_token_address():
    chain = SupportedChain(
        name="Test",
        rpcs=["http://rpc"],
        chain_id=1,
        native_currency="TEST",
        tokens={"TKN": EthereumAddress("0x1234567890123456789012345678901234567890")},
    )

    # Test getting by name
    assert chain.get_token_address("TKN") == "0x1234567890123456789012345678901234567890"

    # Test getting by address
    assert (
        chain.get_token_address("0x1234567890123456789012345678901234567890")
        == "0x1234567890123456789012345678901234567890"
    )

    # Test invalid
    assert chain.get_token_address("INVALID") is None
    assert chain.get_token_address("0xInvalid") is None

    # Test valid address NOT in tokens
    valid_addr_not_in_tokens = "0x0000000000000000000000000000000000000001"
    assert chain.get_token_address(valid_addr_not_in_tokens) is None


def test_chain_classes(mock_secrets):
    mock_secrets.gnosis_rpc.get_secret_value.return_value = "https://gnosis"
    mock_secrets.ethereum_rpc.get_secret_value.return_value = "https://eth"
    mock_secrets.base_rpc.get_secret_value.return_value = "https://base"

    # Reset singletons
    Gnosis._instance = None
    Ethereum._instance = None
    Base._instance = None

    assert Gnosis().name == "Gnosis"
    assert Ethereum().name == "Ethereum"
    assert Base().name == "Base"


def test_chain_interface_init(mock_web3, mock_secrets):
    mock_secrets.gnosis_rpc.get_secret_value.return_value = "https://gnosis"
    Gnosis._instance = None

    ci = ChainInterface()
    assert ci.chain.name == "Gnosis"
    mock_web3.assert_called()

    ci_eth = ChainInterface("ethereum")
    assert ci_eth.chain.name == "Ethereum"


def test_chain_interface_insecure_rpc_warning(mock_web3, caplog):
    chain = MagicMock(spec=SupportedChain)
    chain.name = "TestChain"
    chain.name = "Insecure"
    chain.rpcs = ["http://insecure"]

    # Needs to return property value for rpc
    type(chain).rpc = PropertyMock(return_value="http://insecure")

    ChainInterface(chain)
    assert "Using insecure RPC URL" in caplog.text


def test_is_contract(mock_web3):
    chain = MagicMock(spec=SupportedChain)
    chain.name = "TestChain"
    type(chain).rpc = PropertyMock(return_value="https://rpc")
    ci = ChainInterface(chain)
    ci.web3.eth.get_code.return_value = b"code"
    assert ci.is_contract("0xAddress") is True

    ci.web3.eth.get_code.return_value = b""
    assert ci.is_contract("0xAddress") is False


def test_get_native_balance(mock_web3):
    chain = MagicMock(spec=SupportedChain)
    chain.name = "TestChain"
    type(chain).rpc = PropertyMock(return_value="https://rpc")
    ci = ChainInterface(chain)
    ci.web3.eth.get_balance.return_value = 10**18
    ci.web3.from_wei.return_value = 1.0

    assert ci.get_native_balance_wei("0xAddress") == 10**18
    assert ci.get_native_balance_eth("0xAddress") == 1.0



# NOTE: Tests for sign_and_send_transaction were removed because the method was removed
# from ChainInterface for security reasons. Transaction signing is now handled exclusively
# through TransactionService.sign_and_send() which uses KeyStorage internally.


def test_estimate_gas(mock_web3):
    chain = MagicMock(spec=SupportedChain)
    chain.name = "TestChain"
    type(chain).rpc = PropertyMock(return_value="https://rpc")
    ci = ChainInterface(chain)
    built_method = MagicMock()
    built_method.estimate_gas.return_value = 1000

    # Not a contract
    ci.web3.eth.get_code.return_value = b""
    assert ci.estimate_gas(built_method, {"from": "0xSender"}) == 1100

    # Is a contract
    ci.web3.eth.get_code.return_value = b"code"
    assert ci.estimate_gas(built_method, {"from": "0xSender"}) == 0


def test_calculate_transaction_params(mock_web3):
    chain = MagicMock(spec=SupportedChain)
    chain.name = "TestChain"
    type(chain).rpc = PropertyMock(return_value="https://rpc")
    ci = ChainInterface(chain)
    ci.web3.eth.get_transaction_count.return_value = 5
    ci.web3.eth.gas_price = 20

    with patch.object(ci, "estimate_gas", return_value=1000):
        params = ci.calculate_transaction_params(MagicMock(), {"from": "0xSender"})
        assert params["nonce"] == 5
        assert params["gas"] == 1000
        assert params["gasPrice"] == 20


def test_wait_for_no_pending_tx(mock_web3):
    chain = MagicMock(spec=SupportedChain)
    chain.name = "TestChain"
    type(chain).rpc = PropertyMock(return_value="https://rpc")
    ci = ChainInterface(chain)

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
        if block_identifier == "latest":
            return 10
        return 11

    ci.web3.eth.get_transaction_count.side_effect = side_effect

    with patch("time.time", side_effect=[0, 1, 61]):
        with patch("time.sleep"):
            assert ci.wait_for_no_pending_tx("0xSender") is False


def test_send_native_transfer(mock_web3):
    chain = MagicMock(spec=SupportedChain, rpcs=["https://rpc"], chain_id=1, native_currency="ETH")
    chain.name = "TestChain"
    type(chain).rpc = PropertyMock(return_value="https://rpc")
    ci = ChainInterface(chain)
    account = MagicMock(address="0xSender", key="key")

    ci.web3.eth.get_transaction_count.return_value = 0
    ci.web3.eth.gas_price = 10
    ci.web3.eth.estimate_gas.return_value = 21000

    # Sufficient balance
    ci.web3.eth.get_balance.return_value = 10**18  # plenty
    ci.web3.eth.get_balance.return_value = 10**18  # plenty
    # Valid mock return for success: (True, dict_receipt)
    # The actual method returns tx_hash.hex().
    mock_signed_tx = MagicMock()
    mock_signed_tx.raw_transaction = b"raw"
    mock_receipt = {"transactionHash": b"hash", "status": 1}

    with (
        patch.object(ci.web3.eth, "send_raw_transaction", return_value=b"hash"),
        patch.object(ci.web3.eth, "wait_for_transaction_receipt", return_value=mock_receipt),
        patch.object(ci, "wait_for_no_pending_tx", return_value=True),
    ):
        success, tx_hash = ci.send_native_transfer(
            account.address, "0xReceiver", 1000, sign_callback=lambda tx: mock_signed_tx
        )
        assert success is True
        assert tx_hash == "68617368"

    # Insufficient balance
    ci.web3.eth.get_balance.return_value = 0
    ci.web3.from_wei.return_value = 0.0
    assert ci.send_native_transfer(
        account.address, "0xReceiver", 1000, sign_callback=lambda tx: mock_signed_tx
    ) == (False, None)


def test_chain_interfaces_get():
    ChainInterfaces._instance = None
    interfaces = ChainInterfaces()
    assert interfaces.get("gnosis").chain.name == "Gnosis"

    with pytest.raises(ValueError):
        interfaces.get("invalid")





def test_chain_interface_get_token_address(mock_web3):
    chain = MagicMock(spec=SupportedChain)
    chain.name = "TestChain"
    type(chain).rpc = PropertyMock(return_value="https://rpc")
    chain.get_token_address.return_value = "0xToken"
    ci = ChainInterface(chain)

    assert ci.get_token_address("Token") == "0xToken"
    chain.get_token_address.assert_called_with("Token")


def test_rotate_rpc(mock_web3):
    chain = MagicMock(spec=SupportedChain)
    chain.name = "TestChain"
    chain.rpcs = ["http://rpc1", "http://rpc2", "http://rpc3"]
    chain.name = "TestChain"
    # Needs to return property value for rpc if accessed, but here access is via index

    ci = ChainInterface(chain)
    ci._current_rpc_index = 0

    # Rotate 1
    assert ci.rotate_rpc() is True
    assert ci._current_rpc_index == 1
    # Check that Web3 was re-initialized with new RPC
    args, _ = mock_web3.call_args
    # Web3 is init with HTTPProvider. Mock checking is complex for exact args if provider mock is deeper.
    # Just check index for now.

    # Rotate 2
    assert ci.rotate_rpc() is True
    assert ci._current_rpc_index == 2

    # Rotate 3 (back to 0)
    assert ci.rotate_rpc() is True
    assert ci._current_rpc_index == 0


def test_rotate_rpc_no_rpcs(mock_web3):
    chain = MagicMock(spec=SupportedChain)
    chain.name = "TestChain"
    chain.rpcs = []
    chain.name = "TestChain"
    type(chain).rpc = PropertyMock(return_value="")
    ci = ChainInterface(chain)
    assert ci.rotate_rpc() is False


def test_rotate_rpc_single_rpc(mock_web3):
    chain = MagicMock(spec=SupportedChain)
    chain.name = "TestChain"
    chain.rpcs = ["http://rpc1"]
    chain.name = "TestChain"
    type(chain).rpc = PropertyMock(return_value="http://rpc1")
    ci = ChainInterface(chain)
    assert ci.rotate_rpc() is False
