"""Wallets Screen for the IWA TUI."""

import datetime
import json
import time
from typing import TYPE_CHECKING, List

from loguru import logger
from rich.markup import escape
from rich.text import Text
from textual import on, work
from textual.app import ComposeResult
from textual.containers import (
    Center,
    Horizontal,
    HorizontalScroll,
    VerticalScroll,
)
from textual.widgets import (
    Button,
    Checkbox,
    DataTable,
    Input,
    Label,
    Select,
)

from iwa.tui.workers import MonitorWorker

if TYPE_CHECKING:
    pass

from iwa.core.chain import ChainInterfaces
from iwa.core.models import Config, StoredSafeAccount
from iwa.core.monitor import EventMonitor
from iwa.core.pricing import PriceService
from iwa.core.utils import configure_logger
from iwa.core.wallet import Wallet
from iwa.tui.modals import CreateEOAModal, CreateSafeModal
from iwa.tui.widgets import AccountTable, ChainSelector, TransactionTable

# configure_logger() already configures loguru.logger, so we just use that.
configure_logger()


class WalletsScreen(VerticalScroll):
    """View for managing wallets (EOAs and Safes), viewing balances, and sending transactions.

    This screen handles:
    - Displaying account balances (native and tokens).
    - Managing chain selection.
    - Creating new accounts (EOA and Safe).
    - Sending transactions.
    - Monitoring transaction history.
    """

    BINDINGS = [
        ("r", "refresh", "Refresh Balances"),
    ]

    def __init__(self, wallet: Wallet):
        """Initialize WalletsView."""
        super().__init__()
        self.wallet = wallet
        self.active_chain = "gnosis"
        self.monitor_workers = []  # List of MonitorWorker instances
        # Stores set of checked tokens (names) per chain
        self.chain_token_states: dict[str, set[str]] = {
            "gnosis": set(),
            "ethereum": set(),
            "base": set(),
        }
        self.balance_cache = {}  # chain -> address -> balances
        self.price_service = PriceService()

    async def on_mount(self) -> None:
        """Called when view is mounted.

        Initializes UI state, loads accounts, starts the event monitor,
        and sets up the transaction table columns.
        """
        # Initialize UI state
        await self.refresh_ui_for_chain()
        self.refresh_accounts()
        self.start_monitor()

        # Initial column setup
        self.query_one(TransactionTable).setup_columns()

        # Load recent txs
        self.load_recent_txs()

    def compose(self) -> ComposeResult:
        """Compose the WalletsView UI."""
        yield ChainSelector(active_chain=self.active_chain)

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
        yield AccountTable(id="accounts_table")

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

        yield Label("Send Transaction", classes="header")

        # Transaction Form
        with Horizontal(classes="form-row", id="tx_form_container"):
            # Initial placeholder, will be cleared/replaced
            yield Label("Loading form...", id="form_loading_lbl")

        yield Label("Recent Transactions", classes="header")
        yield TransactionTable(id="tx_table")

    def action_refresh(self) -> None:
        """Manual refresh action."""
        self.notify("Refreshing accounts...", severity="info")
        self.refresh_accounts(force=True)

    def refresh_accounts(self, force: bool = False) -> None:
        """Refreshes table data.

        Args:
            force: If True, clears the local balance cache before refreshing.

        """
        if force:
            if self.active_chain in self.balance_cache:
                self.balance_cache[self.active_chain] = {}

        self.refresh_table_structure_and_data()
        self.load_recent_txs()

    def _build_account_row(
        self, account, current_chain: str, token_names: list
    ) -> tuple[list, bool]:
        """Build a row for a single account. Returns (cells, needs_fetch)."""
        needs_fetch = False

        if isinstance(account, StoredSafeAccount):
            if current_chain not in account.chains:
                return [], False  # Skip this account
            acct_type = "Safe"
        else:
            acct_type = "EOA"

        if account.address not in self.balance_cache[current_chain]:
            self.balance_cache[current_chain][account.address] = {}

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

        for token in token_names:
            if token in self.chain_token_states.get(current_chain, set()):
                cached_token = self.balance_cache[current_chain][account.address].get(token)
                if cached_token:
                    cells.append(cached_token)
                else:
                    cells.append("Loading...")
                    needs_fetch = True
            else:
                cells.append("")

        return cells, needs_fetch

    def refresh_table_structure_and_data(self) -> None:
        """Rebuild the accounts table structure and data."""
        table = self.query_one(AccountTable)
        chain_interface = ChainInterfaces().get(self.active_chain)
        native_symbol = chain_interface.chain.native_currency if chain_interface else "Native"
        token_names = list(chain_interface.tokens.keys()) if chain_interface else []

        table.setup_columns(self.active_chain, native_symbol, token_names)

        current_chain = self.active_chain
        if current_chain not in self.balance_cache:
            self.balance_cache[current_chain] = {}

        needs_fetch = False
        for account in self.wallet.account_service.get_account_data().values():
            try:
                cells, row_needs_fetch = self._build_account_row(
                    account, current_chain, token_names
                )
                if not cells:
                    continue  # Account skipped (e.g., Safe not on this chain)
                needs_fetch = needs_fetch or row_needs_fetch
                table.add_row(*cells, key=account.address)
            except Exception as e:
                logger.error(f"Error processing account {account.address}: {e}")

        if needs_fetch:
            self.fetch_all_balances(current_chain, token_names)
            self.set_timer(3.0, lambda: self.check_balance_loading_status(current_chain))

    def check_balance_loading_status(self, chain_name_checked: str) -> None:
        """Verify if balances are fully loaded for a chain."""
        if self.active_chain != chain_name_checked:
            return

        needs_retry = False
        active_tokens = self.chain_token_states.get(chain_name_checked, set())

        for account in self.wallet.account_service.get_account_data().values():
            addr = account.address
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

            for t in active_tokens:
                t_val = self.balance_cache[chain_name_checked][addr].get(t)
                if not t_val or t_val == "Loading...":
                    needs_retry = True
                    break
            if needs_retry:
                break

        if needs_retry:
            interface = ChainInterfaces().get(chain_name_checked)
            token_names = list(interface.tokens.keys()) if interface else []
            self.fetch_all_balances(chain_name_checked, token_names)

    @work(exclusive=False, thread=True)
    def fetch_all_balances(self, chain_name: str, token_names: List[str]) -> None:
        """Fetch all balances for the chain sequentially in a background thread.

        Iterates through all accounts and triggers fetch for native and token balances.
        """
        accounts = list(self.wallet.account_service.get_account_data().values())
        for account in accounts:
            if self.active_chain != chain_name:
                return
            self._fetch_account_all_balances(account.address, chain_name, token_names)
            time.sleep(0.01)

    def _fetch_account_all_balances(
        self, address: str, chain_name: str, token_names: List[str]
    ) -> None:
        """Fetch native and token balances for a single account."""
        self._fetch_account_native_balance(address, chain_name)
        self._fetch_account_token_balances(address, chain_name, token_names)

    def _fetch_account_native_balance(self, address: str, chain_name: str) -> None:
        """Fetch native balance for a single account."""
        cached_native = self.balance_cache.get(chain_name, {}).get(address, {}).get("NATIVE")
        should_fetch_native = not cached_native or cached_native in ["Loading...", "Error"]

        val_native = cached_native if not should_fetch_native else "Error"
        if should_fetch_native:
            try:
                balance = self.wallet.balance_service.get_native_balance_eth(
                    address, chain_name=chain_name
                )
                val_native = f"{balance:.4f}" if balance is not None else "Error"
                if chain_name not in self.balance_cache:
                    self.balance_cache[chain_name] = {}
                if address not in self.balance_cache[chain_name]:
                    self.balance_cache[chain_name][address] = {}
                self.balance_cache[chain_name][address]["NATIVE"] = val_native
            except Exception as e:
                from loguru import logger

                logger.error(f"Failed native {address}: {e}")

        self.app.call_from_thread(
            self.update_table_cell, address, 3, Text(val_native, justify="right")
        )

    def _fetch_account_token_balances(
        self, address: str, chain_name: str, token_names: List[str]
    ) -> None:
        """Fetch token balances for a single account."""
        interface = ChainInterfaces().get(chain_name)
        all_chain_tokens = list(interface.tokens.keys()) if interface else []
        for token in token_names:
            if token not in self.chain_token_states.get(chain_name, set()):
                continue
            try:
                col_idx = 4 + all_chain_tokens.index(token)
            except ValueError:
                continue

            val_token = self._fetch_single_token_balance(address, token, chain_name)
            self.app.call_from_thread(
                self.update_table_cell, address, col_idx, Text(val_token, justify="right")
            )

    def _fetch_single_token_balance(self, address: str, token: str, chain_name: str) -> str:
        """Fetch a single token balance using BalanceService."""
        val_token = self.wallet.balance_service.get_erc20_balance_with_retry(
            address, token, chain_name
        )
        val_token_str = f"{val_token:.4f}" if val_token is not None else "-"

        if val_token is not None:
            if chain_name not in self.balance_cache:
                self.balance_cache[chain_name] = {}
            if address not in self.balance_cache[chain_name]:
                self.balance_cache[chain_name][address] = {}
            self.balance_cache[chain_name][address][token] = val_token_str

        return val_token_str

    def add_tx_history_row(self, f, t, token, amt, status, tx_hash=""):
        """Add a new row to the transaction history table at the top."""
        from_str = self.resolve_tag(f)
        to_str = self.resolve_tag(t)
        table = self.query_one(TransactionTable)
        table.add_row(
            datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            self.active_chain.capitalize(),
            from_str,
            to_str,
            token,
            amt,
            "",  # Value
            f"[green]{status}[/green]",
            (tx_hash if tx_hash.startswith("0x") else f"0x{tx_hash}")[:10] + "..."
            if tx_hash
            else "",
            "?",  # Gas cost
            "?",  # Gas value
            "",  # Tags
            key=tx_hash,
        )
        try:
            table.sort("Time", reverse=True)
        except Exception:
            # Table sorting might fail in some contexts if ColumnKey is used internally
            pass

    def on_unmount(self) -> None:
        """Stop the monitor when the view is unmounted."""
        self.stop_monitor()

    def start_monitor(self) -> None:
        """Start background transaction monitor."""
        self.stop_monitor()
        addresses = [acc.address for acc in self.wallet.key_storage.accounts.values()]
        for chain_name, interface in ChainInterfaces().items():
            if interface.chain.rpc:
                monitor = EventMonitor(addresses, self.monitor_callback, chain_name)

                # Worker wrapper
                worker = MonitorWorker(monitor, self.app)
                self.monitor_workers.append(worker)

                # Launch as a Textual Worker
                self.run_worker(worker.run(), group="monitors", thread=False)

    def stop_monitor(self) -> None:
        """Stop background transaction monitor."""
        for worker in self.monitor_workers:
            worker.stop()
        self.monitor_workers.clear()
        # Cancel Textual workers in the 'monitors' group
        # self.workers.cancel_group("monitors") # Helper not always available, rely on worker.stop() setting flag

    def monitor_callback(self, txs: List[dict]) -> None:
        """Handle new transactions."""
        self.app.call_from_thread(self.handle_new_txs, txs)

    def handle_new_txs(self, txs: List[dict]) -> None:
        """Process new transactions."""
        self.refresh_accounts()
        for tx in txs:
            raw_ts = tx.get("timestamp")
            if raw_ts is None:
                raw_ts = time.time()
            f, t = tx["from"], tx["to"]
            token = tx.get("token", "NATIVE")
            amt = f"{float(tx.get('value', 0)) / 10**18:.4f}"
            tx_hash = tx["hash"]
            self.add_tx_history_row(f, t, token, amt, "Detected", tx_hash)
            if not any(
                acc.address.lower() == str(tx["from"]).lower()
                for acc in self.wallet.account_service.get_account_data().values()
            ):
                self.notify(f"New transaction detected! {tx['hash'][:6]}...", severity="info")
        self.enrich_and_log_txs(txs)

    def resolve_tag(self, address: str) -> str:
        """Resolve address to tag."""
        for acc in self.wallet.account_service.get_account_data().values():
            if acc.address.lower() == address.lower():
                return acc.tag
        config = Config()
        if config.core and config.core.whitelist:
            for name, addr in config.core.whitelist.items():
                if addr.lower() == address.lower():
                    return name
        return f"{address[:6]}...{address[-4:]}"

    @on(Button.Pressed)
    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press events."""
        if event.button.id == "create_eoa_btn":

            def handler(tag):
                if tag is not None:
                    tag = tag or f"Account {len(self.wallet.key_storage.accounts) + 1}"
                    self.wallet.key_storage.create_account(tag)
                    self.notify(f"Created new EOA: {escape(tag)}")
                    self.refresh_accounts()

            self.app.push_screen(CreateEOAModal(), handler)
        elif event.button.id == "create_safe_btn":
            accs = [(acc.tag, acc.address) for acc in self.wallet.key_storage.accounts.values()]

            def handler(result):
                if result:
                    tag = result.get("tag") or f"Safe {len(self.wallet.key_storage.accounts) + 1}"
                    if not result.get("owners") or not result.get("chains"):
                        self.notify("Missing owners or chains", severity="error")
                        return
                    self.create_safe_worker(
                        tag, result["threshold"], result["owners"], result["chains"]
                    )

            self.app.push_screen(CreateSafeModal(accs), handler)
        elif event.button.id == "send_btn":
            self.send_transaction()

    @work(exclusive=False, thread=True)
    def create_safe_worker(
        self, tag: str, threshold: int, owners: List[str], chains: List[str]
    ) -> None:
        """Worker to deploy a Safe multisig on multiple chains."""
        salt_nonce = int(time.time() * 1000)
        for chain_name in chains:
            try:
                self.app.call_from_thread(
                    self.notify,
                    f"Deploying Safe '{escape(tag)}' on {chain_name}...",
                    severity="info",
                )
                self.wallet.safe_service.create_safe(
                    "master", owners, threshold, chain_name, tag, salt_nonce
                )
                self.app.call_from_thread(
                    self.notify,
                    f"Safe '{escape(tag)}' created on {chain_name}!",
                    severity="success",
                )
            except Exception as e:
                logger.error(f"Failed to create Safe on {chain_name}: {e}")
                self.app.call_from_thread(
                    self.notify, f"Error on {chain_name}: {escape(str(e))}", severity="error"
                )
        self.app.call_from_thread(self.refresh_accounts)

    @on(Select.Changed, "#chain_select")
    async def on_chain_changed(self, event: Select.Changed) -> None:
        """Handle blockchain selection changes."""
        if event.value and event.value != self.active_chain:
            interface = ChainInterfaces().get(event.value)
            if not interface or not interface.chain.rpc:
                self.notify(f"No RPC for {event.value}", severity="warning")
                event.control.value = self.active_chain
                return
            self.active_chain = event.value
            await self.refresh_ui_for_chain()
            self.start_monitor()

    async def refresh_ui_for_chain(self) -> None:
        """Update UI elements for the currently selected chain."""
        self.query_one("#accounts_header", Label).update(
            f"Accounts ({self.active_chain.capitalize()})"
        )
        self.refresh_accounts()
        scroll = self.query_one("#token_toggles", Horizontal)
        interface = ChainInterfaces().get(self.active_chain)
        desired = set(interface.tokens.keys()) if interface else set()
        for child in list(scroll.children):
            if child.id and child.id.startswith("cb_") and child.id[3:] not in desired:
                child.remove()
        if interface:
            for token_name in interface.tokens.keys():
                cb_id = f"cb_{token_name}"
                is_checked = token_name in self.chain_token_states.get(self.active_chain, set())
                try:
                    cb = self.query_one(f"#{cb_id}", Checkbox)
                    cb.value = is_checked
                except Exception:
                    scroll.mount(Checkbox(token_name.upper(), value=is_checked, id=cb_id))

        form_container = self.query_one("#tx_form_container", Horizontal)
        await form_container.remove_children()
        native_symbol = interface.chain.native_currency if interface else "Native"
        token_options = [(native_symbol, "native")] + [
            (t.upper(), t) for t in (interface.tokens.keys() if interface else [])
        ]
        from_options = [(a.tag, a.address) for a in self.wallet.key_storage.accounts.values()]
        to_options = list(from_options)
        config = Config()
        if config.core and config.core.whitelist:
            for n, a in config.core.whitelist.items():
                to_options.append((n, a))

        form_container.mount(
            Select(from_options, prompt="From Address", id="from_addr"),
            Select(to_options, prompt="To Address", id="to_addr"),
            Input(placeholder="Amount", id="amount"),
            Select(token_options, value="native", id="token", allow_blank=False),
            Button("Send", id="send_btn", variant="primary"),
        )

    @on(Checkbox.Changed)
    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        """Handle token track checkbox changes."""
        if not event.checkbox.id or not event.checkbox.id.startswith("cb_"):
            return
        token_name = event.checkbox.id[3:]
        if self.active_chain not in self.chain_token_states:
            self.chain_token_states[self.active_chain] = set()
        if event.value:
            self.chain_token_states[self.active_chain].add(token_name)
            self.fetch_all_balances(self.active_chain, [token_name])
        else:
            self.chain_token_states[self.active_chain].discard(token_name)
            self.refresh_table_structure_and_data()

    def update_table_cell(self, row_key: str, col_index: int, value: str | Text) -> None:
        """Update a specific cell in the accounts table."""
        try:
            table = self.query_one(AccountTable)
            col_key = list(table.columns.keys())[col_index]
            table.update_cell(str(row_key), col_key, value)
        except Exception:
            pass

    @on(DataTable.CellSelected, "#accounts_table")
    def on_account_cell_selected(self, event: DataTable.CellSelected) -> None:
        """Handle account cell selection (copy address)."""
        if event.coordinate.column == 1:
            # event.value may be a Rich Text object, convert to plain string
            value = str(event.value.plain) if hasattr(event.value, "plain") else str(event.value)
            self.app.copy_to_clipboard(value)
            self.notify("Copied address to clipboard")

    @on(DataTable.CellSelected, "#tx_table")
    def on_tx_cell_selected(self, event: DataTable.CellSelected) -> None:
        """Handle transaction cell selection (copy hash)."""
        try:
            columns = list(event.data_table.columns.values())
            if "Hash" in str(columns[event.coordinate.column].label):
                # The row key contains the full hash
                full_hash = str(event.cell_key.row_key.value)
                if full_hash and full_hash.startswith("0x"):
                    self.app.copy_to_clipboard(full_hash)
                    self.notify("Copied hash to clipboard")
        except Exception:
            pass

    def send_transaction(self) -> None:
        """Initiate a transaction from the UI form."""
        try:
            f = self.query_one("#from_addr", Select).value
            t = self.query_one("#to_addr", Select).value
            amt = self.query_one("#amount", Input).value
            tok = self.query_one("#token", Select).value
            if not f or not t or not amt or not tok:
                self.notify("Missing fields", severity="error")
                return
            self.send_tx_worker(f, t, tok, float(amt))
        except Exception:
            pass

    @work(exclusive=True, thread=True)
    def send_tx_worker(self, f, t, token, amount) -> None:
        """Background worker for sending transactions."""
        try:
            # Let Wallet.send handle the conversion - it knows the token's decimals
            # For native currency, use standard 18 decimals
            # For ERC20, Wallet.send should handle it based on the token
            from web3 import Web3

            if token == "native":
                amount_wei = Web3.to_wei(amount, "ether")
            else:
                # For ERC20, get the token's decimals
                from iwa.core.chain import ChainInterfaces
                from iwa.core.contracts.erc20 import ERC20Contract

                chain_interface = ChainInterfaces().get(self.active_chain)
                token_address = chain_interface.chain.get_token_address(token)
                if token_address:
                    erc20 = ERC20Contract(token_address, self.active_chain)
                    amount_wei = int(amount * (10**erc20.decimals))
                else:
                    # Fallback to 18 decimals if token not found
                    amount_wei = Web3.to_wei(amount, "ether")

            tx_hash = self.wallet.send(f, t, amount_wei, token, self.active_chain)
            self.app.call_from_thread(self.notify, "Transaction sent!", severity="success")
            self.app.call_from_thread(
                self.add_tx_history_row, f, t, token, amount, "Pending", tx_hash
            )
        except Exception as e:
            self.app.call_from_thread(self.notify, f"Error: {escape(str(e))}", severity="error")

    def load_recent_txs(self):
        """Load recent transactions from the database."""
        try:
            from iwa.core.db import SentTransaction

            recent = (
                SentTransaction.select()
                .where(
                    (SentTransaction.chain == self.active_chain)
                    & (
                        SentTransaction.timestamp
                        > (datetime.datetime.now() - datetime.timedelta(hours=24))
                    )
                )
                .order_by(SentTransaction.timestamp.desc())
            )
            table = self.query_one(TransactionTable)
            table.clear()
            for tx in recent:
                ts = tx.timestamp.strftime("%Y-%m-%d %H:%M:%S")
                f, t = tx.from_tag or tx.from_address, tx.to_tag or tx.to_address
                symbol = tx.token
                if symbol and symbol.upper() in ["NATIVE", "NATIVE CURRENCY"]:
                    interface = ChainInterfaces().get(tx.chain)
                    symbol = interface.chain.native_currency if interface else "Native"
                    token_decimals = 18  # Native always 18
                else:
                    # Get token decimals for proper display
                    token_decimals = 18  # Default
                    try:
                        interface = ChainInterfaces().get(tx.chain)
                        if interface and tx.token:
                            token_address = interface.chain.get_token_address(tx.token)
                            if token_address:
                                from iwa.core.contracts.erc20 import ERC20Contract

                                erc20 = ERC20Contract(token_address, tx.chain)
                                token_decimals = erc20.decimals
                    except Exception:
                        pass  # Default to 18

                amt = f"{float(tx.amount_wei or 0) / (10**token_decimals):.4f}"
                val_eur = f"€{(tx.value_eur or 0.0):.2f}"
                gas_eur = f"€{tx.gas_value_eur:.4f}" if tx.gas_value_eur else "?"
                table.add_row(
                    ts,
                    str(tx.chain).capitalize(),
                    f,
                    t,
                    symbol,
                    amt,
                    val_eur,
                    "[green]Confirmed[/green]",
                    (tx.tx_hash if tx.tx_hash.startswith("0x") else f"0x{tx.tx_hash}")[:10] + "...",
                    str(tx.gas_cost or "0"),
                    gas_eur,
                    ", ".join(json.loads(tx.tags)) if tx.tags else "",
                    key=tx.tx_hash if tx.tx_hash.startswith("0x") else f"0x{tx.tx_hash}",
                )
        except Exception as e:
            logger.error(f"Failed to load txs: {e}")

    @work(thread=True)
    def enrich_and_log_txs(self, txs: List[dict]) -> None:
        """Enrich transaction data and log to database."""
        from iwa.core.db import log_transaction

        price_cache = {}
        for tx in txs:
            try:
                tx_chain = tx.get("chain", self.active_chain)
                interface = ChainInterfaces().get(tx_chain)
                if not interface:
                    continue
                cg_id = {"ethereum": "ethereum", "gnosis": "dai", "base": "ethereum"}.get(
                    tx_chain, "ethereum"
                )
                if cg_id not in price_cache:
                    price_cache[cg_id] = self.price_service.get_token_price(cg_id, "eur")

                # Simplified resolution for now
                v_wei = int(tx.get("value", 0))
                v_eth = v_wei / 10**18
                v_eur = v_eth * price_cache[cg_id] if price_cache[cg_id] else None

                # Use the native currency symbol for this chain
                native_symbol = interface.chain.native_currency

                # Check if we should even send price data (only if we are confident it's a native tx)
                # Or let log_transaction handle the smart merging
                log_transaction(
                    tx_hash=tx["hash"],
                    from_addr=tx["from"],
                    from_tag=self.resolve_tag(tx["from"]),
                    to_addr=tx["to"],
                    to_tag=self.resolve_tag(tx["to"]),
                    token=native_symbol,
                    amount_wei=str(v_wei),
                    chain=tx_chain,
                    price_eur=price_cache[cg_id],
                    value_eur=v_eur,
                )
            except Exception as e:
                logger.error(f"Failed enrichment: {e}")
        self.app.call_from_thread(self.load_recent_txs)
