"""Plugin system architecture."""

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Dict, Optional, Type

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

    def get_tui_view(self, wallet=None) -> Optional["Widget"]:
        """Return a Textual Widget to be displayed in the TUI."""
        return None
