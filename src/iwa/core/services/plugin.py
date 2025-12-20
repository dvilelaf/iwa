"""Plugin Service module."""

import importlib
import inspect
import pkgutil
from typing import Dict, List, Optional

from loguru import logger

from iwa.core.plugins import Plugin


class PluginService:
    """Manages plugin discovery, loading, and lifecycle."""

    def __init__(self, plugins_package: str = "iwa.plugins"):
        """Initialize PluginService.

        Args:
            plugins_package: Python package path to search for plugins.

        """
        self.plugins_package = plugins_package
        self.loaded_plugins: Dict[str, Plugin] = {}
        self._load_plugins()

    def _discover_plugins(self) -> List[str]:
        """Discover available plugins in the plugins package."""
        try:
            package = importlib.import_module(self.plugins_package)
            if not hasattr(package, "__path__"):
                return []

            return [name for _, name, is_pkg in pkgutil.iter_modules(package.__path__) if is_pkg]
        except ImportError:
            logger.warning(f"Could not import plugins package: {self.plugins_package}")
            return []

    def _load_plugins(self) -> None:
        """Load all discovered plugins."""
        from iwa.core.models import Config

        plugin_names = self._discover_plugins()
        config = Config()

        for name in plugin_names:
            if name in self.loaded_plugins:
                continue

            try:
                module_name = f"{self.plugins_package}.{name}"
                module = importlib.import_module(module_name)

                # Find Plugin subclass
                for _, obj in inspect.getmembers(module):
                    if inspect.isclass(obj) and issubclass(obj, Plugin) and obj is not Plugin:
                        try:
                            plugin_instance = obj()
                            # Verify unique name
                            if plugin_instance.name in self.loaded_plugins:
                                logger.warning(
                                    f"Plugin name collision: {plugin_instance.name}. Skipping."
                                )
                                continue

                            # Register plugin's config model if it has one
                            if plugin_instance.config_model:
                                config.register_plugin_config(
                                    plugin_instance.name, plugin_instance.config_model
                                )

                            self.loaded_plugins[plugin_instance.name] = plugin_instance
                            plugin_instance.on_load()
                            logger.info(f"Loaded plugin: {plugin_instance.name}")
                        except Exception as e:
                            logger.error(f"Failed to instantiate plugin {name}: {e}")

            except Exception as e:
                logger.error(f"Failed to load plugin module {name}: {e}")

    def get_plugin(self, name: str) -> Optional[Plugin]:
        """Get a loaded plugin by name."""
        return self.loaded_plugins.get(name)

    def get_all_plugins(self) -> Dict[str, Plugin]:
        """Get all loaded plugins."""
        # Return a copy to prevent modification
        return self.loaded_plugins.copy()
