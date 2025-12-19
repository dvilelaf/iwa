"""Tests for AccountService."""

from unittest.mock import MagicMock

import pytest

from iwa.core.constants import NATIVE_CURRENCY_ADDRESS
from iwa.core.models import EthereumAddress, StoredSafeAccount
from iwa.core.services.account import AccountService


@pytest.fixture
def mock_key_storage():
    mock = MagicMock()
    mock.master_account = StoredSafeAccount(
        tag="master",
        address="0x1111111111111111111111111111111111111111",
        chains=["gnosis"],
        threshold=1,
        signers=["0x2222222222222222222222222222222222222222"],
    )
    mock.get_account.return_value = MagicMock(address="0x1234")
    mock.get_tag_by_address.return_value = "my_tag"
    mock.accounts = {}
    return mock


@pytest.fixture
def account_service(mock_key_storage):
    return AccountService(mock_key_storage)


def test_init(account_service, mock_key_storage):
    """Test AccountService initialization."""
    assert account_service.key_storage == mock_key_storage


def test_master_account(account_service, mock_key_storage):
    """Test master_account property."""
    result = account_service.master_account

    assert result == mock_key_storage.master_account
    assert result.tag == "master"


def test_get_token_address_native(account_service):
    """Test get_token_address returns native address."""
    mock_chain = MagicMock()

    result = account_service.get_token_address("native", mock_chain)

    assert result == EthereumAddress(NATIVE_CURRENCY_ADDRESS)


def test_get_token_address_valid_address(account_service):
    """Test get_token_address with valid Ethereum address."""
    mock_chain = MagicMock()
    valid_address = "0x1234567890123456789012345678901234567890"

    result = account_service.get_token_address(valid_address, mock_chain)

    assert result == EthereumAddress(valid_address)


def test_get_token_address_by_name(account_service):
    """Test get_token_address resolves token name."""
    mock_chain = MagicMock()
    mock_chain.get_token_address.return_value = EthereumAddress(
        "0x6B175474E89094C44Da98b954EedeAC495271E01"
    )

    result = account_service.get_token_address("DAI", mock_chain)

    assert result == EthereumAddress("0x6B175474E89094C44Da98b954EedeAC495271E01")
    mock_chain.get_token_address.assert_called_with("DAI")


def test_get_token_address_not_found(account_service):
    """Test get_token_address returns None for unknown token."""
    mock_chain = MagicMock()
    mock_chain.name = "gnosis"
    mock_chain.get_token_address.return_value = None

    result = account_service.get_token_address("UNKNOWN", mock_chain)

    assert result is None


def test_resolve_account(account_service, mock_key_storage):
    """Test resolve_account delegates to key_storage."""
    result = account_service.resolve_account("my_tag")

    mock_key_storage.get_account.assert_called_with("my_tag")
    assert result.address == "0x1234"


def test_resolve_account_not_found(account_service, mock_key_storage):
    """Test resolve_account returns None for unknown account."""
    mock_key_storage.get_account.return_value = None

    result = account_service.resolve_account("unknown")

    assert result is None


def test_get_tag_by_address(account_service, mock_key_storage):
    """Test get_tag_by_address delegates to key_storage."""
    result = account_service.get_tag_by_address("0x1234")

    mock_key_storage.get_tag_by_address.assert_called_with("0x1234")
    assert result == "my_tag"


def test_get_account_data(account_service, mock_key_storage):
    """Test get_account_data returns accounts dict."""
    mock_key_storage.accounts = {"0x1234": MagicMock()}

    result = account_service.get_account_data()

    assert result == mock_key_storage.accounts
