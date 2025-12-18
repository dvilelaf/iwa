"""TUI Views for the IWA application."""

import datetime
import json
import threading
import time
from typing import List, Tuple

from rich.markup import escape
from rich.text import Text
from textual import on, work
from textual.app import ComposeResult
from textual.containers import Center, Horizontal, HorizontalScroll, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    Checkbox,
    DataTable,
    Input,
    Label,
    Select,
    SelectionList,
    # Selection,
)

from iwa.core.chain import ChainInterfaces
from iwa.core.models import Config, StoredSafeAccount
from iwa.core.monitor import EventMonitor
from iwa.core.pricing import PriceService
from iwa.core.utils import configure_logger
from iwa.core.wallet import Wallet

logger = configure_logger()


def trace(msg):
    """No-op trace."""
    pass


def run_monitor_thread(monitor: EventMonitor):
    """Start the event monitor in a daemon thread."""
    t = threading.Thread(target=monitor.start, daemon=True)
    t.start()
    return t


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
            yield Input(placeholder="e.g. My My EOA", id="tag_input")
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
            # Using SelectionList for multi-selection
            options = [(f"{tag} ({addr})", addr) for tag, addr in self.existing_accounts]
            yield SelectionList[str](*options, id="owners_list")

            yield Label("Chains (select multiple):")
            from iwa.core.chain import ChainInterfaces

            chain_options = [(name.title(), name) for name, _ in ChainInterfaces().items()]
            yield SelectionList[str](*chain_options, id="chains_list")

            with Horizontal(id="btn_row"):
                yield Button("Cancel", id="cancel")
                yield Button("Create", variant="primary", id="create")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press."""
        if event.button.id == "create":
            tag = self.query_one("#tag_input").value
            threshold_str = self.query_one("#threshold_input").value
            owners = self.query_one("#owners_list").selected
            chains = self.query_one("#chains_list").selected

            try:
                threshold = int(threshold_str)
            except ValueError:
                threshold = 1

            self.dismiss({"tag": tag, "threshold": threshold, "owners": owners, "chains": chains})
        elif event.button.id == "cancel":
            self.dismiss(None)


class WalletsView(VerticalScroll):
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
        self.monitors = []
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
        self.refresh_accounts()
        self.start_monitor()

        # Initial column setup
        self.setup_tx_table_columns()

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
            # Buttons for creating new wallets
            with Center():
                yield Horizontal(
                    Button(
                        "Create EOA",
                        id="create_eoa_btn",
                        variant="primary",
                        classes="create-btn",
                    ),
                    Button(
                        "Create Safe",
                        id="create_safe_btn",
                        variant="warning",
                        classes="create-btn",
                    ),
                    classes="btn-group",
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

    def setup_tx_table_columns(self) -> None:
        """Ensure the transaction table has the correct columns."""
        try:
            table = self.query_one("#tx_table", DataTable)
            if not table.columns:
                table.add_column("Time", width=22)
                table.add_column("Chain", width=10)
                table.add_column("From", width=20)
                table.add_column("To", width=20)
                table.add_column("Token", width=10)
                table.add_column("Amount", width=12)
                table.add_column("Value (€)", width=12)
                table.add_column("Status", width=12)
                table.add_column("Hash", width=22)
                table.add_column("Gas (wei)", width=12)
                table.add_column("Gas (€)", width=10)
                table.add_column("Tags", width=20)
        except Exception as e:
            logger.error(f"Failed to setup tx table columns: {e}")

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
        # Update Recent Transactions
        # Reload from DB instead of using memory history to persist across chain switches
        self.load_recent_txs()

    def refresh_table_structure_and_data(self) -> None:  # noqa: C901
        """Rebuild the accounts table structure and data."""
        table = self.query_one("#accounts_table", DataTable)
        table.clear(columns=True)
        chain_interface = ChainInterfaces().get(self.active_chain)
        native_symbol = chain_interface.chain.native_currency if chain_interface else "Native"
        table.add_column("Tag", width=12)
        table.add_column("Address", width=44)
        table.add_column("Type", width=6)
        table.add_column(Text(native_symbol.upper(), justify="center"), width=12)

        # Add all token columns available on this chain
        token_names = []
        if chain_interface:
            for token_name in chain_interface.tokens.keys():
                table.add_column(Text(f"{token_name.upper()}", justify="center"), width=12)
                token_names.append(token_name)

        # Populate Rows
        current_chain = self.active_chain  # Capture for workers
        logger.info(f"Refeshing table for {current_chain}...")

        # Ensure cache exists for this chain
        if current_chain not in self.balance_cache:
            self.balance_cache[current_chain] = {}

        needs_fetch = False

        for account in self.wallet.key_storage.accounts.values():
            try:
                if isinstance(account, StoredSafeAccount):
                    if current_chain not in account.chains:
                        continue
                    acct_type = "Safe"
                else:
                    acct_type = "EOA"
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

                cells = [
                    Text(account.tag, style="green"),
                    escape(account.address),
                    acct_type,
                    native_cell,
                ]

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
            except Exception as e:
                logger.error(f"Error processing account {account.address}: {e}")

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
    def fetch_all_balances(self, chain_name: str, token_names: List[str]) -> None:
        """Fetch all balances for the chain sequentially (Worker wrapper)."""
        self._fetch_all_balances_impl(chain_name, token_names)

    def _fetch_all_balances_impl(self, chain_name: str, token_names: List[str]) -> None:  # noqa: C901
        """Fetch all balances for the chain sequentially (Implementation)."""
        trace(f"WORKER START: {chain_name}")

        logger.info(f"WORKER START: Fetching all balances for {chain_name}")

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
            # Retrieve full list of tokens for this chain to determine correct column index
            chain_interface = ChainInterfaces().get(chain_name)
            all_chain_tokens = list(chain_interface.tokens.keys()) if chain_interface else []

            for _i, token in enumerate(token_names):
                # Check if this token is enabled
                if token not in self.chain_token_states.get(chain_name, set()):
                    continue

                # Determine correct column index based on full list
                try:
                    token_idx = all_chain_tokens.index(token)
                    col_idx = 4 + token_idx
                except ValueError:
                    logger.error(f"Token {token} not found in chain {chain_name} tokens")
                    continue

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
                                    self.notify, f"Rate Limit {escape(token)}", severity="error"
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

        for chain_name, interface in ChainInterfaces().items():
            if interface.chain.rpc:
                monitor = EventMonitor(addresses, self.monitor_callback, chain_name)
                run_monitor_thread(monitor)
                self.monitors.append(monitor)

    def stop_monitor(self) -> None:
        """Stop the background transaction monitor."""
        for monitor in self.monitors:
            monitor.stop()
        self.monitors.clear()

    def monitor_callback(self, txs: List[dict]) -> None:
        """Handle new transactions from the monitor thread."""
        self.app.call_from_thread(self.handle_new_txs, txs)

    def handle_new_txs(self, txs: List[dict]) -> None:
        """Process new transactions on the main thread."""
        try:
            self.refresh_accounts()  # Fetch new balances
            self.setup_tx_table_columns()
            table = self.query_one("#tx_table", DataTable)

            for tx in txs:
                # Format Time
                if tx.get("timestamp"):
                    ts = datetime.datetime.fromtimestamp(tx["timestamp"]).strftime(
                        "%Y-%m-%d %H:%M:%S"
                    )
                else:
                    ts = "Recent"

                # Resolve Names
                chain_str = tx.get("chain", "?").title()
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

                # Normalize Hash
                tx_hash = tx["hash"]
                if not tx_hash.startswith("0x"):
                    tx_hash = "0x" + tx_hash

                if tx_hash in table.rows:
                    continue

                table.add_row(
                    ts,
                    chain_str,
                    from_str,
                    to_str,
                    token_str,
                    amount_str,
                    "",  # Value
                    status,
                    tx_hash[:10] + "...",
                    "?",  # Gas
                    "?",  # Gas Val
                    "",  # Tags - will be enriched later
                    key=tx_hash,
                )
                # Only notify for incoming transactions (not from our own accounts)
                is_outgoing = False
                for acc in self.wallet.key_storage.accounts.values():
                    if acc.address.lower() == str(tx["from"]).lower():
                        is_outgoing = True
                        break

                if not is_outgoing:
                    self.notify(f"New transaction detected! {tx['hash'][:6]}...", severity="info")

        except Exception as e:
            logger.error(f"Error handling new transactions: {e}")

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
    def on_button_pressed(self, event: Button.Pressed) -> None:  # noqa: C901
        """Handle button presses in the WalletsView."""
        if event.button.id == "create_eoa_btn":

            def create_eoa_handler(result_tag):
                if result_tag is not None:
                    # Tag can be empty string, in which case we auto-gen
                    tag = result_tag
                    if not tag:
                        tag = f"Account {len(self.wallet.key_storage.accounts) + 1}"

                    self.wallet.key_storage.create_account(tag)
                    self.notify(f"Created new EOA: {escape(tag)}")

            self.app.push_screen(CreateEOAModal(), create_eoa_handler)

        elif event.button.id == "create_safe_btn":
            # Pass existing accounts to modal
            accounts_list = [
                (acc.tag, acc.address) for acc in self.wallet.key_storage.accounts.values()
            ]

            def create_safe_handler(result_dict):
                if result_dict:
                    tag = result_dict.get("tag")
                    threshold = result_dict.get("threshold", 1)
                    owners = result_dict.get("owners", [])
                    chains = result_dict.get("chains", [])

                    if not tag:
                        tag = f"Safe {len(self.wallet.key_storage.accounts) + 1}"

                    if not owners:
                        self.notify("Safe creation failed: No owners selected.", severity="error")
                        return

                    if not chains:
                        self.notify("Safe creation failed: No chains selected.", severity="error")
                        return

                    self.create_safe_worker(tag, threshold, owners, chains)

            self.app.push_screen(CreateSafeModal(accounts_list), create_safe_handler)

        elif event.button.id == "send_btn":
            self.send_transaction()

    @work(exclusive=False, thread=True)
    def create_safe_worker(
        self, tag: str, threshold: int, owners: List[str], chains: List[str]
    ) -> None:
        """Background worker to create a Safe."""
        import time

        salt_nonce = int(time.time() * 1000)

        # Iterate over selected chains
        from iwa.core.chain import ChainInterfaces

        for chain_name in chains:
            try:
                interface = ChainInterfaces().get(chain_name)
            except ValueError:
                continue

            if not interface.chain.rpc:
                logger.warning(f"Skipping Safe deployment on {chain_name} (No RPC)")
                self.app.call_from_thread(
                    self.notify, f"Skipping {escape(chain_name)}: No RPC", severity="warning"
                )
                continue

            try:
                self.app.call_from_thread(
                    self.notify,
                    f"Deploying Safe '{escape(tag)}' on {escape(chain_name)}...",
                    severity="info",
                )

                # Use 'master' as deployer as per requirements
                deployer = "master"

                # Call KeyStorage.create_safe
                safe_account, tx_hash = self.wallet.key_storage.create_safe(
                    deployer_tag_or_address=deployer,
                    owner_tags_or_addresses=owners,
                    threshold=threshold,
                    chain_name=chain_name,
                    tag=tag,
                    salt_nonce=salt_nonce,
                )

                self.app.call_from_thread(
                    self.notify,
                    f"Safe '{escape(tag)}' successfully created on {escape(chain_name)}!",
                    severity="success",
                )

            except Exception as e:
                logger.error(f"Failed to create Safe on {chain_name}: {e}")
                self.app.call_from_thread(
                    self.notify,
                    f"Error creating Safe on {escape(chain_name)}: {escape(str(e))}",
                    severity="error",
                )

        self.app.call_from_thread(self.refresh_accounts)

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

        # Refresh table structure (columns) and data for the new chain
        self.refresh_accounts()

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

    @on(DataTable.CellSelected, "#tx_table")
    def on_tx_cell_selected(self, event: DataTable.CellSelected) -> None:
        """Handle click on transaction table cell (copy hash)."""
        # Try to find which column we clicked by label
        try:
            columns = list(event.data_table.columns.values())
            col_label = str(columns[event.coordinate.column].label)
        except Exception:
            col_label = ""

        if "Hash" in col_label:
            # The full hash is stored as the row key
            full_hash = str(event.cell_key.row_key.value)
            try:
                import pyperclip

                pyperclip.copy(full_hash)
                self.notify(f"Copied hash: {full_hash[:6]}...", severity="info")
            except Exception as e:
                logger.error(f"Clipboard copy failed: {e}")
                self.app.copy_to_clipboard(full_hash)
                self.notify(f"Copied hash (Textual): {full_hash[:6]}...", severity="info")

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
        """Execute transaction sending (Worker wrapper)."""
        self._send_tx_worker_impl(f, t, token, amount)

    def _send_tx_worker_impl(self, f, t, token, amount) -> None:
        """Execute transaction sending in background thread (Implementation)."""
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

            self.app.call_from_thread(
                self.notify, "Transaction sent successfully!", severity="success"
            )
            self.app.call_from_thread(
                self.add_tx_history_row, f, t, token, amount, "Pending", tx_hash
            )
        except Exception as e:
            self.app.call_from_thread(self.notify, f"Error: {escape(str(e))}", severity="error")
            self.app.call_from_thread(self.update_last_tx_status, "[red]Failed[/red]")

    def add_tx_history_row(self, f, t, token, amt, status, tx_hash=""):
        """Add a new row to the transaction history table directly."""
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            self.query_one("#tx_table", DataTable).add_row(
                ts,
                self.active_chain.capitalize(),
                f,
                t,
                token,
                amt,
                "",  # Value - placeholder
                status,
                (tx_hash if tx_hash.startswith("0x") else f"0x{tx_hash}")[:10] + "..."
                if tx_hash
                else "",
                "?",  # Gas
                "?",  # Gas Val
                "",  # Tags - will be updated from DB or enrichment
            )
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

            self.setup_tx_table_columns()

            cutoff = dt.datetime.now() - dt.timedelta(hours=24)

            # Query all transactions ordered by time
            recent = (
                SentTransaction.select()
                .where(SentTransaction.timestamp > cutoff)
                .order_by(SentTransaction.timestamp.desc())
            )

            table = self.query_one("#tx_table", DataTable)
            table.clear()

            for tx in recent:
                ts = tx.timestamp.strftime("%Y-%m-%d %H:%M:%S")
                # Prefer tags over addresses
                f = tx.from_tag or tx.from_address
                t = tx.to_tag or tx.to_address

                # Token Symbol: If it says Native/NATIVE, get the actual symbol for the chain
                token_symbol = tx.token
                if token_symbol and token_symbol.upper() in ["NATIVE", "NATIVE CURRENCY"]:
                    chain_interface = ChainInterfaces().get(tx.chain)
                    token_symbol = (
                        chain_interface.chain.native_currency if chain_interface else "Native"
                    )

                # Format Amount (assuming 18 decimals for simplicity or raw string)
                try:
                    amt_val = float(tx.amount_wei) / 10**18
                    amt_str = f"{amt_val:.4f}"
                except (ValueError, TypeError):
                    amt_str = tx.amount_wei or "?"

                val_eur = f"€{(tx.value_eur or 0.0):.2f}"
                status = "[green]Confirmed[/green]"

                # Gas in wei
                gas_str = str(tx.gas_cost or "0")

                if tx.gas_value_eur is not None:
                    if tx.gas_value_eur < 0.0001 and tx.gas_value_eur > 0:
                        gas_eur = f"€{tx.gas_value_eur:.8f}"
                    elif tx.gas_value_eur < 0.01 and tx.gas_value_eur > 0:
                        gas_eur = f"€{tx.gas_value_eur:.6f}"
                    else:
                        gas_eur = f"€{tx.gas_value_eur:.4f}"
                else:
                    gas_eur = "?"

                table.add_row(
                    ts,
                    escape(str(tx.chain).capitalize()),
                    escape(f) if f else "",
                    escape(t) if t else "",
                    escape(token_symbol or "UNK"),
                    escape(amt_str),
                    escape(val_eur),
                    status,
                    escape(
                        (tx.tx_hash if tx.tx_hash.startswith("0x") else f"0x{tx.tx_hash}")[:10]
                        + "..."
                    ),
                    escape(gas_str),
                    escape(gas_eur),
                    escape(", ".join(json.loads(tx.tags)) if tx.tags else ""),
                    key=tx.tx_hash if tx.tx_hash.startswith("0x") else f"0x{tx.tx_hash}",
                )
        except Exception as e:
            logger.error(f"Failed to load recent txs: {e}")
            print(f"DEBUG: Failed to load recent txs: {e}")
            pass

    def _resolve_token_info_for_enrichment(self, tx, interface, price):
        """Helper to resolve token symbol and value/price for enrichment."""
        value_wei = int(tx.get("value", 0))
        token_val = tx.get("token", "NATIVE")
        value_eur = None
        final_price = price

        if token_val == "TOKEN" and tx.get("contract_address"):
            contract_addr = tx["contract_address"]
            token_val = interface.get_token_symbol(contract_addr)
            decimals = interface.get_token_decimals(contract_addr)
            value_token = value_wei / (10**decimals)
        else:
            value_token = value_wei / 10**18

        if (
            token_val.upper() in ["NATIVE", "NATIVE CURRENCY"]
            or token_val == interface.chain.native_currency
        ):
            token_val = interface.chain.native_currency
            if final_price is not None:
                value_eur = value_token * final_price
        else:
            token_cg_ids = {
                "OLAS": "autonolas",
                "USDC": "usd-coin",
                "DAI": "dai",
                "WXDAI": "dai",
                "SDAI": "dai",
            }
            t_cg_id = token_cg_ids.get(token_val.upper())
            if t_cg_id:
                t_price = self.price_service.get_token_price(t_cg_id, "eur")
                if t_price:
                    final_price = t_price
                    value_eur = value_token * t_price

        return token_val, value_wei, value_eur, final_price

    def _calculate_gas_cost_wei(self, interface, tx_hash, tx_data):
        """Helper to calculate gas cost accurately via receipt if possible."""
        try:
            receipt = interface.web3.eth.get_transaction_receipt(tx_hash)
            gas_used = receipt.get("gasUsed", 0)
            effective_gas_price = receipt.get("effectiveGasPrice", tx_data.get("gasPrice", 0))
            return int(effective_gas_price) * int(gas_used)
        except Exception:
            return int(tx_data.get("gasPrice", 0)) * int(tx_data.get("gasUsed", 0))

    @work(thread=True)
    def enrich_and_log_txs(self, txs: List[dict]) -> None:
        """Fetch additional details for transactions and log them to DB."""
        from iwa.core.db import log_transaction

        cg_ids = {"ethereum": "ethereum", "gnosis": "dai", "base": "ethereum"}
        price_cache = {}

        for tx in txs:
            try:
                tx_hash = tx.get("hash")
                tx_chain = tx.get("chain", self.active_chain)
                interface = ChainInterfaces().get(tx_chain)
                if not interface:
                    logger.warning(
                        f"No interface for chain {tx_chain}, skipping enrichment for {tx_hash}"
                    )
                    continue

                cg_id = cg_ids.get(tx_chain, "ethereum")
                if cg_id not in price_cache:
                    price_cache[cg_id] = self.price_service.get_token_price(cg_id, "eur")

                initial_price = price_cache[cg_id]
                token_val, value_wei, value_eur, final_price = (
                    self._resolve_token_info_for_enrichment(tx, interface, initial_price)
                )

                gas_cost_wei = self._calculate_gas_cost_wei(interface, tx_hash, tx)
                gas_eth = gas_cost_wei / 10**18
                gas_value_eur = gas_eth * final_price if final_price is not None else None

                log_transaction(
                    tx_hash=tx_hash,
                    from_addr=tx["from"],
                    from_tag=self.resolve_tag(tx["from"]),
                    to_addr=tx["to"],
                    to_tag=self.resolve_tag(tx["to"]),
                    token=token_val,
                    amount_wei=str(value_wei),
                    chain=tx_chain,
                    price_eur=final_price,
                    value_eur=value_eur,
                    gas_cost=str(gas_cost_wei),
                    gas_value_eur=gas_value_eur,
                )
                logger.info(f"Logged enriched tx {tx_hash} on {tx_chain}")
            except Exception as e:
                logger.error(f"Failed to enrich/log tx {tx.get('hash')} on {tx_chain}: {e}")

        # Refresh the UI table to show new enriched data
        self.app.call_from_thread(self.load_recent_txs)


def map_column_index_to_key(table: DataTable, index: int):
    """Map column numerical index to its key."""
    try:
        return list(table.columns.keys())[index]
    except Exception:
        return None
