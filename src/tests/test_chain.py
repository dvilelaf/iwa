from unittest.mock import MagicMock, PropertyMock, patch

import pytest

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
    """Mock Web3 and RateLimitedWeb3 to bypass rate limiting wrapper in tests."""
    with (
        patch("iwa.core.chain.interface.Web3") as mock_web3_class,
        patch("iwa.core.chain.interface.RateLimitedWeb3") as mock_rl_web3,
    ):
        # Make RateLimitedWeb3 just return the raw web3 instance passed to it
        mock_rl_web3.side_effect = lambda w3, rl, ci: w3
        yield mock_web3_class


@pytest.fixture
def mock_secrets():
    with patch("iwa.core.chain.models.settings") as mock:
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
    chain.rpcs = ["https://rpc"]
    type(chain).rpc = PropertyMock(return_value="https://rpc")
    ci = ChainInterface(chain)
    ci.web3.eth.get_code.return_value = b"code"
    assert ci.is_contract("0xAddress") is True

    ci.web3.eth.get_code.return_value = b""
    assert ci.is_contract("0xAddress") is False


def test_get_native_balance(mock_web3):
    chain = MagicMock(spec=SupportedChain)
    chain.name = "TestChain"
    chain.rpcs = ["https://rpc"]
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
    chain.rpcs = ["https://rpc"]
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
    chain.rpcs = ["https://rpc"]
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
    chain.rpcs = ["https://rpc"]
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
    chain.rpcs = ["https://rpc"]
    type(chain).rpc = PropertyMock(return_value="https://rpc")
    chain.get_token_address.return_value = "0xToken"
    ci = ChainInterface(chain)

    assert ci.get_token_address("Token") == "0xToken"
    chain.get_token_address.assert_called_with("Token")


def test_rotate_rpc(mock_web3):
    chain = MagicMock(spec=SupportedChain)
    chain.name = "TestChain"
    chain.rpcs = ["http://rpc1", "http://rpc2", "http://rpc3"]
    # Needs to return property value for rpc if accessed
    type(chain).rpc = PropertyMock(return_value="http://rpc1")

    ci = ChainInterface(chain)
    ci._current_rpc_index = 0

    # Mock health check to always pass
    with patch.object(ci, "check_rpc_health", return_value=True):
        # Rotate 1
        assert ci.rotate_rpc() is True
        assert ci._current_rpc_index == 1

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


# --- Tests migrated from test_chain_interface_coverage.py ---


def test_chain_interface_with_real_chains():
    """Test ChainInterface with real chain configurations."""
    from eth_account import Account

    valid_addr_1 = Account.create().address
    valid_addr_2 = Account.create().address

    # Patch RateLimitedWeb3 to bypass rate limiting wrapper
    with patch("iwa.core.chain.interface.RateLimitedWeb3", side_effect=lambda w3, rl, ci: w3):
        # Use Gnosis() directly (SupportedChain), not ChainInterfaces().gnosis (ChainInterface)
        interface = ChainInterface(Gnosis())
        interface.chain.rpcs = ["http://rpc1", "http://rpc2"]
        interface.web3 = MagicMock()
        interface.web3.provider.endpoint_uri = "http://rpc1"
        interface.web3._web3.eth.block_number = 12345  # For health check

        # Mock health check to pass
        with patch.object(interface, "check_rpc_health", return_value=True):
            rotated = interface.rotate_rpc()
            assert rotated is True

        interface.web3.eth.get_code = MagicMock(return_value=b"code")
        assert interface.is_contract(valid_addr_1) is True

        interface.web3.eth.get_code.return_value = b""
        assert interface.is_contract(valid_addr_2) is False

        with patch("iwa.core.contracts.erc20.ERC20Contract") as mock_erc20:
            instance = mock_erc20.return_value
            instance.symbol = "SYM"
            instance.decimals = 18

            interface.web3.eth.get_code.return_value = b"code"

            sym = interface.get_token_symbol(valid_addr_1)
            assert sym == "SYM"

            dec = interface.get_token_decimals(valid_addr_1)
            assert dec == 18


# --- Negative Tests ---


def test_send_native_transfer_insufficient_balance(mock_web3):
    """Test send_native_transfer fails with insufficient balance."""
    chain = MagicMock(spec=SupportedChain)
    chain.name = "TestChain"
    chain.rpcs = ["https://rpc"]
    chain.chain_id = 1
    chain.native_currency = "ETH"
    type(chain).rpc = PropertyMock(return_value="https://rpc")

    ci = ChainInterface(chain)
    ci.web3.eth.get_transaction_count.return_value = 0
    ci.web3.eth.gas_price = 1000000000  # 1 gwei
    ci.web3.eth.estimate_gas.return_value = 21000
    ci.web3.eth.get_balance.return_value = 1000  # Very low balance
    ci.web3.from_wei.return_value = 0.000001

    sign_callback = MagicMock()

    success, tx_hash = ci.send_native_transfer(
        from_address="0x1111111111111111111111111111111111111111",
        to_address="0x2222222222222222222222222222222222222222",
        value_wei=10**18,  # 1 ETH - more than available
        sign_callback=sign_callback,
    )

    assert success is False
    assert tx_hash is None
    sign_callback.assert_not_called()


def test_send_native_transfer_rpc_error(mock_web3):
    """Test send_native_transfer handles RPC errors."""
    chain = MagicMock(spec=SupportedChain)
    chain.name = "TestChain"
    chain.rpcs = ["https://rpc"]
    chain.chain_id = 1
    chain.native_currency = "ETH"
    type(chain).rpc = PropertyMock(return_value="https://rpc")

    ci = ChainInterface(chain)
    ci.web3.eth.get_transaction_count.return_value = 0
    ci.web3.eth.gas_price = 1000000000
    ci.web3.eth.estimate_gas.return_value = 21000
    ci.web3.eth.get_balance.return_value = 10**19  # Enough balance
    ci.web3.from_wei.return_value = 10.0
    ci.web3.eth.send_raw_transaction.side_effect = Exception("Connection refused")

    sign_callback = MagicMock()
    sign_callback.return_value = MagicMock(raw_transaction=b"signed")

    success, tx_hash = ci.send_native_transfer(
        from_address="0x1111111111111111111111111111111111111111",
        to_address="0x2222222222222222222222222222222222222222",
        value_wei=10**17,
        sign_callback=sign_callback,
    )

    assert success is False
    assert tx_hash is None


def test_get_token_symbol_fallback_on_error(mock_web3):
    """Test get_token_symbol returns truncated address on error."""
    chain = MagicMock(spec=SupportedChain)
    chain.name = "TestChain"
    chain.rpcs = ["https://rpc"]
    chain.tokens = {}
    type(chain).rpc = PropertyMock(return_value="https://rpc")

    ci = ChainInterface(chain)

    # Patch ERC20Contract to raise error
    with patch("iwa.core.contracts.erc20.ERC20Contract") as mock_erc20:
        mock_erc20.side_effect = Exception("Contract not found")

        address = "0x1234567890123456789012345678901234567890"
        symbol = ci.get_token_symbol(address)

        # Should return truncated address as fallback
        assert symbol == "0x1234...7890"


def test_get_token_decimals_fallback_on_error(mock_web3):
    """Test get_token_decimals returns 18 on error."""
    chain = MagicMock(spec=SupportedChain)
    chain.name = "TestChain"
    chain.rpcs = ["https://rpc"]
    type(chain).rpc = PropertyMock(return_value="https://rpc")

    ci = ChainInterface(chain)

    with patch("iwa.core.contracts.erc20.ERC20Contract") as mock_erc20:
        mock_erc20.side_effect = Exception("Contract not found")

        decimals = ci.get_token_decimals("0x1234567890123456789012345678901234567890")

        # Should return default 18 as fallback
        assert decimals == 18


def test_is_rate_limit_error_detection(mock_web3):
    """Test _is_rate_limit_error detects various rate limit errors."""
    chain = MagicMock(spec=SupportedChain)
    chain.name = "TestChain"
    chain.rpcs = ["https://rpc"]
    type(chain).rpc = PropertyMock(return_value="https://rpc")

    ci = ChainInterface(chain)

    # Should detect rate limit
    assert ci._is_rate_limit_error(Exception("Error 429")) is True
    assert ci._is_rate_limit_error(Exception("rate limit exceeded")) is True
    assert ci._is_rate_limit_error(Exception("Too Many Requests")) is True
    assert ci._is_rate_limit_error(Exception("ratelimit")) is True

    # Should NOT detect as rate limit
    assert ci._is_rate_limit_error(Exception("Connection timeout")) is False
    assert ci._is_rate_limit_error(Exception("Invalid address")) is False
    assert ci._is_rate_limit_error(Exception("Out of gas")) is False


def test_handle_rpc_error_non_rate_limit(mock_web3):
    """Test _handle_rpc_error returns dict with should_retry for connection errors."""
    chain = MagicMock(spec=SupportedChain)
    chain.name = "TestChain"
    chain.rpcs = ["https://rpc1", "https://rpc2"]
    type(chain).rpc = PropertyMock(return_value="https://rpc1")

    ci = ChainInterface(chain)

    # Connection error should now return dict with should_retry
    with patch.object(ci, "check_rpc_health", return_value=True):
        result = ci._handle_rpc_error(Exception("Connection timeout"))
        assert isinstance(result, dict)
        assert result["is_connection_error"] is True
        assert result["should_retry"] is True

    # Non-retryable error (e.g., invalid address) should not trigger retry
    result = ci._handle_rpc_error(Exception("Invalid address"))
    assert isinstance(result, dict)
    assert result["should_retry"] is False
