from unittest.mock import patch

import pytest

from iwa.core.contracts.erc20 import ERC20Contract


@pytest.fixture
def mock_contract_instance():
    with (
        patch("iwa.core.contracts.contract.ContractInstance.__init__", return_value=None),
        patch("iwa.core.contracts.contract.ContractInstance.call") as mock_call,
        patch("iwa.core.contracts.contract.ContractInstance.prepare_transaction") as mock_prep,
    ):
        mock_call.side_effect = lambda method, *args: {
            "decimals": 18,
            "symbol": "TEST",
            "name": "Test Token",
            "totalSupply": 1000000,
            "allowance": 500,
            "balanceOf": 1000,
        }.get(method)

        yield mock_call, mock_prep


def test_init(mock_contract_instance):
    erc20 = ERC20Contract("0xToken", "gnosis")
    assert erc20.decimals == 18
    assert erc20.symbol == "TEST"
    assert erc20.name == "Test Token"
    assert erc20.total_supply == 1000000


def test_allowance_wei(mock_contract_instance):
    erc20 = ERC20Contract("0xToken", "gnosis")
    assert erc20.allowance_wei("0xOwner", "0xSpender") == 500


def test_allowance_eth(mock_contract_instance):
    erc20 = ERC20Contract("0xToken", "gnosis")
    # 500 wei / 10^18 is tiny
    assert erc20.allowance_eth("0xOwner", "0xSpender") == 500 / 10**18


def test_balance_of_wei(mock_contract_instance):
    erc20 = ERC20Contract("0xToken", "gnosis")
    assert erc20.balance_of_wei("0xAccount") == 1000


def test_balance_of_eth(mock_contract_instance):
    erc20 = ERC20Contract("0xToken", "gnosis")
    assert erc20.balance_of_eth("0xAccount") == 1000 / 10**18


def test_prepare_transfer_tx(mock_contract_instance):
    mock_call, mock_prep = mock_contract_instance
    mock_prep.return_value = {"data": "0x"}

    erc20 = ERC20Contract("0xToken", "gnosis")
    tx = erc20.prepare_transfer_tx("0xFrom", "0xTo", 100)
    assert tx == {"data": "0x"}
    mock_prep.assert_called_with(
        method_name="transfer",
        method_kwargs={"to": "0xTo", "amount": 100},
        tx_params={"from": "0xFrom"},
    )


def test_prepare_transfer_from_tx(mock_contract_instance):
    mock_call, mock_prep = mock_contract_instance
    mock_prep.return_value = {"data": "0x"}

    erc20 = ERC20Contract("0xToken", "gnosis")
    tx = erc20.prepare_transfer_from_tx("0xFrom", "0xSender", "0xRecipient", 100)
    assert tx == {"data": "0x"}
    mock_prep.assert_called_with(
        method_name="transferFrom",
        method_kwargs={"_sender": "0xSender", "_recipient": "0xRecipient", "_amount": 100},
        tx_params={"from": "0xFrom"},
    )


def test_prepare_approve_tx(mock_contract_instance):
    mock_call, mock_prep = mock_contract_instance
    mock_prep.return_value = {"data": "0x"}

    erc20 = ERC20Contract("0xToken", "gnosis")
    tx = erc20.prepare_approve_tx("0xFrom", "0xSpender", 100)
    assert tx == {"data": "0x"}
    mock_prep.assert_called_with(
        method_name="approve",
        method_kwargs={"spender": "0xSpender", "amount": 100},
        tx_params={"from": "0xFrom"},
    )
