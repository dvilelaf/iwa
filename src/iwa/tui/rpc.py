"""RPC Status View module."""

import time
from typing import List

from textual import work
from textual.app import ComposeResult
from textual.widgets import DataTable, Label, Static

from iwa.core.chain import ChainInterfaces


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
        # Determine chains to check (hardcoded as per ChainInterfaces)
        chain_names = ["gnosis", "ethereum", "base"]
        results = []

        for chain_name in chain_names:
            # Get interface to access w3/rpc
            interface = ChainInterfaces().get(chain_name)
            if not interface:
                results.append((chain_name, "N/A", "Not Configured", "-"))
                continue

            rpc_url = interface.chain.rpc
            if not rpc_url:
                results.append((chain_name, "None", "Missing URL", "-"))
                continue

            try:
                start = time.time()
                is_connected = interface.web3.is_connected()
                latency = (time.time() - start) * 1000

                status = "Online" if is_connected else "Unreachable"
                results.append((chain_name, rpc_url, status, f"{latency:.2f}"))
            except Exception as e:
                results.append((chain_name, rpc_url, f"Error: {e}", "-"))

        self.app.call_from_thread(self.update_table, results)

    def update_table(self, results: List[tuple]) -> None:
        """Update the RPC status table."""
        table = self.query_one(DataTable)
        table.clear()
        for row in results:
            table.add_row(*row)
