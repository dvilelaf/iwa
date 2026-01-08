import os
from unittest.mock import MagicMock, mock_open, patch

import pytest

from iwa.core.models import FundRequirements, TenderlyConfig, TokenAmount, VirtualNet
from iwa.tools.reset_tenderly import (
    _create_vnet,
    _delete_vnet,
    _fund_wallet,
    _generate_vnet_slug,
    main,
    update_rpc_variables,
)


@pytest.fixture
def mock_requests():
    with patch("iwa.tools.reset_tenderly.requests") as mock:
        import requests

        mock.exceptions.JSONDecodeError = requests.exceptions.JSONDecodeError
        yield mock


@pytest.fixture
def mock_tenderly_config():
    config = MagicMock(spec=TenderlyConfig)
    vnet = MagicMock(spec=VirtualNet)
    vnet.vnet_id = "old_id"
    vnet.chain_id = 1
    vnet.public_rpc = "https://rpc.com"
    vnet.admin_rpc = "https://admin.rpc.com"
    vnet.funds_requirements = {
        "tag1": FundRequirements(
            native_eth=1.0,
            tokens=[
                TokenAmount(
                    address="0x1234567890123456789012345678901234567890",
                    amount_eth=10.0,
                    symbol="TKN",
                )
            ],
        )
    }
    config.vnets = {"Gnosis": vnet}
    return config


def test_delete_vnet(mock_requests):
    _delete_vnet("key", "account", "project", "vnet_id")
    mock_requests.delete.assert_called_once()
    args, kwargs = mock_requests.delete.call_args
    assert "vnet_id" in kwargs["url"]
    assert kwargs["headers"]["X-Access-Key"] == "key"


def test_create_vnet(mock_requests):
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "id": "new_id",
        "rpcs": [
            {"name": "Admin RPC", "url": "admin_url"},
            {"name": "Public RPC", "url": "public_url"},
        ],
    }
    mock_requests.post.return_value = mock_response

    vnet_id, admin_rpc, public_rpc = _create_vnet("key", "account", "project", 1, 1, "slug", "name")

    assert vnet_id == "new_id"
    assert admin_rpc == "admin_url"
    assert public_rpc == "public_url"


def test_generate_vnet_slug():
    slug = _generate_vnet_slug("prefix", 5)
    assert slug.startswith("prefix-")
    assert len(slug) == len("prefix-") + 5


def test_update_rpc_variables(mock_tenderly_config):
    mock_file_content = "gnosis_test_rpc=old_url\nother_var=1"
    with patch("builtins.open", mock_open(read_data=mock_file_content)) as mock_file:
        update_rpc_variables(mock_tenderly_config)

        mock_file().write.assert_called_once()
        written_content = mock_file().write.call_args[0][0]
        assert "gnosis_test_rpc=https://rpc.com" in written_content


def test_update_rpc_variables_new(mock_tenderly_config):
    mock_file_content = "other_var=1"
    with patch("builtins.open", mock_open(read_data=mock_file_content)) as mock_file:
        update_rpc_variables(mock_tenderly_config)

        mock_file().write.assert_called_once()
        written_content = mock_file().write.call_args[0][0]
        assert "gnosis_test_rpc=https://rpc.com" in written_content


def test_fund_wallet_native(mock_requests):
    mock_requests.post.return_value.status_code = 200
    _fund_wallet("admin_url", ["0x1"], 1.0, "native")

    mock_requests.post.assert_called_once()
    kwargs = mock_requests.post.call_args[1]
    assert kwargs["json"]["method"] == "tenderly_setBalance"
    assert kwargs["json"]["params"][1] == hex(int(1e18))


def test_fund_wallet_token(mock_requests):
    mock_requests.post.return_value.status_code = 200
    _fund_wallet("admin_url", ["0x1"], 1.0, "0xToken")

    mock_requests.post.assert_called_once()
    kwargs = mock_requests.post.call_args[1]
    assert kwargs["json"]["method"] == "tenderly_setErc20Balance"
    assert kwargs["json"]["params"][0] == "0xToken"


def test_fund_wallet_error(mock_requests, capsys):
    mock_requests.post.return_value.status_code = 500
    mock_requests.post.return_value.json.return_value = {"error": "fail"}

    _fund_wallet("admin_url", ["0x1"], 1.0)

    captured = capsys.readouterr()
    assert "500" in captured.out
    assert "{'error': 'fail'}" in captured.out


def test_fund_wallet_json_error(mock_requests, capsys):
    import requests

    mock_requests.post.return_value.status_code = 500
    mock_requests.post.return_value.json.side_effect = requests.exceptions.JSONDecodeError(
        "msg", "doc", 0
    )

    _fund_wallet("admin_url", ["0x1"], 1.0)

    captured = capsys.readouterr()
    assert "500" in captured.out
    # Should not print json error
    assert "msg" not in captured.out


def test_main(mock_requests, mock_tenderly_config):
    # Mock env vars
    with patch.dict(
        os.environ,
        {
            "tenderly_account_slug": "acc",
            "tenderly_project_slug": "proj",
            "tenderly_access_key": "key",
        },
    ):
        # Mock TenderlyConfig.load
        with patch("iwa.core.models.TenderlyConfig.load", return_value=mock_tenderly_config):
            with patch(
                "iwa.tools.reset_tenderly.get_tenderly_credentials",
                return_value=("acc", "proj", "key"),
            ):
                # Mock KeyStorage
                with patch("iwa.tools.reset_tenderly.KeyStorage") as mock_key_storage:
                    mock_keys = mock_key_storage.return_value
                    mock_keys.get_account.return_value.address = "0xAddress"
                    mock_keys.accounts.keys.return_value = ["tag1"]

                    # Mock _create_vnet return values (since we mock requests, _create_vnet logic runs, but we can also mock _create_vnet directly)
                    # But let's let it run with mocked requests
                    mock_response_create = MagicMock()
                    mock_response_create.json.return_value = {
                        "id": "new_id",
                        "rpcs": [
                            {"name": "Admin RPC", "url": "admin"},
                            {"name": "Public RPC", "url": "public"},
                        ],
                    }

                    # Mock requests.post for create and fund
                    # We need side_effect to handle different calls
                    def post_side_effect(*args, **kwargs):
                        if "vnets" in kwargs.get("url", ""):
                            return mock_response_create
                        return MagicMock(status_code=200)

                    mock_requests.post.side_effect = post_side_effect

                    # Mock update_rpc_variables to avoid file I/O
                    with patch("iwa.tools.reset_tenderly.update_rpc_variables") as mock_update:
                        # Mock SafeService
                        with patch("iwa.core.services.SafeService") as mock_safe_service_cls:
                            main()

                            # Verify interactions
                            mock_requests.delete.assert_called()  # _delete_vnet
                            mock_tenderly_config.save.assert_called()
                            mock_update.assert_called()
                            # mock_keys.redeploy_safes.assert_called() # Removed
                            mock_safe_service_cls.return_value.redeploy_safes.assert_called()
