"""Tests for SafeService."""
from unittest.mock import MagicMock, patch

import pytest
from eth_account import Account

from iwa.core.keys import EncryptedAccount, KeyStorage
from iwa.core.models import StoredSafeAccount
from iwa.core.services.account import AccountService
from iwa.core.services.safe import SafeService


@pytest.fixture
def mock_key_storage():
    """Mock KeyStorage."""
    ks = MagicMock(spec=KeyStorage)
    ks.accounts = {}
    return ks


@pytest.fixture
def mock_account_service():
    """Mock AccountService."""
    return MagicMock(spec=AccountService)


@pytest.fixture
def safe_service(mock_key_storage, mock_account_service):
    """SafeService fixture."""
    return SafeService(mock_key_storage, mock_account_service)


def test_create_safe_deployer_not_found(safe_service, mock_key_storage):
    """Test create_safe when deployer not found."""
    mock_key_storage.find_stored_account.return_value = None
    with pytest.raises(ValueError, match="Deployer account 'deployer' not found"):
        safe_service.create_safe("deployer", ["owner"], 1, "gnosis")


def test_create_safe_deployer_is_safe(safe_service, mock_key_storage):
    """Test create_safe when deployer is a Safe."""
    # Use valid addresses
    valid_addr_1 = "0x5B38Da6a701c568545dCfcB03FcB875f56beddC4"

    mock_key_storage.find_stored_account.return_value = StoredSafeAccount(
        tag="safe", address=valid_addr_1, chains=["gnosis"], threshold=1, signers=[]
    )
    with pytest.raises(ValueError, match="Deployer account 'deployer' .* is a Safe"):
        safe_service.create_safe("deployer", ["owner"], 1, "gnosis")


def test_create_safe_owner_not_found(safe_service, mock_key_storage):
    """Test create_safe when owner not found."""
    deployer = MagicMock(spec=EncryptedAccount)
    deployer.address = "0x5B38Da6a701c568545dCfcB03FcB875f56beddC4"

    # First call for deployer found, second call for owner returns None
    def side_effect(arg):
        if arg == "deployer":
            return deployer
        return None

    mock_key_storage.find_stored_account.side_effect = side_effect
    # Use valid 32 byte key hex
    mock_key_storage._get_private_key.return_value = "0x" + "1" * 64

    with pytest.raises(ValueError, match="Owner account 'owner' not found"):
        safe_service.create_safe("deployer", ["owner"], 1, "gnosis")


@patch("iwa.core.services.safe.EthereumClient")
@patch("iwa.core.services.safe.Safe")
@patch("iwa.core.services.safe.settings")
def test_create_safe_success(mock_settings, mock_safe_cls, mock_eth_client, safe_service, mock_key_storage, mock_account_service):
    """Test create_safe success path."""
    deployer = MagicMock(spec=EncryptedAccount)
    deployer.address = "0x5B38Da6a701c568545dCfcB03FcB875f56beddC4"

    owner = MagicMock(spec=EncryptedAccount)
    owner.address = "0x78731D3Ca6b7E34aC0F824c42a7cC18A495cabaB"

    mock_key_storage.find_stored_account.side_effect = lambda x: deployer if x == "deployer" else owner
    mock_key_storage._get_private_key.return_value = Account.create().key.hex()
    mock_key_storage.accounts = {}

    # Mock Safe creation
    mock_safe_instance = MagicMock()
    mock_safe_cls.create.return_value = mock_safe_instance
    mock_safe_instance.contract_address = "0x617F2E2fD72FD9D5503197092aC168c91465E7f2"
    mock_safe_instance.tx_hash.hex.return_value = "0xTxHash"

    mock_account_service.get_tag_by_address.return_value = "deployer_tag"

    safe_account, tx_hash = safe_service.create_safe("deployer", ["owner"], 1, "gnosis", tag="MySafe")

    assert safe_account.address == "0x617F2E2fD72FD9D5503197092aC168c91465E7f2"
    assert safe_account.tag == "MySafe"
    assert tx_hash == "0xTxHash"

    # Verify save called
    mock_key_storage.save.assert_called_once()
    assert "0x617F2E2fD72FD9D5503197092aC168c91465E7f2" in mock_key_storage.accounts



def test_get_signer_keys_not_safe(safe_service, mock_key_storage):
    """Test _get_signer_keys when target is not a safe."""
    # _get_signer_keys now takes a StoredSafeAccount directly
    non_safe = MagicMock(spec=EncryptedAccount)
    # Should raise TypeError since method expects StoredSafeAccount
    with pytest.raises(AttributeError):
        safe_service._get_signer_keys(non_safe)


def test_get_signer_keys_not_enough_signers(safe_service, mock_key_storage):
    """Test _get_signer_keys when not enough keys available."""
    valid_addr_1 = "0x5B38Da6a701c568545dCfcB03FcB875f56beddC4"
    valid_addr_2 = "0x78731D3Ca6b7E34aC0F824c42a7cC18A495cabaB"
    valid_addr_3 = "0x617F2E2fD72FD9D5503197092aC168c91465E7f2"

    safe = StoredSafeAccount(
        tag="safe", address=valid_addr_1, chains=["gnosis"], threshold=2, signers=[valid_addr_2, valid_addr_3]
    )

    # Only one key available
    mock_key_storage._get_private_key.side_effect = lambda addr: "0xKey1" if addr == valid_addr_2 else None

    with pytest.raises(ValueError, match="Not enough signer private keys"):
        safe_service._get_signer_keys(safe)


@patch("iwa.plugins.gnosis.safe.SafeMultisig")
def test_execute_safe_transaction_success(mock_safe_multisig, safe_service, mock_key_storage):
    """Test execute_safe_transaction success."""
    valid_addr_1 = "0x5B38Da6a701c568545dCfcB03FcB875f56beddC4"
    valid_addr_2 = "0x78731D3Ca6b7E34aC0F824c42a7cC18A495cabaB"

    safe = StoredSafeAccount(
        tag="safe", address=valid_addr_1, chains=["gnosis"], threshold=1, signers=[valid_addr_2]
    )
    mock_key_storage.find_stored_account.return_value = safe
    mock_key_storage._get_private_key.return_value = "0xKey1"

    # Mock SafeMultisig and its methods
    mock_safe_instance = MagicMock()
    mock_safe_multisig.return_value = mock_safe_instance
    mock_safe_tx = MagicMock()
    mock_safe_tx.tx_hash.hex.return_value = "0xTxHash123"
    mock_safe_instance.build_tx.return_value = mock_safe_tx

    result = safe_service.execute_safe_transaction(
        safe_address_or_tag="safe",
        to="0x0000000000000000000000000000000000000001",
        value=1000,
        chain_name="gnosis",
    )

    assert result == "0xTxHash123"
    mock_safe_instance.build_tx.assert_called_once()
    mock_safe_tx.sign.assert_called_with("0xKey1")
    mock_safe_tx.call.assert_called_once()
    mock_safe_tx.execute.assert_called_with("0xKey1")
