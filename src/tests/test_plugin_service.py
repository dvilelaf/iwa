"""Tests for PluginService."""

from unittest.mock import MagicMock, patch

from iwa.core.plugins import Plugin
from iwa.core.services.plugin import PluginService


class MockPlugin(Plugin):
    """Mock plugin for testing."""

    @property
    def name(self):
        return "mock_plugin"

    def get_cli_commands(self):
        return {"mock": lambda: None}


def test_plugin_service_init():
    """Test PluginService initialization loads plugins."""
    with patch.object(PluginService, "_load_plugins"):
        service = PluginService()
        assert service.plugins_package == "iwa.plugins"


def test_discover_plugins_import_error():
    """Test _discover_plugins handles ImportError."""
    with patch.object(PluginService, "_load_plugins"):
        service = PluginService()

    with patch(
        "iwa.core.services.plugin.importlib.import_module",
        side_effect=ImportError("Module not found"),
    ):
        plugins = service._discover_plugins()
        assert plugins == []


def test_discover_plugins_no_path():
    """Test _discover_plugins handles package without __path__."""
    with patch.object(PluginService, "_load_plugins"):
        service = PluginService()

    with patch("iwa.core.services.plugin.importlib.import_module") as mock_import:
        mock_package = MagicMock(spec=[])  # No __path__
        del mock_package.__path__  # Ensure hasattr returns False
        mock_import.return_value = mock_package

        plugins = service._discover_plugins()
        assert plugins == []


def test_load_plugins_module_error():
    """Test _load_plugins handles module import errors."""
    with (
        patch.object(PluginService, "_discover_plugins", return_value=["bad_module"]),
        patch(
            "iwa.core.services.plugin.importlib.import_module",
            side_effect=ImportError("Bad module"),
        ),
    ):
        # Should not raise, just log error
        service = PluginService()

        assert "bad_module" not in service.loaded_plugins


def test_get_plugin():
    """Test get_plugin returns correct plugin."""
    with patch.object(PluginService, "_load_plugins"):
        service = PluginService()
        mock_plugin = MockPlugin()
        service.loaded_plugins["mock_plugin"] = mock_plugin

        result = service.get_plugin("mock_plugin")

        assert result == mock_plugin


def test_get_plugin_not_found():
    """Test get_plugin returns None for unknown plugin."""
    with patch.object(PluginService, "_load_plugins"):
        service = PluginService()

        result = service.get_plugin("nonexistent")

        assert result is None


def test_get_all_plugins():
    """Test get_all_plugins returns copy of plugins."""
    with patch.object(PluginService, "_load_plugins"):
        service = PluginService()
        mock_plugin = MockPlugin()
        service.loaded_plugins["mock_plugin"] = mock_plugin

        result = service.get_all_plugins()

        assert "mock_plugin" in result
        # Verify it's a copy
        result["new_plugin"] = None
        assert "new_plugin" not in service.loaded_plugins


def test_skip_already_loaded():
    """Test _load_plugins skips already loaded plugins."""
    with patch.object(PluginService, "_discover_plugins", return_value=["mock"]):
        with patch.object(PluginService, "_load_plugins"):
            service = PluginService()

        # Pre-populate loaded plugins with key matching discovered name
        mock_plugin = MockPlugin()
        service.loaded_plugins["mock"] = mock_plugin

        # Now load - should skip "mock" since it's in loaded_plugins
        with patch("iwa.core.services.plugin.importlib.import_module") as mock_import:
            service._load_plugins()
            mock_import.assert_not_called()
