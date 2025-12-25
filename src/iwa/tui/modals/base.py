"""Modal screens for the IWA TUI."""

from typing import List, Tuple

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    Input,
    Label,
    Select,
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


class StakeServiceModal(ModalScreen):
    """Modal screen for selecting a staking contract."""

    CSS = """
    StakeServiceModal {
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
    Select {
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

    def __init__(self, contracts: List[Tuple[str, str]]):
        """Init with list of (name, address) tuples."""
        super().__init__()
        self.contracts = contracts

    def compose(self) -> ComposeResult:
        """Compose the modal UI."""
        with Vertical(id="dialog"):
            yield Label("Stake Service", classes="header")
            yield Label("Select Staking Contract:")
            options = [(name, addr) for name, addr in self.contracts]
            yield Select(options, prompt="Select a contract...", id="contract_select")
            with Horizontal(id="btn_row"):
                yield Button("Cancel", id="cancel")
                yield Button("Stake", variant="primary", id="stake")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press."""
        if event.button.id == "stake":
            contract_address = self.query_one("#contract_select", Select).value
            if contract_address == Select.BLANK:
                return
            self.dismiss(contract_address)
        elif event.button.id == "cancel":
            self.dismiss(None)


class CreateServiceModal(ModalScreen):
    """Modal screen for creating a new Olas service."""

    CSS = """
    CreateServiceModal {
        align: center middle;
    }
    #dialog {
        padding: 1 2;
        width: 65;
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
    Input {
        width: 100%;
        margin-bottom: 2;
    }
    Select {
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

    def __init__(
        self,
        chains: List[str],
        default_chain: str = "gnosis",
        staking_contracts: List[Tuple[str, str]] = None,
    ):
        """Init with list of available chains and staking contracts."""
        super().__init__()
        self.chains = chains
        self.default_chain = default_chain
        self.staking_contracts = staking_contracts or []

    def compose(self) -> ComposeResult:
        """Compose the modal UI."""
        with Vertical(id="dialog"):
            yield Label("Create New Olas Service", classes="header")

            yield Label("Service Name:")
            yield Input(placeholder="e.g. My Trader", id="name_input")

            yield Label("Chain:")
            chain_options = [(c.title(), c) for c in self.chains]
            yield Select(chain_options, value=self.default_chain, id="chain_select")

            yield Label("Agent Type:")
            agent_options = [("Trader", "trader")]
            yield Select(agent_options, value="trader", id="agent_type_select")

            yield Label("Staking Contract:")
            contract_options = [("None (don't stake)", "")]
            contract_options.extend([(name, addr) for name, addr in self.staking_contracts])
            yield Select(contract_options, value="", id="staking_select")

            with Horizontal(id="btn_row"):
                yield Button("Cancel", id="cancel")
                yield Button("Create", variant="primary", id="create")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press."""
        if event.button.id == "create":
            name = self.query_one("#name_input", Input).value
            chain = self.query_one("#chain_select", Select).value
            agent_type = self.query_one("#agent_type_select", Select).value
            staking_contract = self.query_one("#staking_select", Select).value
            if not name or chain == Select.BLANK:
                return
            self.dismiss(
                {
                    "name": name,
                    "chain": chain,
                    "agent_type": agent_type if agent_type != Select.BLANK else "trader",
                    "staking_contract": staking_contract
                    if staking_contract != Select.BLANK
                    else None,
                }
            )
        elif event.button.id == "cancel":
            self.dismiss(None)


class FundServiceModal(ModalScreen):
    """Modal screen for funding Olas service accounts."""

    CSS = """
    FundServiceModal {
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
    .desc {
        color: $text-muted;
        margin-bottom: 2;
    }
    Input {
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

    def __init__(self, service_key: str, native_symbol: str = "xDAI"):
        """Init with service key and native currency symbol."""
        super().__init__()
        self.service_key = service_key
        self.native_symbol = native_symbol

    def compose(self) -> ComposeResult:
        """Compose the modal UI."""
        with Vertical(id="dialog"):
            yield Label("Fund Service", classes="header")
            yield Label(f"Send {self.native_symbol} from master wallet:", classes="desc")
            yield Label(f"Agent Amount ({self.native_symbol}):")
            yield Input(placeholder="0.0", id="agent_amount", type="number")
            yield Label(f"Safe Amount ({self.native_symbol}):")
            yield Input(placeholder="0.0", id="safe_amount", type="number")
            with Horizontal(id="btn_row"):
                yield Button("Cancel", id="cancel")
                yield Button("Fund", variant="primary", id="fund")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press."""
        if event.button.id == "fund":
            try:
                agent_amount = float(self.query_one("#agent_amount", Input).value or "0")
                safe_amount = float(self.query_one("#safe_amount", Input).value or "0")
            except ValueError:
                return
            if agent_amount <= 0 and safe_amount <= 0:
                return
            self.dismiss(
                {
                    "service_key": self.service_key,
                    "agent_amount": agent_amount,
                    "safe_amount": safe_amount,
                }
            )
        elif event.button.id == "cancel":
            self.dismiss(None)
