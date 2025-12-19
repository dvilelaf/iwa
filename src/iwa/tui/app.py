"""Main TUI Application module."""

import datetime

from loguru import logger
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Footer, Header, TabbedContent, TabPane

from iwa.core.wallet import Wallet
from iwa.tui.rpc import RPCView
from iwa.tui.screens.wallets import WalletsScreen


def trace(msg):
    """Write debug trace."""
    try:
        with open("debug_trace.txt", "a") as f:
            ts = datetime.datetime.now().strftime("%H:%M:%S.%f")
            f.write(f"[APP] [{ts}] {msg}\n")
    except Exception:
        pass


class IwaApp(App):
    """Iwa TUI Application."""

    # ... (keep constants) ...
    TITLE = "Iwa"

    CSS = """
    .header {
        margin: 1 0;
        text-style: bold;
    }
    .form-row {
        height: 5;
        margin: 1 0;
        align: left middle;
    }
    .label {
        margin: 1 1;
        width: auto;
    }
    Input {
        width: 15;
        height: 3;
        margin-right: 1;
    }
    Select {
        width: 30;
        height: 3;
        margin-right: 1;
    }
    Button {
        margin-right: 1;
    }
    #chain_row {
        height: 3;
        margin: 1 0;
        align: left middle;
    }
    #chain_row Label {
        margin: 1 1;
        height: 1;
    }
    #tokens_row {
        height: 3;
        margin: 0 0;
    }
    #tokens_row Label {
        margin: 1 1;
        height: 1;
    }
    #token_toggles {
        height: 3;
        margin: 0 0;
    }
    #accounts_table {
        margin-top: 1;
        height: 1fr;
        min-height: 10;
    }
    #tx_table {
        height: 10;
    }
    Tab {
        width: 20;
    }
    .btn-group {
        width: 100%;
        height: auto;
        align: center middle;
        margin-top: 1;
        margin-bottom: 1;
    }
    .create-btn {
        margin-left: 1;
        margin-right: 1;
        width: auto;
        min-width: 20;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh", "Refresh"),
    ]

    def __init__(self):
        """Initialize the App."""
        trace("App INIT called")
        super().__init__()
        # Configure logger for TUI
        logger.remove()
        logger.add("iwa.log", rotation="10 MB", level="INFO")

        trace("App INIT: Loading Wallet...")
        self.wallet = Wallet()
        trace("App INIT: Wallet Loaded")

        # Use PluginService from wallet
        self.plugins = self.wallet.plugin_service.get_all_plugins()
        trace("App INIT: Plugins Loaded")

    def compose(self) -> ComposeResult:
        """Compose the App layout."""
        trace("App COMPOSE called")
        yield Header(show_clock=True)

        with TabbedContent():
            with TabPane("Wallets"):
                trace("App COMPOSE: Yielding WalletsScreen")
                yield WalletsScreen(self.wallet)

            with TabPane("RPC Status"):
                yield RPCView()

            # Dynamic Plugin Tabs
            for _name, plugin in self.plugins.items():
                view = plugin.get_tui_view()
                if view:
                    with TabPane(plugin.name.capitalize()):
                        yield view

        yield Footer()

    def action_refresh(self) -> None:
        """Refresh current view."""
        # Ideally, propagate refresh to active tab
        # For now, just refresh wallets view explicitly if it's there
        try:
            wallets_screen = self.query_one(WalletsScreen)
            wallets_screen.refresh_accounts()
        except Exception:
            pass

    def copy_to_clipboard(self, text: str) -> None:
        """Copy text to system clipboard using pyperclip."""
        try:
            import pyperclip

            pyperclip.copy(str(text))
        except Exception as e:
            logger.error(f"Failed to copy to clipboard: {e}")


if __name__ == "__main__":
    app = IwaApp()
    app.run()
