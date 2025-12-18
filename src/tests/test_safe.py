import sys
from unittest.mock import MagicMock, patch

import pytest

# Mock safe_eth before importing SafeMultisig
sys.modules["safe_eth"] = MagicMock()
sys.modules["safe_eth.eth"] = MagicMock()
sys.modules["safe_eth.eth.constants"] = MagicMock()
sys.modules["safe_eth.safe"] = MagicMock()

from iwa.core.models import StoredSafeAccount
from iwa.plugins.gnosis.safe import SafeMultisig


@pytest.fixture
def mock_secrets():
    with patch("iwa.plugins.gnosis.safe.settings") as mock:
        mock.gnosis_rpc.get_secret_value.return_value = "http://rpc"
        yield mock


@pytest.fixture
def mock_safe_account():
    account = MagicMock(spec=StoredSafeAccount)
    account.address = "0xSafe"
    account.chains = ["gnosis"]
    return account


@pytest.fixture
def mock_safe_lib():
    with (
        patch("iwa.plugins.gnosis.safe.Safe") as mock_safe,
        patch("iwa.plugins.gnosis.safe.EthereumClient") as mock_client,
    ):
        yield mock_safe, mock_client


def test_init_success(mock_safe_account, mock_secrets, mock_safe_lib):
    safe = SafeMultisig(mock_safe_account, "gnosis")
    assert safe.multisig is not None
    mock_safe_lib[1].assert_called_with("http://rpc")  # EthereumClient
    mock_safe_lib[0].assert_called_with("0xSafe", mock_safe_lib[1].return_value)  # Safe


def test_init_invalid_chain(mock_safe_account, mock_secrets):
    with pytest.raises(ValueError, match="Safe account is not deployed on chain"):
        SafeMultisig(mock_safe_account, "ethereum")


def test_get_owners(mock_safe_account, mock_secrets, mock_safe_lib):
    safe = SafeMultisig(mock_safe_account, "gnosis")
    safe.multisig.retrieve_owners.return_value = ["0xOwner"]
    assert safe.get_owners() == ["0xOwner"]


def test_get_threshold(mock_safe_account, mock_secrets, mock_safe_lib):
    safe = SafeMultisig(mock_safe_account, "gnosis")
    safe.multisig.retrieve_threshold.return_value = 2
    assert safe.get_threshold() == 2


def test_get_nonce(mock_safe_account, mock_secrets, mock_safe_lib):
    safe = SafeMultisig(mock_safe_account, "gnosis")
    safe.multisig.retrieve_nonce.return_value = 5
    assert safe.get_nonce() == 5


def test_retrieve_all_info(mock_safe_account, mock_secrets, mock_safe_lib):
    safe = SafeMultisig(mock_safe_account, "gnosis")
    safe.multisig.retrieve_all_info.return_value = {"owners": []}
    assert safe.retrieve_all_info() == {"owners": []}


def test_send_tx(mock_safe_account, mock_secrets, mock_safe_lib):
    safe = SafeMultisig(mock_safe_account, "gnosis")
    mock_tx = MagicMock()
    safe.multisig.build_multisig_tx.return_value = mock_tx
    mock_tx.tx_hash.hex.return_value = "0xHash"

    safe.send_tx(to="0xTo", value=100, signers_private_keys=["key1", "key2"], data="0x1234")

    safe.multisig.build_multisig_tx.assert_called()
    assert mock_tx.sign.call_count == 2
    mock_tx.call.assert_called_once()
    mock_tx.execute.assert_called_with("key1")
