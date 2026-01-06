"""Tests for ChainInterface RPC error handling and retry logic."""

from unittest.mock import MagicMock, patch

import pytest

from iwa.core.chain.interface import ChainInterface


@pytest.fixture
def mock_chain_interface():
    """Create a ChainInterface with mocked web3."""
    with patch("iwa.core.chain.interface.get_rate_limiter") as mock_limiter:
        with patch("iwa.core.chain.interface.RateLimitedWeb3") as mock_rlw3:
            mock_limiter.return_value = MagicMock()
            mock_web3 = MagicMock()
            mock_rlw3.return_value = mock_web3

            # Construct with mock chain
            with patch("iwa.core.chain.models.Gnosis") as mock_gnosis_cls:
                mock_gnosis = mock_gnosis_cls.return_value
                mock_gnosis.name = "gnosis"
                mock_gnosis.rpc = "https://rpc.gnosis.gateway.fm"
                mock_gnosis.rpcs = [
                    "https://rpc.gnosis.gateway.fm",
                    "https://rpc2.gnosis.gateway.fm",
                ]
                mock_gnosis.chain_id = 100
                mock_gnosis.native_currency = "xDAI"
                mock_gnosis.tokens = {}
                mock_gnosis.contracts = {}

                interface = ChainInterface(mock_gnosis)
                interface._rate_limiter = mock_limiter.return_value

                yield interface, mock_web3


def test_is_rate_limit_error():
    """Test rate limit error detection."""
    with patch("iwa.core.chain.interface.get_rate_limiter"):
        with patch("iwa.core.chain.interface.RateLimitedWeb3"):
            with patch("iwa.core.chain.models.Gnosis") as mock_gnosis_cls:
                mock_gnosis = mock_gnosis_cls.return_value
                mock_gnosis.name = "gnosis"
                mock_gnosis.rpc = "https://rpc.example.com"
                mock_gnosis.rpcs = ["https://rpc.example.com"]
                mock_gnosis.chain_id = 100
                mock_gnosis.native_currency = "xDAI"
                mock_gnosis.tokens = {}
                mock_gnosis.contracts = {}

                interface = ChainInterface(mock_gnosis)

    assert interface._is_rate_limit_error(Exception("429 Too Many Requests"))
    assert interface._is_rate_limit_error(Exception("rate limit exceeded"))
    assert not interface._is_rate_limit_error(Exception("connection refused"))


def test_is_connection_error():
    """Test connection error detection."""
    with patch("iwa.core.chain.interface.get_rate_limiter"):
        with patch("iwa.core.chain.interface.RateLimitedWeb3"):
            with patch("iwa.core.chain.models.Gnosis") as mock_gnosis_cls:
                mock_gnosis = mock_gnosis_cls.return_value
                mock_gnosis.name = "gnosis"
                mock_gnosis.rpc = "https://rpc.example.com"
                mock_gnosis.rpcs = ["https://rpc.example.com"]
                mock_gnosis.chain_id = 100
                mock_gnosis.native_currency = "xDAI"
                mock_gnosis.tokens = {}
                mock_gnosis.contracts = {}

                interface = ChainInterface(mock_gnosis)

    assert interface._is_connection_error(Exception("connection timeout"))
    assert interface._is_connection_error(Exception("connection refused"))
    assert interface._is_connection_error(Exception("read timeout"))
    assert not interface._is_connection_error(Exception("429"))


def test_is_server_error():
    """Test server error detection."""
    with patch("iwa.core.chain.interface.get_rate_limiter"):
        with patch("iwa.core.chain.interface.RateLimitedWeb3"):
            with patch("iwa.core.chain.models.Gnosis") as mock_gnosis_cls:
                mock_gnosis = mock_gnosis_cls.return_value
                mock_gnosis.name = "gnosis"
                mock_gnosis.rpc = "https://rpc.example.com"
                mock_gnosis.rpcs = ["https://rpc.example.com"]
                mock_gnosis.chain_id = 100
                mock_gnosis.native_currency = "xDAI"
                mock_gnosis.tokens = {}
                mock_gnosis.contracts = {}

                interface = ChainInterface(mock_gnosis)

    assert interface._is_server_error(Exception("500 internal server error"))
    assert interface._is_server_error(Exception("502 bad gateway"))
    assert not interface._is_server_error(Exception("404 not found"))


def test_is_tenderly_quota_exceeded():
    """Test Tenderly quota detection."""
    with patch("iwa.core.chain.interface.get_rate_limiter"):
        with patch("iwa.core.chain.interface.RateLimitedWeb3"):
            with patch("iwa.core.chain.models.Gnosis") as mock_gnosis_cls:
                mock_gnosis = mock_gnosis_cls.return_value
                mock_gnosis.name = "gnosis"
                mock_gnosis.rpc = "https://virtual.tenderly.co/xxx"
                mock_gnosis.rpcs = ["https://virtual.tenderly.co/xxx"]
                mock_gnosis.chain_id = 100
                mock_gnosis.native_currency = "xDAI"
                mock_gnosis.tokens = {}
                mock_gnosis.contracts = {}

                interface = ChainInterface(mock_gnosis)

    assert interface._is_tenderly_quota_exceeded(
        Exception("403 Forbidden tenderly virtual network")
    )
    assert not interface._is_tenderly_quota_exceeded(Exception("500 server error"))


def test_handle_rpc_error_rotation(mock_chain_interface):
    """Test RPC error handling triggers rotation."""
    interface, mock_web3 = mock_chain_interface

    # Mock rotate_rpc to return True
    interface.rotate_rpc = MagicMock(return_value=True)

    error = Exception("429 rate limit")
    result = interface._handle_rpc_error(error)

    assert result["is_rate_limit"]
    assert result["should_retry"]
    interface.rotate_rpc.assert_called()


def test_handle_rpc_error_server_error(mock_chain_interface):
    """Test server error triggers retry without rotation."""
    interface, _ = mock_chain_interface
    interface.rotate_rpc = MagicMock(return_value=False)

    error = Exception("503 service unavailable")
    result = interface._handle_rpc_error(error)

    assert result["is_server_error"]
    assert result["should_retry"]


def test_check_rpc_health(mock_chain_interface):
    """Test RPC health check."""
    interface, mock_web3 = mock_chain_interface

    # Healthy
    mock_web3._web3.eth.block_number = 1000
    assert interface.check_rpc_health()

    # Unhealthy
    mock_web3._web3.eth.block_number = None
    assert not interface.check_rpc_health()


def test_rotate_rpc_single_rpc():
    """Test rotation fails with single RPC."""
    with patch("iwa.core.chain.interface.get_rate_limiter"):
        with patch("iwa.core.chain.interface.RateLimitedWeb3"):
            with patch("iwa.core.chain.models.Gnosis") as mock_gnosis_cls:
                mock_gnosis = mock_gnosis_cls.return_value
                mock_gnosis.name = "gnosis"
                mock_gnosis.rpc = "https://rpc.example.com"
                mock_gnosis.rpcs = ["https://rpc.example.com"]  # Only one RPC
                mock_gnosis.chain_id = 100
                mock_gnosis.native_currency = "xDAI"
                mock_gnosis.tokens = {}
                mock_gnosis.contracts = {}

                interface = ChainInterface(mock_gnosis)

    assert not interface.rotate_rpc()


def test_is_tenderly_property():
    """Test is_tenderly property."""
    with patch("iwa.core.chain.interface.get_rate_limiter"):
        with patch("iwa.core.chain.interface.RateLimitedWeb3"):
            with patch("iwa.core.chain.models.Gnosis") as mock_gnosis_cls:
                mock_gnosis = mock_gnosis_cls.return_value
                mock_gnosis.name = "gnosis"
                mock_gnosis.rpc = "https://virtual.tenderly.co/xxx"
                mock_gnosis.rpcs = ["https://virtual.tenderly.co/xxx"]
                mock_gnosis.chain_id = 100
                mock_gnosis.native_currency = "xDAI"
                mock_gnosis.tokens = {}
                mock_gnosis.contracts = {}

                interface = ChainInterface(mock_gnosis)

    assert interface.is_tenderly


def test_reset_rpc_failure_counts(mock_chain_interface):
    """Test resetting failure counts."""
    interface, _ = mock_chain_interface
    interface._rpc_failure_counts = {0: 5, 1: 3}

    interface.reset_rpc_failure_counts()

    assert interface._rpc_failure_counts == {}
