"""RPC Status View module."""

from typing import List

from textual import work
from textual.app import ComposeResult
from textual.widgets import DataTable, Label, Static


class RPCView(Static):
    """View for monitoring RPC status."""

    def compose(self) -> ComposeResult:
        """Compose the RPC view layout."""
        yield Label("RPC Connections", classes="header")
        yield DataTable(id="rpc_table")

    def on_mount(self) -> None:
        """Initialize the view on mount."""
        table = self.query_one(DataTable)
        table.add_columns("Chain", "RPC URL", "Status", "Latency (ms)")
        self.check_rpcs()

    @work(exclusive=True, thread=True)
    def check_rpcs(self) -> None:
        """Check status of RPC endpoints in background."""
        # Determine chains to check.
        # This would typically come from config.
        # ... implementation ...
        pass

    def update_table(self, results: List[tuple]) -> None:
        """Update the RPC status table."""
        table = self.query_one(DataTable)
        table.clear()
        # ...
