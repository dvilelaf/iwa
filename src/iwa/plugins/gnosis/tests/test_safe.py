"""Tests for Safe module."""

from unittest.mock import MagicMock, patch

import pytest

from iwa.core.models import StoredSafeAccount
from iwa.plugins.gnosis.safe import SafeMultisig


@pytest.fixture
def mock_settings():
    """Mock settings."""
    with patch("iwa.plugins.gnosis.safe.settings") as mock:
        mock.gnosis_rpc.get_secret_value.return_value = "http://rpc"
        yield mock


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
