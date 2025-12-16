"""TUI Views for the IWA application."""

import datetime
import threading
from typing import List, Tuple

try:
    with open("debug_trace.txt", "w") as f:
        f.write("MODULE_LOADED\n")
except Exception:
    pass

from rich.text import Text
from textual import on, work
from textual.app import ComposeResult
from textual.containers import Center, Horizontal, HorizontalScroll, Vertical
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    Checkbox,
    DataTable,
    Input,
    Label,
    RadioButton,
    RadioSet,
    Select,
)

from iwa.core.chain import ChainInterfaces
from iwa.core.models import Config, StoredSafeAccount
from iwa.core.monitor import EventMonitor
from iwa.core.pricing import PriceService
from iwa.core.utils import configure_logger
from iwa.core.wallet import Wallet

logger = configure_logger()


def trace(msg):
    """Write a debug trace message to a file."""
    try:
        with open("debug_trace.txt", "a") as f:
            ts = datetime.datetime.now().strftime("%H:%M:%S.%f")
            f.write(f"[{ts}] {msg}\n")
    except Exception:
        pass


def run_monitor_thread(monitor: EventMonitor):
    """Start the event monitor in a daemon thread."""
    t = threading.Thread(target=monitor.start, daemon=True)
    t.start()
    return t


class CreateAddressModal(ModalScreen):
    """Modal screen for creating a new wallet/address."""

    CSS = """
    CreateAddressModal {
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
    #type_radio {
        width: 100%;
        margin-bottom: 2;
    }
    #btn_row {
        height: 3;
        width: 100%;
        align: center middle;
    }
    RadioButton {
        width: 100%;
        padding-left: 1;
    }
    Button {
        margin: 0 1;
    }
    """

    def compose(self) -> ComposeResult:
        """Compose the modal UI."""
        with Vertical(id="dialog"):
            yield Label("Create New Wallet", classes="header")

            # Tag Input
            yield Label("Tag (Name):")
            yield Input(placeholder="e.g. My Wallet", id="tag_input")

            # Type Selection
            yield Label("Type:")
            with RadioSet(id="type_radio"):
                yield RadioButton("Standard (EOA)", value=True, id="eoa")
                yield RadioButton("Safe (Multisig)", id="safe")

            # Buttons
            with Horizontal(id="btn_row"):
                yield Button("Cancel", id="cancel")
                yield Button("Create", variant="primary", id="create")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press in modal."""
        if event.button.id == "create":
            tag = self.query_one("#tag_input").value
            is_safe = self.query_one("#safe").value
            self.dismiss((tag, is_safe))
        elif event.button.id == "cancel":
            self.dismiss(None)


class WalletsView(Vertical):
    """View for managing wallets."""

    BINDINGS = [
        ("r", "refresh", "Refresh Balances"),
    ]

    def __init__(self, wallet: Wallet):
        """Initialize WalletsView."""
        trace("WalletsView INIT called")
        super().__init__()
        self.wallet = wallet
        self.active_chain = "gnosis"
        self.monitor = None
        # Stores set of checked tokens (names) per chain
        self.chain_token_states: dict[str, set[str]] = {
            "gnosis": set(),
            "ethereum": set(),
            "base": set(),
        }
        self.balance_cache = {}  # chain -> address -> balances
        self.tx_history = []  # List of (from, to, token, amt, status)
        self.price_service = PriceService()

    async def on_mount(self) -> None:
        """Called when view is mounted."""
        # Initialize UI state
        await self.refresh_ui_for_chain()
        self.start_monitor()

        # Setup Tx Table
        tx_table = self.query_one("#tx_table", DataTable)
        tx_table.add_column("Time", width=22)
        tx_table.add_column("From", width=20)
        tx_table.add_column("To", width=20)
        tx_table.add_column("Token", width=10)
        tx_table.add_column("Amount", width=12)
        tx_table.add_column("Status", width=12)

        # Load recent txs
        self.load_recent_txs()

    def compose(self) -> ComposeResult:
        """Compose the WalletsView UI."""
        try:
            trace("COMPOSE called")
            # Chain Selector
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

            yield Horizontal(
                Label("Chain:", classes="label"),
                Select(
                    options=chain_options,
                    value=self.active_chain,  # Default from init
                    id="chain_select",
                    allow_blank=False,
                ),
                id="chain_row",
            )

            yield Label(
                f"Accounts ({self.active_chain.capitalize()})",
                classes="header",
                id="accounts_header",
            )

            # Token Selection (Checkboxes)
            yield Label("Track Tokens:", classes="label")
            with HorizontalScroll(id="tokens_row"):
                yield Horizontal(id="token_toggles")

            # Accounts Table
            yield DataTable(id="accounts_table")
            # Button for creating new wallets
            with Center():
                yield Button(
                    "Create Wallet",
                    id="create_address_btn",
                    variant="primary",
                    classes="create-btn",
                )
            trace("COMPOSE finished yielding")
        except Exception as e:
            trace(f"COMPOSE CRASHED: {e}")
            logger.error(f"COMPOSE CRASHED: {e}")
            raise e

        yield Label("Send Transaction", classes="header")

        # Transaction Form
        with Horizontal(classes="form-row", id="tx_form_container"):
            # Initial placeholder, will be cleared/replaced
            yield Label("Loading form...", id="form_loading_lbl")

        yield Label("Recent Transactions", classes="header")
        yield DataTable(id="tx_table")

    def action_refresh(self) -> None:
        """Manual refresh action."""
        self.notify("Refreshing accounts...", severity="info")
        self.refresh_accounts(force=True)

    def refresh_accounts(self, force: bool = False) -> None:
        """Refreshes table data."""
        # Force clears cache entries for current chain addresses
        if force:
            if self.active_chain in self.balance_cache:
                self.balance_cache[self.active_chain] = {}

        self.refresh_table_structure_and_data()

        # Update Recent Transactions
        tx_table = self.query_one("#tx_table", DataTable)
        tx_table.clear()

        for tx in reversed(self.tx_history):
            tx_table.add_row(*tx)

    def refresh_table_structure_and_data(self) -> None:  # noqa: C901
        """Rebuild the accounts table structure and data."""
        table = self.query_one("#accounts_table", DataTable)
        table.clear(columns=True)
        chain_interface = ChainInterfaces().get(self.active_chain)
        native_symbol = chain_interface.chain.native_currency if chain_interface else "Native"
        table.add_column("Tag", width=12)
        table.add_column("Address", width=44)
        table.add_column("Type", width=6)
        table.add_column(native_symbol.upper(), width=12)

        # Add all token columns available on this chain
        token_names = []
        if chain_interface:
            for token_name in chain_interface.tokens.keys():
                table.add_column(f"{token_name.upper()}", width=12)
                token_names.append(token_name)

        # Populate Rows
        current_chain = self.active_chain  # Capture for workers
        logger.info(f"Refeshing table for {current_chain}...")

        # Ensure cache exists for this chain
        if current_chain not in self.balance_cache:
            self.balance_cache[current_chain] = {}

        needs_fetch = False

        for account in self.wallet.key_storage.accounts.values():
            acct_type = "Safe" if isinstance(account, StoredSafeAccount) else "EOA"
            row_key = account.address

            # Ensure cache exists for this address
            if account.address not in self.balance_cache[current_chain]:
                self.balance_cache[current_chain][account.address] = {}

            # 1. Native Balance
            cached_native = self.balance_cache[current_chain][account.address].get("NATIVE")
            if cached_native:
                native_cell = cached_native
            else:
                native_cell = "Loading..."
                needs_fetch = True

            cells = [Text(account.tag, style="green"), account.address, acct_type, native_cell]

            # 2. Token Balances
            for _i, token in enumerate(token_names):
                if token in self.chain_token_states.get(current_chain, set()):
                    cached_token = self.balance_cache[current_chain][account.address].get(token)
                    if cached_token:
                        cells.append(cached_token)
                    else:
                        cells.append("Loading...")
                        # If a token is visible but not cached, we need a fetch
                        needs_fetch = True
                else:
                    cells.append("")

            table.add_row(*cells, key=row_key)

        if needs_fetch:
            # Trigger the single sequential worker
            logger.info(f"Triggering sequential fetch for {current_chain}")
            trace(f"Triggering sequential fetch for {current_chain}")
            self.fetch_all_balances(current_chain, token_names)

            # Watchdog: Request a check in 3 seconds to see if we are still loading
            self.set_timer(3.0, lambda: self.check_balance_loading_status(current_chain))

    # --- Helper / Watchdog ---
    def check_balance_loading_status(self, chain_name_checked: str) -> None:
        """Verify if balances are fully loaded for a chain."""
        if self.active_chain != chain_name_checked:
            return

        needs_retry = False
        chain_interface = ChainInterfaces().get(chain_name_checked)
        active_tokens = self.chain_token_states.get(chain_name_checked, set())

        # Iterate all accounts to see if we have data
        for account in self.wallet.key_storage.accounts.values():
            addr = account.address

            # Check Native
            if chain_name_checked not in self.balance_cache:
                needs_retry = True
                break

            if addr not in self.balance_cache[chain_name_checked]:
                needs_retry = True
                break

            native_val = self.balance_cache[chain_name_checked][addr].get("NATIVE")
            if not native_val or native_val == "Loading...":
                needs_retry = True
                break

            # Check Tokens (if any selected)
            for t in active_tokens:
                t_val = self.balance_cache[chain_name_checked][addr].get(t)
                if not t_val or t_val == "Loading...":
                    needs_retry = True
                    break

            if needs_retry:
                break

        trace(f"Watchdog Check: {chain_name_checked} Needs Retry? {needs_retry}")

        if needs_retry:
            logger.warning(
                f"Watchdog: Balances still loading for {chain_name_checked}. Retrying..."
            )
            trace(f"Watchdog: Retrying for {chain_name_checked}")
            chain_interface = ChainInterfaces().get(chain_name_checked)
            token_names = list(chain_interface.tokens.keys()) if chain_interface else []
            self.fetch_all_balances(chain_name_checked, token_names)

    # --- Async Fetchers ---
    @work(exclusive=False, thread=True)
    def fetch_all_balances(self, chain_name: str, token_names: List[str]) -> None:  # noqa: C901
        """Fetch all balances for the chain sequentially."""
        trace(f"WORKER START: {chain_name}")

        logger.info(f"WORKER START: Fetching all balances for {chain_name}")
        import time

        # We iterate over a snapshot of accounts to avoid modification issues
        accounts = list(self.wallet.key_storage.accounts.values())

        for account in accounts:
            if self.active_chain != chain_name:
                trace(f"Worker aborted for {chain_name} (Active: {self.active_chain})")
                return

            address = account.address

            trace(f"  FETCHING: {address} on {chain_name}")

            # --- Native Balance ---
            # Check cache first to avoid re-fetching valid data
            cached_native = self.balance_cache.get(chain_name, {}).get(address, {}).get("NATIVE")

            should_fetch_native = True
            if cached_native and cached_native != "Loading..." and cached_native != "Error":
                should_fetch_native = False

            val_native = cached_native if not should_fetch_native else "Error"

            if should_fetch_native:
                retries = 3
                for attempt in range(retries):
                    try:
                        start_time = time.time()
                        balance = self.wallet.get_native_balance_eth(address, chain_name=chain_name)
                        duration = time.time() - start_time
                        logger.info(f"[{chain_name}] Fetched native {address} in {duration:.2f}s")
                        val_native = f"{balance:.4f}" if balance is not None else "Error"
                        # Update Cache immediately so subsequent partial re-draws have it
                        if chain_name not in self.balance_cache:
                            self.balance_cache[chain_name] = {}
                        if address not in self.balance_cache[chain_name]:
                            self.balance_cache[chain_name][address] = {}
                        self.balance_cache[chain_name][address]["NATIVE"] = val_native
                        break
                    except Exception as e:
                        if attempt == retries - 1:
                            logger.error(f"[{chain_name}] Failed native {address}: {e}")
                            if "429" in str(e):
                                self.app.call_from_thread(
                                    self.notify, f"Rate Limit (429) {chain_name}", severity="error"
                                )
                        else:
                            self.app.call_from_thread(
                                self.update_table_cell,
                                address,
                                3,
                                Text(f"Retry {attempt + 1}...", style="yellow", justify="right"),
                            )
                            time.sleep(1)

            # Update UI
            self.app.call_from_thread(
                self.update_table_cell, address, 3, Text(val_native, justify="right")
            )

            # --- Token Balances ---
            for i, token in enumerate(token_names):
                # Check if this token is enabled
                if token not in self.chain_token_states.get(chain_name, set()):
                    continue

                col_idx = 4 + i

                # Check cache
                cached_token = self.balance_cache.get(chain_name, {}).get(address, {}).get(token)
                if cached_token and cached_token != "-" and cached_token != "Loading...":
                    self.app.call_from_thread(
                        self.update_table_cell,
                        address,
                        col_idx,
                        Text(cached_token, justify="right"),
                    )
                    continue

                retries = 3
                val_token = "-"

                for attempt in range(retries):
                    try:
                        balance = self.wallet.get_erc20_balance_eth(
                            address, token, chain_name=chain_name
                        )
                        val_token = f"{balance:.4f}" if balance is not None else "-"

                        # Update Cache
                        if chain_name not in self.balance_cache:
                            self.balance_cache[chain_name] = {}
                        if address not in self.balance_cache[chain_name]:
                            self.balance_cache[chain_name][address] = {}
                        self.balance_cache[chain_name][address][token] = val_token
                        break
                    except Exception as e:
                        if attempt == retries - 1:
                            logger.error(f"[{chain_name}] Failed token {token} {address}: {e}")
                            if "429" in str(e):
                                self.app.call_from_thread(
                                    self.notify, f"Rate Limit {token}", severity="error"
                                )
                        else:
                            self.app.call_from_thread(
                                self.update_table_cell,
                                address,
                                col_idx,
                                Text(f"Retry {attempt + 1}...", style="yellow", justify="right"),
                            )
                            time.sleep(1)

                self.app.call_from_thread(
                    self.update_table_cell, address, col_idx, Text(val_token, justify="right")
                )

            # Yield slightly to keep UI snappy
            time.sleep(0.01)

        logger.info(f"WORKER END: Finished fetching for {chain_name}")

    def on_unmount(self) -> None:
        """Stop the monitor when the view is unmounted."""
        self.stop_monitor()

    def start_monitor(self) -> None:
        """Start the background transaction monitor."""
        self.stop_monitor()
        addresses = [acc.address for acc in self.wallet.key_storage.accounts.values()]
        self.monitor = EventMonitor(addresses, self.monitor_callback, self.active_chain)
        self.monitor_worker = run_monitor_thread(self.monitor)

    def stop_monitor(self) -> None:
        """Stop the background transaction monitor."""
        if self.monitor:
            self.monitor.stop()
            self.monitor = None

    def monitor_callback(self, txs: List[dict]) -> None:
        """Handle new transactions from the monitor thread."""
        self.app.call_from_thread(self.handle_new_txs, txs)

    def handle_new_txs(self, txs: List[dict]) -> None:
        """Process new transactions on the main thread."""
        self.refresh_accounts()  # Fetch new balances

        table = self.query_one("#tx_table", DataTable)
        import datetime

        for tx in txs:
            # Format Time
            if tx.get("timestamp"):
                ts = datetime.datetime.fromtimestamp(tx["timestamp"]).strftime("%Y-%m-%d %H:%M:%S")
            else:
                ts = "Recent"

            # Resolve Names
            from_str = self.resolve_tag(tx["from"])
            to_str = self.resolve_tag(tx["to"])
            token_str = tx["token"]

            # Amount
            val = tx["value"]
            if val > 0 and token_str == "NATIVE":
                amount_str = f"{val / 10**18:.4f}"
            else:
                amount_str = "?"  # hard to say for tokens without decimals

            status = "[green]Detected[/green]"

            table.add_row(ts, from_str, to_str, token_str, amount_str, status, key=tx["hash"])
            self.notify(f"New transaction detected! {tx['hash'][:6]}...", severity="info")

        self.enrich_and_log_txs(txs)

    def resolve_tag(self, address: str) -> str:
        """Resolve an address to a friendly tag name if known."""
        # Check wallet
        for acc in self.wallet.key_storage.accounts.values():
            if acc.address.lower() == address.lower():
                return acc.tag
        # Check whitelist
        config = Config()
        if config.core and config.core.whitelist:
            for name, addr in config.core.whitelist.items():
                if addr.lower() == address.lower():
                    return name
        # Fallback to address
        return f"{address[:6]}...{address[-4:]}"

    @on(Button.Pressed)
    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses in the WalletsView."""
        if event.button.id == "create_address_btn":

            def create_handler(result):
                if result:
                    tag, is_safe = result
                    if not tag:
                        tag = f"Account {len(self.wallet.key_storage.accounts) + 1}"

                    if is_safe:
                        self.notify(
                            "Safe creation requires more config (signers). Created EOA for now.",
                            severity="warning",
                        )
                        self.wallet.key_storage.create_account(tag)
                    else:
                        self.wallet.key_storage.create_account(tag)

                    self.notify(f"Created new account: {tag}")
                    self.refresh_accounts()

            self.app.push_screen(CreateAddressModal(), create_handler)

        elif event.button.id == "send_btn":
            self.send_transaction()

    @on(Select.Changed, "#chain_select")
    async def on_chain_changed(self, event: Select.Changed) -> None:
        """Handle chain selection changes."""
        if event.value and event.value != self.active_chain:
            interface = ChainInterfaces().get(event.value)
            if not interface or not interface.chain.rpc:
                self.notify(
                    f"No RPC configured for {event.value}. Please check your secrets.",
                    severity="warning",
                )
                event.control.value = self.active_chain
                return

            self.active_chain = event.value
            await self.refresh_ui_for_chain()
            self.start_monitor()

    async def refresh_ui_for_chain(self) -> None:  # noqa: C901
        """Update the UI elements for the newly selected chain."""
        self.query_one("#accounts_header", Label).update(
            f"Accounts ({self.active_chain.capitalize()})"
        )

        # 1. Rebuild Token Toggles
        scroll = self.query_one("#token_toggles", Horizontal)
        chain_interface = ChainInterfaces().get(self.active_chain)
        desired_tokens = set(chain_interface.tokens.keys()) if chain_interface else set()

        existing_ids = {
            child.id for child in scroll.children if child.id and child.id.startswith("cb_")
        }

        for child in list(scroll.children):
            if child.id and child.id.startswith("cb_"):
                token_name = child.id[3:]
                if token_name not in desired_tokens:
                    child.remove()

        if chain_interface:
            for token_name in chain_interface.tokens.keys():
                cb_id = f"cb_{token_name}"
                is_checked = token_name in self.chain_token_states.get(self.active_chain, set())
                if cb_id not in existing_ids:
                    scroll.mount(Checkbox(token_name.upper(), value=is_checked, id=cb_id))
                else:
                    existing_cb = self.query_one(f"#{cb_id}", Checkbox)
                    if existing_cb.value != is_checked:
                        existing_cb.value = is_checked

        # 2. Update Tx Form Options
        form_container = self.query_one("#tx_form_container", Horizontal)
        # Clear existing content carefully
        await form_container.remove_children()

        native_symbol = chain_interface.chain.native_currency if chain_interface else "Native"
        token_options: List[Tuple[str, str]] = [(native_symbol, "native")]
        if chain_interface:
            for token_name in chain_interface.tokens.keys():
                token_options.append((token_name.upper(), token_name))

        accounts = self.wallet.key_storage.accounts.values()
        from_options = [(a.tag, a.address) for a in accounts]
        to_options = list(from_options)
        config = Config()
        if config.core and config.core.whitelist:
            for name, addr in config.core.whitelist.items():
                to_options.append((name, addr))

        try:
            self.query_one("#from_addr", Select).set_options(from_options)
            self.query_one("#to_addr", Select).set_options(to_options)
            t_sel = self.query_one("#token", Select)
            t_sel.set_options(token_options)
            t_sel.value = "native"
        except Exception:
            form_container.mount(
                Select(from_options, prompt="From Address", id="from_addr"),
                Select(to_options, prompt="To Address", id="to_addr"),
                Input(placeholder="Amount", id="amount"),
                Select(token_options, value="native", id="token", allow_blank=False),
                Button("Send", id="send_btn", variant="primary"),
            )

    @on(Checkbox.Changed)
    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        """Handle token toggle checkbox changes."""
        if not event.checkbox.id or not event.checkbox.id.startswith("cb_"):
            return

        token_name = event.checkbox.id[3:]
        is_checked = event.value

        if self.active_chain not in self.chain_token_states:
            self.chain_token_states[self.active_chain] = set()

        if is_checked:
            self.chain_token_states[self.active_chain].add(token_name)
            self.fetch_all_for_token(token_name)
        else:
            self.chain_token_states[self.active_chain].discard(token_name)
            self.clear_all_for_token(token_name)

    def is_token_checked(self, token_name: str) -> bool:
        """Check if a token is currently selected for the active chain."""
        return token_name in self.chain_token_states.get(self.active_chain, set())

    def fetch_all_for_token(self, token_name: str) -> None:
        """Trigger balance fetch for a specific token."""
        if self.active_chain:
            self.fetch_all_balances(self.active_chain, [token_name])

    def clear_all_for_token(self, token_name: str) -> None:
        """Clear displayed balance for a token when unchecked."""
        chain_interface = ChainInterfaces().get(self.active_chain)
        if not chain_interface:
            return

        # Find column usage
        token_keys = list(chain_interface.tokens.keys())
        if token_name.upper() in token_keys:
            # Just refresh to be safe and simple
            self.refresh_table_structure_and_data()

    def update_table_cell(self, row_key: str, col_index: int, value: str | Text) -> None:
        """Update a single cell in the accounts table safely."""
        try:
            table = self.query_one("#accounts_table", DataTable)
            if col_index < len(table.columns):
                col_key = list(table.columns.keys())[col_index]
                table.update_cell(str(row_key), col_key, value)
        except Exception:
            pass

    @on(DataTable.CellSelected, "#accounts_table")
    def on_account_cell_selected(self, event: DataTable.CellSelected) -> None:
        """Handle click on account table cell (copy address)."""
        if event.coordinate.column == 1:
            try:
                # Try simple copy
                import pyperclip

                pyperclip.copy(event.value)
                self.notify("Copied address to clipboard")
            except Exception as e:
                logger.error(f"Clipboard copy failed: {e}")
                self.app.copy_to_clipboard(event.value)
                self.notify("Copied address to clipboard (Textual)")

    def send_transaction(self) -> None:
        """Handle send button press to trigger transaction."""
        try:
            from_addr = self.query_one("#from_addr", Select).value
            to = self.query_one("#to_addr", Select).value
            amt = self.query_one("#amount", Input).value
            tok = self.query_one("#token", Select).value
        except Exception:
            return

        if not from_addr or not to or not amt or not tok:
            self.notify("Please fill all fields", severity="error")
            return

        amount = float(amt)
        self.send_tx_worker(from_addr, to, tok, amount)

    @work(exclusive=True, thread=True)
    def send_tx_worker(self, f, t, token, amount) -> None:
        """Execute transaction sending in background thread."""
        try:
            chain = self.active_chain
            # Convert amount to wei (assuming 18 decimals for now)
            amount_wei = int(amount * 10**18)
            token_arg = token if token != "native" else "native"

            tx_hash = self.wallet.send(
                from_address_or_tag=f,
                to_address_or_tag=t,
                token_address_or_name=token_arg,
                amount_wei=amount_wei,
                chain_name=chain,
            )

            self.app.call_from_thread(self.notify, f"Sent! Hash: {tx_hash}")
            self.app.call_from_thread(self.add_tx_history_row, f, t, token, amount, "Pending")
        except Exception as e:
            self.app.call_from_thread(self.notify, f"Error: {e}", severity="error")
            self.app.call_from_thread(self.update_last_tx_status, "[red]Failed[/red]")

    def add_tx_history_row(self, f, t, token, amt, status):
        """Add a new row to the transaction history table directly."""
        import datetime

        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            self.query_one("#tx_table", DataTable).add_row(ts, f, t, token, amt, status)
        except Exception:
            pass

    def update_last_tx_status(self, new_status):
        """Update the status of the most recently added transaction row."""
        try:
            table = self.query_one("#tx_table", DataTable)
            if table.row_count > 0:
                pass
        except Exception:
            pass

    def load_recent_txs(self):
        """Load recent transactions from the database and populate table."""
        try:
            import datetime as dt

            from iwa.core.db import SentTransaction

            cutoff = dt.datetime.now() - dt.timedelta(hours=24)

            # Simple query - we might need to filter by chain if SentTx has chain info
            # Assuming SentTransaction stores values compatible
            recent = (
                SentTransaction.select()
                .where(SentTransaction.timestamp > cutoff)
                .order_by(SentTransaction.timestamp.desc())
            )

            table = self.query_one("#tx_table", DataTable)
            table.clear()

            for tx in recent:
                ts = tx.timestamp.strftime("%Y-%m-%d %H:%M:%S")
                f = tx.from_address
                t = tx.to_address
                amt = f"€{tx.value_eur:.2f}"
                status = "Confirmed"  # Valid assumption for historic DB txs
                table.add_row(ts, f, t, tx.token_symbol or "UNK", amt, status, key=tx.tx_hash)
        except Exception as e:
            logger.error(f"Failed to load recent txs: {e}")
            print(f"DEBUG: Failed to load recent txs: {e}")
            pass

    @work(thread=True)
    def enrich_and_log_txs(self, txs: List[dict]) -> None:
        """Fetch additional details for transactions and log them to DB."""
        from iwa.core.db import log_transaction

        # Mapping for CoinGecko
        cg_ids = {
            "ethereum": "ethereum",
            "gnosis": "gnosis",
            "base": "ethereum",
        }
        cg_id = cg_ids.get(self.active_chain, "ethereum")

        price = self.price_service.get_token_price(cg_id, "eur")
        interface = ChainInterfaces().get(self.active_chain)

        for tx in txs:
            try:
                # Basic enrichment
                value_wei = int(tx.get("value", 0))
                value_eur = 0.0
                token_val = "Native"

                # Check if it's a token transfer (ERC20)
                # In a real monitor, we'd parse logs or input data.
                # Here we assume native for simplicity or use what Monitor provided?
                # Monitor provided raw tx dict?
                # Let's assume native for now if 'token' key not set
                if "token" in tx:
                    token_val = tx["token"]

                if token_val == "Native" or token_val == interface.chain.native_currency:
                    value_eth = value_wei / 10**18
                    value_eur = value_eth * price

                # Gas
                gas_cost_wei = int(tx.get("gasPrice", 0)) * int(tx.get("gasUsed", 0))

                tx_hash = tx.get("hash")
                log_transaction(
                    tx_hash=tx_hash,
                    from_addr=tx["from"],
                    to_addr=tx["to"],
                    token=token_val,
                    amount_wei=str(value_wei),
                    chain=self.active_chain,
                    price_eur=price,
                    value_eur=value_eur,
                    gas_cost=str(gas_cost_wei),
                )
                logger.info(f"Logged enriched tx {tx_hash}")
            except Exception as e:
                logger.error(f"Failed to enrich/log tx {tx.get('hash')}: {e}")


def map_column_index_to_key(table: DataTable, index: int):
    """Map column numerical index to its key."""
    try:
        return list(table.columns.keys())[index]
    except Exception:
        return None
