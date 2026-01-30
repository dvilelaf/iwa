"""Tests for Safe module."""

from unittest.mock import MagicMock, patch

import pytest

from iwa.core.models import StoredSafeAccount
from iwa.plugins.gnosis.safe import (
    MAX_CACHED_CLIENTS,
    SafeMultisig,
    _ethereum_client_cache,
    get_ethereum_client,
)


@pytest.fixture
def mock_settings():
    """Mock settings."""
    # secrets is no longer used in this module, so we don't need to patch it here
    yield None


@pytest.fixture
def mock_safe_eth():
    """Mock safe_eth module."""
    with (
        patch("iwa.plugins.gnosis.safe.EthereumClient") as mock_client,
        patch("iwa.plugins.gnosis.safe.Safe") as mock_safe,
    ):
        yield mock_client, mock_safe


@pytest.fixture
def safe_account():
    """Mock safe account."""
    return StoredSafeAccount(
        address="0x1234567890123456789012345678901234567890",
        owners=["0x1234567890123456789012345678901234567890"],
        threshold=1,
        chains=["gnosis"],
        tag="mysafe",
        signers=[],
    )


def test_init(safe_account, mock_settings, mock_safe_eth):
    """Test initialization."""
    with patch("iwa.core.chain.ChainInterfaces") as mock_ci_cls:
        mock_ci = mock_ci_cls.return_value
        mock_ci.get.return_value.current_rpc = "http://rpc"
        ms = SafeMultisig(safe_account, "gnosis")
        assert ms.multisig is not None
        mock_safe_eth[0].assert_called_with("http://rpc")  # EthereumClient init
        mock_safe_eth[1].assert_called()  # Safe init


def test_init_invalid_chain(safe_account, mock_settings, mock_safe_eth):
    """Test initialization with invalid chain."""
    with pytest.raises(ValueError, match="not deployed on chain"):
        SafeMultisig(safe_account, "ethereum")


def test_getters(safe_account, mock_settings, mock_safe_eth):
    """Test safe property getters."""
    ms = SafeMultisig(safe_account, "gnosis")
    mock_safe_instance = mock_safe_eth[1].return_value

    mock_safe_instance.retrieve_owners.return_value = ["0x1"]
    assert ms.get_owners() == ["0x1"]

    mock_safe_instance.retrieve_threshold.return_value = 2
    assert ms.get_threshold() == 2

    mock_safe_instance.retrieve_nonce.return_value = 5
    assert ms.get_nonce() == 5

    mock_safe_instance.retrieve_all_info.return_value = {"info": "test"}
    assert ms.retrieve_all_info() == {"info": "test"}


def test_build_tx(safe_account, mock_settings, mock_safe_eth):
    """Test build_multisig_tx."""
    ms = SafeMultisig(safe_account, "gnosis")
    mock_safe_instance = mock_safe_eth[1].return_value
    mock_safe_instance.build_multisig_tx.return_value = "0xTx"

    tx = ms.build_tx("0xTo", 100)
    assert tx == "0xTx"

    mock_safe_instance.build_multisig_tx.assert_called()


def test_send_tx(safe_account, mock_settings, mock_safe_eth):
    """Test send_multisig_tx."""
    ms = SafeMultisig(safe_account, "gnosis")

    # Mock build_tx just in case (though it delegates)
    # Actually we can let it delegate to mock_safe_instance which returns "0xSafeTx"
    mock_safe_instance = mock_safe_eth[1].return_value
    mock_safe_instance.build_multisig_tx.return_value = "0xSafeTx"

    callback = MagicMock(return_value="0xHash")

    tx_hash = ms.send_tx("0xTo", 100, callback)
    assert tx_hash == "0xHash"

    callback.assert_called_with("0xSafeTx")


class TestEthereumClientCache:
    """Tests for EthereumClient caching to prevent FD exhaustion."""

    def setup_method(self):
        """Clear cache before each test."""
        _ethereum_client_cache.clear()

    def test_cache_reuses_client(self):
        """Test that the same RPC URL returns the same cached client."""
        with patch("iwa.plugins.gnosis.safe.EthereumClient") as mock_client_cls:
            mock_client_cls.return_value = MagicMock()

            client1 = get_ethereum_client("https://rpc1.example.com")
            client2 = get_ethereum_client("https://rpc1.example.com")

            assert client1 is client2
            # Should only create one instance
            assert mock_client_cls.call_count == 1

    def test_cache_different_urls(self):
        """Test that different URLs create different clients."""
        with patch("iwa.plugins.gnosis.safe.EthereumClient") as mock_client_cls:
            mock_client_cls.side_effect = lambda url: MagicMock(url=url)

            client1 = get_ethereum_client("https://rpc1.example.com")
            client2 = get_ethereum_client("https://rpc2.example.com")

            assert client1 is not client2
            assert mock_client_cls.call_count == 2

    def test_cache_limit_enforced(self):
        """Test that cache is limited to MAX_CACHED_CLIENTS."""
        with patch("iwa.plugins.gnosis.safe.EthereumClient") as mock_client_cls:
            # Create mock clients with closeable sessions
            def create_mock_client(url):
                client = MagicMock(url=url)
                client.w3 = MagicMock()
                client.w3.provider = MagicMock()
                client.w3.provider._request_kwargs = {"session": MagicMock()}
                return client

            mock_client_cls.side_effect = create_mock_client

            # Create more clients than the limit
            urls = [f"https://rpc{i}.example.com" for i in range(MAX_CACHED_CLIENTS + 2)]
            for url in urls:
                get_ethereum_client(url)

            # Cache should not exceed limit
            assert len(_ethereum_client_cache) <= MAX_CACHED_CLIENTS

    def test_cache_evicts_oldest(self):
        """Test that oldest entries are evicted when limit is reached."""
        with patch("iwa.plugins.gnosis.safe.EthereumClient") as mock_client_cls:

            def create_mock_client(url):
                client = MagicMock(url=url)
                client.w3 = MagicMock()
                client.w3.provider = MagicMock()
                client.w3.provider._request_kwargs = {"session": MagicMock()}
                return client

            mock_client_cls.side_effect = create_mock_client

            # Fill cache to limit
            first_url = "https://first.example.com"
            get_ethereum_client(first_url)
            for i in range(1, MAX_CACHED_CLIENTS):
                get_ethereum_client(f"https://rpc{i}.example.com")

            assert first_url in _ethereum_client_cache

            # Add one more - should evict the first
            get_ethereum_client("https://new.example.com")

            # First URL should be evicted
            assert first_url not in _ethereum_client_cache
            assert "https://new.example.com" in _ethereum_client_cache
