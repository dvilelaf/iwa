"""Tests for Olas Plugin."""

from unittest.mock import MagicMock, patch

from iwa.plugins.olas.models import OlasConfig
from iwa.plugins.olas.plugin import OlasPlugin


class TestOlasPlugin:
    """Tests for OlasPlugin class."""

    def test_name_property(self):
        """Test plugin name property."""
        plugin = OlasPlugin()
        assert plugin.name == "olas"

    def test_config_model_returns_olas_config(self):
        """Test config_model property returns OlasConfig."""
        plugin = OlasPlugin()
        assert plugin.config_model == OlasConfig

    def test_get_cli_commands(self):
        """Test get_cli_commands returns dict with commands."""
        plugin = OlasPlugin()
        commands = plugin.get_cli_commands()

        assert isinstance(commands, dict)
        assert "create" in commands
        assert callable(commands["create"])

    @patch("iwa.plugins.olas.plugin.Wallet")
    @patch("iwa.plugins.olas.plugin.ServiceManager")
    def test_create_service(self, mock_sm_class, mock_wallet_class):
        """Test create_service calls ServiceManager.create."""
        mock_wallet = MagicMock()
        mock_wallet_class.return_value = mock_wallet

        mock_manager = MagicMock()
        mock_sm_class.return_value = mock_manager

        plugin = OlasPlugin()
        plugin.create_service(
            chain_name="gnosis",
            owner="0x1234",
            token="OLAS",
            bond=100,
        )

        mock_wallet_class.assert_called_once()
        mock_sm_class.assert_called_once_with(mock_wallet)
        mock_manager.create.assert_called_once_with("gnosis", "0x1234", "OLAS", 100)

    @patch("iwa.plugins.olas.plugin.Wallet")
    @patch("iwa.plugins.olas.plugin.ServiceManager")
    def test_create_service_defaults(self, mock_sm_class, mock_wallet_class):
        """Test create_service with default parameters."""
        mock_wallet = MagicMock()
        mock_wallet_class.return_value = mock_wallet

        mock_manager = MagicMock()
        mock_sm_class.return_value = mock_manager

        plugin = OlasPlugin()
        # Note: when called directly (not via typer), defaults are OptionInfo objects
        # so we can only verify the method was called
        plugin.create_service()

        mock_wallet_class.assert_called_once()
        mock_sm_class.assert_called_once_with(mock_wallet)
        mock_manager.create.assert_called_once()  # Any arguments
