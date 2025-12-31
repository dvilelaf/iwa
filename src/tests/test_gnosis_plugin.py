"""Tests for Gnosis Plugin."""

from unittest.mock import patch

import pytest
import typer

from iwa.plugins.gnosis.plugin import GnosisPlugin


@pytest.fixture
def plugin():
    return GnosisPlugin()


def test_plugin_name(plugin):
    """Test plugin name property."""
    assert plugin.name == "gnosis"


def test_get_cli_commands(plugin):
    """Test get_cli_commands returns correct commands."""
    commands = plugin.get_cli_commands()

    assert "create-safe" in commands
    assert callable(commands["create-safe"])


def test_create_safe_command_success(plugin):
    """Test create_safe_command with successful creation."""
    with (
        patch("iwa.plugins.gnosis.plugin.KeyStorage"),
        patch("iwa.core.services.AccountService"),
        patch("iwa.core.services.SafeService") as mock_safe_service,
    ):
        mock_safe_service.return_value.create_safe.return_value = "0xSafeAddress"

        # Call the command directly
        plugin.create_safe_command(
            tag="my_safe",
            owners="owner1,owner2",
            threshold=2,
            chain_name="gnosis",
        )

        mock_safe_service.return_value.create_safe.assert_called_once_with(
            deployer_tag_or_address="master",
            owner_tags_or_addresses=["owner1", "owner2"],
            threshold=2,
            chain_name="gnosis",
            tag="my_safe",
        )


def test_create_safe_command_error(plugin):
    """Test create_safe_command handles ValueError."""
    with (
        patch("iwa.plugins.gnosis.plugin.KeyStorage"),
        patch("iwa.core.services.AccountService"),
        patch("iwa.core.services.SafeService") as mock_safe_service,
    ):
        mock_safe_service.return_value.create_safe.side_effect = ValueError("Owner not found")

        with pytest.raises(typer.Exit) as exc_info:
            plugin.create_safe_command(
                tag="my_safe",
                owners="unknown_owner",
                threshold=1,
                chain_name="gnosis",
            )

        assert exc_info.value.exit_code == 1


def test_create_safe_command_no_tag(plugin):
    """Test create_safe_command without tag."""
    with (
        patch("iwa.plugins.gnosis.plugin.KeyStorage"),
        patch("iwa.core.services.AccountService"),
        patch("iwa.core.services.SafeService") as mock_safe_service,
    ):
        mock_safe_service.return_value.create_safe.return_value = "0xSafeAddress"

        plugin.create_safe_command(
            tag=None,
            owners="owner1",
            threshold=1,
            chain_name="gnosis",
        )

        mock_safe_service.return_value.create_safe.assert_called_once()
        call_kwargs = mock_safe_service.return_value.create_safe.call_args[1]
        assert call_kwargs["tag"] is None


def test_create_safe_command_multiple_owners(plugin):
    """Test create_safe_command with multiple owners."""
    with (
        patch("iwa.plugins.gnosis.plugin.KeyStorage"),
        patch("iwa.core.services.AccountService"),
        patch("iwa.core.services.SafeService") as mock_safe_service,
    ):
        plugin.create_safe_command(
            tag="multi_safe",
            owners="owner1, owner2, owner3",  # With spaces
            threshold=2,
            chain_name="gnosis",
        )

        call_kwargs = mock_safe_service.return_value.create_safe.call_args[1]
        assert call_kwargs["owner_tags_or_addresses"] == ["owner1", "owner2", "owner3"]
