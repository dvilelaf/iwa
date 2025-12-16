"""Plugin system architecture."""

import importlib
import inspect
import pkgutil
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Dict, List, Optional, Type

from pydantic import BaseModel

from iwa.core.utils import configure_logger

if TYPE_CHECKING:
    from textual.widget import Widget

logger = configure_logger()


class Plugin(ABC):
    """Abstract base class for plugins."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Plugin name."""
        pass

    @property
    def version(self) -> str:
        """Plugin version."""
        return "0.1.0"

    @property
    def config_model(self) -> Optional[Type[BaseModel]]:
        """Pydantic model for plugin configuration."""
        return None

    def get_cli_commands(self) -> Dict[str, callable]:
        """Return a dict of command_name: function to registers in CLI."""
        return {}

    def on_load(self) -> None:  # noqa: B027
        """Called when plugin is loaded."""
        pass

    def get_tui_view(self) -> Optional["Widget"]:
        """Return a Textual Widget to be displayed in the TUI."""
        return None


class PluginLoader:
    """Discovers and loads plugins."""

    def __init__(self, plugins_package: str = "iwa.plugins"):
        """Initialize loader."""
        self.plugins_package = plugins_package
        self.loaded_plugins: Dict[str, Plugin] = {}

    def discover_plugins(self) -> List[str]:
        """Discover available plugins in the plugins package."""
        try:
            package = importlib.import_module(self.plugins_package)
            if not hasattr(package, "__path__"):
                return []

            return [name for _, name, is_pkg in pkgutil.iter_modules(package.__path__) if is_pkg]
        except ImportError:
            logger.warning(f"Could not import plugins package: {self.plugins_package}")
            return []

    def load_plugins(self) -> Dict[str, Plugin]:
        """Load all discovered plugins."""
        plugin_names = self.discover_plugins()

        for name in plugin_names:
            try:
                module_name = f"{self.plugins_package}.{name}"
                module = importlib.import_module(module_name)

                # Find Plugin subclass
                for _, obj in inspect.getmembers(module):
                    if inspect.isclass(obj) and issubclass(obj, Plugin) and obj is not Plugin:
                        try:
                            plugin_instance = obj()
                            self.loaded_plugins[plugin_instance.name] = plugin_instance
                            plugin_instance.on_load()
                            logger.info(f"Loaded plugin: {plugin_instance.name}")
                        except Exception as e:
                            logger.error(f"Failed to instantiate plugin {name}: {e}")

            except Exception as e:
                logger.error(f"Failed to load plugin module {name}: {e}")

        return self.loaded_plugins
