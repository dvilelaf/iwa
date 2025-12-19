import sys
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner


@pytest.fixture
def iwa_cli_module():
    mock_cowpy = MagicMock()
    modules_to_patch = {
        "cowdao_cowpy": mock_cowpy,
        "cowdao_cowpy.common": MagicMock(),
        "cowdao_cowpy.common.chains": MagicMock(),
        "cowdao_cowpy.app_data": MagicMock(),
        "cowdao_cowpy.app_data.utils": MagicMock(),
        "cowdao_cowpy.contracts": MagicMock(),
        "cowdao_cowpy.contracts.order": MagicMock(),
        "cowdao_cowpy.contracts.sign": MagicMock(),
        "cowdao_cowpy.cow": MagicMock(),
        "cowdao_cowpy.cow.swap": MagicMock(),
        "cowdao_cowpy.order_book": MagicMock(),
        "cowdao_cowpy.order_book.api": MagicMock(),
        "cowdao_cowpy.order_book.config": MagicMock(),
        "cowdao_cowpy.order_book.generated": MagicMock(),
        "cowdao_cowpy.order_book.generated.model": MagicMock(),
    }

    with patch.dict(sys.modules, modules_to_patch):
        if "iwa.core.cli" in sys.modules:
            del sys.modules["iwa.core.cli"]
        if "iwa.core.wallet" in sys.modules:
            pass

        with patch("iwa.core.wallet.Wallet"):
            import iwa.core.cli

            yield iwa.core.cli.iwa_cli


runner = CliRunner()


@pytest.fixture
def cli(iwa_cli_module):
    return iwa_cli_module


@pytest.fixture
def mock_key_storage():
    with patch("iwa.core.cli.KeyStorage") as mock:
        yield mock.return_value


@pytest.fixture
def mock_wallet():
    with patch("iwa.core.cli.Wallet") as mock:
        yield mock.return_value


def test_account_create(cli, mock_key_storage):
    result = runner.invoke(cli, ["wallet", "create", "--tag", "test"])
    assert result.exit_code == 0
    mock_key_storage.create_account.assert_called_with("test")


def test_account_create_error(cli, mock_key_storage):
    mock_key_storage.create_account.side_effect = ValueError("Error creating account")
    result = runner.invoke(cli, ["wallet", "create", "--tag", "test"])
    assert result.exit_code == 1
    assert "Error: Error creating account" in result.stdout


def test_account_list(cli, mock_wallet):
    mock_wallet.get_accounts_balances.return_value = ({}, None)
    with (
        patch("iwa.core.cli.list_accounts") as mock_list_accounts,
        patch("iwa.core.cli.ChainInterfaces"),
    ):
        result = runner.invoke(cli, ["wallet", "list", "--chain", "gnosis", "--balances", "native"])
        assert result.exit_code == 0
        mock_wallet.get_accounts_balances.assert_called_with("gnosis", ["native"])
        mock_list_accounts.assert_called_once()


def test_account_send(cli, mock_wallet):
    result = runner.invoke(
        cli, ["wallet", "send", "--from", "sender", "--to", "receiver", "--amount", "1.0"]
    )
    assert result.exit_code == 0
    mock_wallet.send.assert_called()


def test_erc20_transfer_from(cli, mock_wallet):
    result = runner.invoke(
        cli,
        [
            "wallet",
            "transfer-from",
            "--from",
            "from",
            "--sender",
            "sender",
            "--recipient",
            "recipient",
            "--token",
            "token",
            "--amount",
            "1.0",
        ],
    )
    assert result.exit_code == 0
    mock_wallet.transfer_from_erc20.assert_called()


def test_erc20_approve(cli, mock_wallet):
    result = runner.invoke(
        cli,
        [
            "wallet",
            "approve",
            "--owner",
            "owner",
            "--spender",
            "spender",
            "--token",
            "token",
            "--amount",
            "1.0",
        ],
    )
    assert result.exit_code == 0
    mock_wallet.approve_erc20.assert_called()


def test_drain_wallet(cli, mock_wallet):
    result = runner.invoke(cli, ["wallet", "drain", "--from", "from", "--to", "to"])
    assert result.exit_code == 0
    mock_wallet.drain.assert_called()
