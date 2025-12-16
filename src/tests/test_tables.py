from unittest.mock import MagicMock, patch

import pytest

from iwa.core.models import StoredAccount, StoredSafeAccount
from iwa.core.tables import list_accounts


@pytest.fixture
def mock_console():
    with patch("iwa.core.tables.Console") as mock:
        yield mock.return_value


@pytest.fixture
def mock_chain_interface():
    mock = MagicMock()
    mock.chain.native_currency = "ETH"
    return mock


def test_list_accounts_empty(mock_console, mock_chain_interface):
    list_accounts(None, mock_chain_interface, None, None)
    mock_console.print.assert_called_once()
    # Could verify table content but that's harder with mocks.
    # Just ensuring it runs without error and prints something is good for coverage.


def test_list_accounts_eoa(mock_console, mock_chain_interface):
    accounts = {
        "0x5B38Da6a701c568545dCfcB03FcB875f56beddC4": StoredAccount(
            address="0x5B38Da6a701c568545dCfcB03FcB875f56beddC4", tag="tag1"
        )
    }
    list_accounts(accounts, mock_chain_interface, None, None)
    mock_console.print.assert_called_once()


def test_list_accounts_safe(mock_console, mock_chain_interface):
    accounts = {
        "0x61a4f49e9dD1f90EB312889632FA956a21353720": StoredSafeAccount(
            address="0x61a4f49e9dD1f90EB312889632FA956a21353720",
            tag="tag2",
            signers=["0x5B38Da6a701c568545dCfcB03FcB875f56beddC4"],
            threshold=1,
            chains=["gnosis"],
        )
    }
    list_accounts(accounts, mock_chain_interface, None, None)
    mock_console.print.assert_called_once()


def test_list_accounts_with_tokens(mock_console, mock_chain_interface):
    accounts = {
        "0x5B38Da6a701c568545dCfcB03FcB875f56beddC4": StoredAccount(
            address="0x5B38Da6a701c568545dCfcB03FcB875f56beddC4", tag="tag1"
        )
    }
    token_names = ["native", "OLAS"]
    token_balances = {"0x5B38Da6a701c568545dCfcB03FcB875f56beddC4": {"native": 1.5, "OLAS": 100.0}}
    list_accounts(accounts, mock_chain_interface, token_names, token_balances)
    mock_console.print.assert_called_once()


def test_list_accounts_empty_with_tokens(mock_console, mock_chain_interface):
    token_names = ["native"]
    token_balances = {}  # Should be empty if no accounts
    list_accounts(None, mock_chain_interface, token_names, token_balances)
    mock_console.print.assert_called_once()


def test_list_accounts_no_accounts_but_tokens(mock_console, mock_chain_interface):
    token_names = ["native"]
    token_balances = {"0x5B38Da6a701c568545dCfcB03FcB875f56beddC4": {"native": 1.5}}
    list_accounts(None, mock_chain_interface, token_names, token_balances)
    mock_console.print.assert_called_once()
