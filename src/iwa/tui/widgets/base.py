"""Custom widgets for the IWA TUI."""

from typing import List, Optional

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import (
    DataTable,
    Label,
    Select,
)

from iwa.core.chain import ChainInterfaces


class ChainSelector(Horizontal):
    """Widget for selecting the active blockchain."""

    def __init__(self, active_chain: str = "gnosis", id: Optional[str] = None):
        """Initialize ChainSelector.

        Args:
            active_chain: The chain to be selected by default.
            id: The widget ID.

        """
        super().__init__(id=id)
        self.active_chain = active_chain

    def compose(self) -> ComposeResult:
        """Compose the widget.

        Yields a Label and a Select widget populated with available chains.
        Chains without RPC endpoints are disabled/struck-through.
        """
        chain_options = []
        chain_names = ["gnosis", "ethereum", "base"]

        for name in chain_names:
            interface = ChainInterfaces().get(name)
            if interface.chain.rpc:
                label = name.title()
                chain_options.append((label, name))
            else:
                label = Text(f"{name.title()} (No RPC)", style="dim strike")
                chain_options.append((label, name))

        yield Label("Chain:", classes="label")
        yield Select(
            options=chain_options,
            value=self.active_chain,
            id="chain_select",
            allow_blank=False,
        )


class AccountTable(DataTable):
    """Table for displaying account addresses and balances."""

    def setup_columns(self, chain_name: str, native_symbol: str, token_names: List[str]):
        """Setup table columns dynamically based on chain and token list.

        Clears existing columns and adds new ones structure:
        Tag | Address | Type | Native Symbol | Token 1 | Token 2 ...

        Args:
            chain_name: Name of the current chain (unused in col setup but contextually relevant).
            native_symbol: Symbol of the native currency (e.g., ETH, xDAI).
            token_names: List of additional token names/symbols to display.

        """
        self.clear(columns=True)
        self.add_column("Tag", width=12)
        self.add_column("Address", width=44)
        self.add_column("Type", width=6)
        self.add_column(Text(native_symbol.upper(), justify="center"), width=12)

        for token_name in token_names:
            self.add_column(Text(f"{token_name.upper()}", justify="center"), width=12)


class TransactionTable(DataTable):
    """Table for displaying transaction history."""

    def setup_columns(self):
        """Setup initial table columns."""
        if not self.columns:
            self.add_column("Time", width=22)
            self.add_column("Chain", width=10)
            self.add_column("From", width=20)
            self.add_column("To", width=20)
            self.add_column("Token", width=10)
            self.add_column("Amount", width=12)
            self.add_column("Value (€)", width=12)
            self.add_column("Status", width=12)
            self.add_column("Hash", width=14)
            self.add_column("Gas (wei)", width=12)
            self.add_column("Gas (€)", width=10)
            self.add_column("Tags", width=20)
