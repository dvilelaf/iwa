"""Modal screens for the IWA TUI."""

from typing import List, Tuple

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    Input,
    Label,
    SelectionList,
)

from iwa.core.chain import ChainInterfaces


class CreateEOAModal(ModalScreen):
    """Modal screen for creating a new EOA wallet."""

    CSS = """
    CreateEOAModal {
        align: center middle;
    }
    #dialog {
        padding: 1 2;
        width: 60;
        height: auto;
        border: thick $background 80%;
        background: $surface;
    }
    #dialog Label {
        width: 100%;
        margin-bottom: 1;
    }
    .header {
        text-align: center;
        text-style: bold;
        margin-bottom: 2;
    }
    #tag_input {
        width: 100%;
        margin-bottom: 2;
    }
    #btn_row {
        height: 3;
        width: 100%;
        align: center middle;
    }
    Button {
        margin: 0 1;
    }
    """

    def compose(self) -> ComposeResult:
        """Compose the modal UI."""
        with Vertical(id="dialog"):
            yield Label("Create New EOA Wallet", classes="header")
            yield Label("Tag (Name):")
            yield Input(placeholder="e.g. My EOA", id="tag_input")
            with Horizontal(id="btn_row"):
                yield Button("Cancel", id="cancel")
                yield Button("Create", variant="primary", id="create")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press."""
        if event.button.id == "create":
            tag = self.query_one("#tag_input").value
            self.dismiss(tag)
        elif event.button.id == "cancel":
            self.dismiss(None)


class CreateSafeModal(ModalScreen):
    """Modal screen for creating a new Safe wallet."""

    CSS = """
    CreateSafeModal {
        align: center middle;
    }
    #dialog {
        padding: 1 2;
        width: 70;
        height: auto;
        max-height: 90%;
        border: thick $background 80%;
        background: $surface;
        overflow-y: auto;
    }
    #dialog Label {
        width: 100%;
        margin-bottom: 1;
    }
    .header {
        text-align: center;
        text-style: bold;
        margin-bottom: 2;
    }
    #tag_input {
        width: 100%;
        margin-bottom: 2;
    }
    #threshold_input {
        width: 100%;
        margin-bottom: 2;
    }
    SelectionList {
        height: 8;
        margin-bottom: 2;
        border: solid $secondary;
    }
    #btn_row {
        height: 3;
        width: 100%;
        align: center middle;
    }
    Button {
        margin: 0 1;
    }
    """

    def __init__(self, existing_accounts: List[Tuple[str, str]]):
        """Init with list of (tag, address) tuples."""
        super().__init__()
        self.existing_accounts = existing_accounts

    def compose(self) -> ComposeResult:
        """Compose the modal UI."""
        with Vertical(id="dialog"):
            yield Label("Create New Safe Wallet", classes="header")

            yield Label("Tag (Name):")
            yield Input(placeholder="e.g. My Safe", id="tag_input")

            yield Label("Threshold (Min signatures):")
            yield Input(placeholder="1", id="threshold_input", type="integer")

            yield Label("Owners (select multiple):")
            options = [(f"{tag} ({addr})", addr) for tag, addr in self.existing_accounts]
            yield SelectionList[str](*options, id="owners_list")

            yield Label("Chains (select multiple):")
            chain_options = [(name.title(), name) for name, _ in ChainInterfaces().items()]
            yield SelectionList[str](*chain_options, id="chains_list")

            with Horizontal(id="btn_row"):
                yield Button("Cancel", id="cancel")
                yield Button("Create", variant="primary", id="create")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press."""
        if event.button.id == "create":
            tag = self.query_one("#tag_input", Input).value
            threshold = int(self.query_one("#threshold_input", Input).value or "1")
            owners = self.query_one("#owners_list", SelectionList).selected
            chains = self.query_one("#chains_list", SelectionList).selected
            self.dismiss({"tag": tag, "threshold": threshold, "owners": owners, "chains": chains})
        elif event.button.id == "cancel":
            self.dismiss(None)
