"""Olas Services TUI View."""

from typing import TYPE_CHECKING, Optional

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, ScrollableContainer, Vertical
from textual.widgets import Button, DataTable, Label, Select, Static

if TYPE_CHECKING:
    from iwa.core.wallet import Wallet


class OlasView(Static):
    """Olas services view for TUI."""

    DEFAULT_CSS = """
    OlasView {
        height: 100%;
        padding: 1;
    }

    .olas-header {
        height: 3;
        margin-bottom: 1;
    }

    .services-container {
        height: 1fr;
    }

    .service-card {
        border: solid $primary;
        padding: 1;
        margin-bottom: 1;
        height: auto;
    }

    .service-title {
        text-style: bold;
        color: $accent;
    }

    .service-info-row {
        height: 1;
    }

    .staking-section {
        margin-top: 1;
        padding: 1;
        background: $surface;
    }

    .staking-label {
        color: $text-muted;
    }

    .staking-value {
        color: $success;
    }

    .staking-value.not-staked {
        color: $text-muted;
    }

    .rewards-value {
        color: $accent;
        text-style: bold;
    }

    .action-buttons {
        margin-top: 1;
        height: 3;
    }

    .action-buttons Button {
        margin-right: 1;
    }

    .accounts-table {
        height: auto;
        max-height: 10;
    }

    .empty-state {
        text-align: center;
        color: $text-muted;
        padding: 2;
    }
    """

    def __init__(self, wallet: Optional["Wallet"] = None):
        """Initialize the Olas view."""
        super().__init__()
        self._wallet = wallet
        self._chain = "gnosis"
        self._services_data = []

    def compose(self) -> ComposeResult:
        """Compose the Olas view."""
        with Vertical():
            # Header with chain selector and refresh
            with Horizontal(classes="olas-header"):
                yield Label("Chain: ", classes="label")
                yield Select(
                    [(c, c) for c in ["gnosis", "ethereum", "base"]],
                    value="gnosis",
                    id="olas-chain-select",
                )
                yield Button("Refresh", id="olas-refresh-btn", variant="default")

            # Services container
            with ScrollableContainer(classes="services-container", id="services-container"):
                yield Label("Loading services...", id="olas-loading", classes="empty-state")

    def on_mount(self) -> None:
        """Load services when mounted."""
        self.load_services()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        button_id = event.button.id
        if button_id == "olas-refresh-btn":
            self.load_services()
        elif button_id == "olas-create-service-btn":
            self.show_create_service_modal()
        elif button_id and button_id.startswith("claim-"):
            service_key = button_id.replace("claim-", "")
            self.claim_rewards(service_key)
        elif button_id and button_id.startswith("unstake-"):
            service_key = button_id.replace("unstake-", "")
            self.unstake_service(service_key)
        elif button_id and button_id.startswith("stake-"):
            service_key = button_id.replace("stake-", "")
            self.stake_service(service_key)
        elif button_id and button_id.startswith("drain-"):
            service_key = button_id.replace("drain-", "")
            self.drain_service(service_key)
        elif button_id and button_id.startswith("fund-"):
            service_key = button_id.replace("fund-", "")
            self.show_fund_service_modal(service_key)
        elif button_id and button_id.startswith("terminate-"):
            service_key = button_id.replace("terminate-", "")
            self.terminate_service(service_key)

    def on_select_changed(self, event: Select.Changed) -> None:
        """Handle chain selection change."""
        if event.select.id == "olas-chain-select":
            self._chain = str(event.value)
            self.load_services()

    def load_services(self) -> None:
        """Load Olas services for the selected chain."""
        container = self.query_one("#services-container", ScrollableContainer)

        # Clear existing content
        container.remove_children()

        if not self._wallet:
            container.mount(Label("Wallet not available", classes="empty-state"))
            return

        try:
            from iwa.core.models import Config
            from iwa.plugins.olas.models import OlasConfig
            from iwa.plugins.olas.service_manager import ServiceManager

            config = Config()

            # Check if Olas plugin is configured
            if "olas" not in config.plugins:
                container.mount(
                    Label(f"No Olas services configured for {self._chain}", classes="empty-state")
                )
                return

            olas_config = OlasConfig.model_validate(config.plugins["olas"])

            # Filter services by chain
            services = [
                (key, svc)
                for key, svc in olas_config.services.items()
                if svc.chain_name == self._chain
            ]

            if not services:
                container.mount(
                    Label(f"No Olas services found for {self._chain}", classes="empty-state")
                )
                return

            # Create a card for each service
            for service_key, service in services:
                manager = ServiceManager(self._wallet)
                manager.service = service
                staking_status = manager.get_staking_status()

                card = self._create_service_card(service_key, service, staking_status)
                container.mount(card)

            # Add Create Service button at the bottom
            container.mount(Button("Create New Service", id="olas-create-service-btn", variant="primary"))

        except Exception as e:
            container.mount(Label(f"Error loading services: {e}", classes="empty-state"))

    def _create_service_card(self, service_key: str, service, staking_status) -> Container:
        """Create a service card widget."""
        from iwa.plugins.olas.models import Service

        service: Service = service  # type hint

        # Get account info
        accounts_data = []

        if service.agent_address:
            native = self._get_balance(service.agent_address, "native")
            olas = self._get_balance(service.agent_address, "OLAS")
            tag = self._get_tag(service.agent_address)
            accounts_data.append(("Agent", tag or service.agent_address[:10] + "...", native, olas))

        if service.multisig_address:
            safe_addr = str(service.multisig_address)
            native = self._get_balance(safe_addr, "native")
            olas = self._get_balance(safe_addr, "OLAS")
            tag = self._get_tag(safe_addr)
            accounts_data.append(("Safe", tag or safe_addr[:10] + "...", native, olas))

        if service.service_owner_address:
            native = self._get_balance(str(service.service_owner_address), "native")
            olas = self._get_balance(str(service.service_owner_address), "OLAS")
            tag = self._get_tag(str(service.service_owner_address))
            accounts_data.append(
                ("Owner", tag or str(service.service_owner_address)[:10] + "...", native, olas)
            )

        # Build staking info
        is_staked = staking_status and staking_status.is_staked
        rewards = staking_status.accrued_reward_wei / 1e18 if staking_status else 0

        # Calculate epoch countdown
        epoch_text = "-"
        if staking_status and staking_status.remaining_epoch_seconds:
            hours = int(staking_status.remaining_epoch_seconds // 3600)
            mins = int((staking_status.remaining_epoch_seconds % 3600) // 60)
            epoch_text = f"{hours}h {mins}m"

        with Container(classes="service-card", id=f"card-{service_key}") as card:
            # Title
            yield Label(
                f"{service.service_name or 'Service'} #{service.service_id}",
                classes="service-title",
            )

            # Accounts table
            table = DataTable(classes="accounts-table")
            table.add_columns("Role", "Account", "Native", "OLAS")
            for row in accounts_data:
                table.add_row(*row)
            yield table

            # Staking info
            with Container(classes="staking-section"):
                yield Label(
                    f"Status: {'✓ STAKED' if is_staked else '○ NOT STAKED'}",
                    classes="staking-value" if is_staked else "staking-value not-staked",
                )
                if is_staked:
                    yield Label(f"Rewards: {rewards:.4f} OLAS", classes="rewards-value")
                    liveness = staking_status.mech_requests_this_epoch
                    required = staking_status.required_mech_requests
                    passed = "✓" if staking_status.liveness_ratio_passed else "⚠"
                    yield Label(f"Liveness: {liveness}/{required} {passed}", classes="staking-label")
                    yield Label(f"Epoch ends: {epoch_text}", classes="staking-label")

            # Action buttons - Order: Fund, Stake/Unstake, Drain, Terminate
            with Horizontal(classes="action-buttons"):
                if is_staked and rewards > 0:
                    yield Button(f"Claim {rewards:.2f} OLAS", id=f"claim-{service_key}", variant="primary")
                yield Button("Fund", id=f"fund-{service_key}", variant="primary")
                if is_staked:
                    yield Button("Unstake", id=f"unstake-{service_key}", variant="primary")
                else:
                    yield Button("Stake", id=f"stake-{service_key}", variant="primary")
                yield Button("Drain", id=f"drain-{service_key}", variant="warning")
                yield Button("Terminate", id=f"terminate-{service_key}", variant="error")

        return card

    def _get_balance(self, address: str, token: str) -> str:
        """Get balance for an address."""
        if not self._wallet:
            return "-"
        try:
            if token == "native":
                bal = self._wallet.get_native_balance_eth(address, self._chain)
                return f"{bal:.4f}" if bal else "0.0000"
            else:
                bal = self._wallet.balance_service.get_erc20_balance_wei(address, token, self._chain)
                return f"{bal / 1e18:.4f}" if bal else "0.0000"
        except Exception:
            return "-"

    def _get_tag(self, address: str) -> Optional[str]:
        """Get tag for an address if it exists."""
        if not self._wallet:
            return None
        try:
            stored = self._wallet.key_storage.find_stored_account(address)
            return stored.tag if stored else None
        except Exception:
            return None

    def claim_rewards(self, service_key: str) -> None:
        """Claim rewards for a service."""
        self.notify("Claiming rewards...", severity="information")
        try:
            from iwa.core.models import Config
            from iwa.plugins.olas.contracts.staking import StakingContract
            from iwa.plugins.olas.models import OlasConfig
            from iwa.plugins.olas.service_manager import ServiceManager

            config = Config()
            olas_config = OlasConfig.model_validate(config.plugins["olas"])
            service = olas_config.services[service_key]

            manager = ServiceManager(self._wallet)
            manager.service = service

            staking = StakingContract(service.staking_contract_address, service.chain_name)
            success, amount = manager.claim_rewards(staking_contract=staking)

            if success:
                self.notify(f"Claimed {amount / 1e18:.4f} OLAS!", severity="information")
                self.load_services()
            else:
                self.notify("Claim failed", severity="error")
        except Exception as e:
            self.notify(f"Error: {e}", severity="error")

    def stake_service(self, service_key: str) -> None:
        """Stake a service."""
        from iwa.plugins.olas.constants import OLAS_TRADER_STAKING_CONTRACTS
        from iwa.tui.modals.base import StakeServiceModal

        contracts_dict = OLAS_TRADER_STAKING_CONTRACTS.get(self._chain, {})
        if not contracts_dict:
            self.notify(f"No staking contracts for {self._chain}", severity="error")
            return

        contracts = [(name, str(addr)) for name, addr in contracts_dict.items()]

        def on_modal_result(contract_address: Optional[str]) -> None:
            if not contract_address:
                return

            self.notify("Staking...", severity="information")
            try:
                from iwa.plugins.olas.contracts.staking import StakingContract
                from iwa.plugins.olas.service_manager import ServiceManager

                manager = ServiceManager(self._wallet, service_key=service_key)
                staking = StakingContract(contract_address, self._chain)
                success = manager.stake(staking)

                if success:
                    self.notify("Service staked!", severity="information")
                    self.load_services()
                else:
                    self.notify("Stake failed", severity="error")
            except Exception as e:
                self.notify(f"Error: {e}", severity="error")

        self.app.push_screen(StakeServiceModal(contracts), on_modal_result)

    def unstake_service(self, service_key: str) -> None:
        """Unstake a service."""
        self.notify("Unstaking...", severity="information")
        try:
            from iwa.core.models import Config
            from iwa.plugins.olas.contracts.staking import StakingContract
            from iwa.plugins.olas.models import OlasConfig
            from iwa.plugins.olas.service_manager import ServiceManager

            config = Config()
            olas_config = OlasConfig.model_validate(config.plugins["olas"])
            service = olas_config.services[service_key]

            manager = ServiceManager(self._wallet)
            manager.service = service

            staking = StakingContract(service.staking_contract_address, service.chain_name)
            success = manager.unstake(staking)

            if success:
                self.notify("Service unstaked!", severity="information")
                self.load_services()
            else:
                self.notify("Unstake failed", severity="error")
        except Exception as e:
            self.notify(f"Error: {e}", severity="error")

    def drain_service(self, service_key: str) -> None:
        """Drain all service accounts."""
        self.notify("Draining service...", severity="information")
        try:
            from iwa.plugins.olas.service_manager import ServiceManager

            manager = ServiceManager(self._wallet, service_key=service_key)
            drained = manager.drain_service()

            # Format summary
            accounts = list(drained.keys()) if drained else []
            self.notify(f"Drained accounts: {', '.join(accounts) or 'none'}", severity="information")
            self.load_services()
        except Exception as e:
            self.notify(f"Error: {e}", severity="error")

    def show_create_service_modal(self) -> None:
        """Show modal to create a new service."""
        from iwa.tui.modals.base import CreateServiceModal

        chains = ["gnosis"]  # Only gnosis has staking contracts

        def on_modal_result(result) -> None:
            if not result:
                return

            self.notify("Creating and deploying service...", severity="information")
            try:
                from iwa.plugins.olas.service_manager import ServiceManager

                manager = ServiceManager(self._wallet)
                service_id = manager.create(
                    chain_name=result["chain"],
                    service_name=result["name"],
                )

                if not service_id:
                    self.notify("Failed to create service", severity="error")
                    return

                # Spin up to fully deploy
                spin_up_success = manager.spin_up()

                if spin_up_success:
                    self.notify(f"Service deployed! ID: {service_id}", severity="information")
                else:
                    self.notify(f"Service created (ID: {service_id}) but deployment failed", severity="warning")
                self.load_services()
            except Exception as e:
                self.notify(f"Error: {e}", severity="error")

        self.app.push_screen(CreateServiceModal(chains, self._chain), on_modal_result)

    def show_fund_service_modal(self, service_key: str) -> None:
        """Show modal to fund a service."""
        from web3 import Web3

        from iwa.tui.modals.base import FundServiceModal

        # Get native symbol for current chain
        native_symbol = "xDAI" if self._chain == "gnosis" else "ETH"

        def on_modal_result(result) -> None:
            if not result:
                return

            self.notify("Funding service...", severity="information")
            try:
                from iwa.core.models import Config
                from iwa.plugins.olas.models import OlasConfig

                config = Config()
                olas_config = OlasConfig.model_validate(config.plugins["olas"])
                service = olas_config.services[service_key]

                # Fund agent
                if result["agent_amount"] > 0 and service.agent_address:
                    self._wallet.send(
                        from_address_or_tag="master",
                        to_address_or_tag=service.agent_address,
                        amount_wei=Web3.to_wei(result["agent_amount"], "ether"),
                        token_address_or_name="native",
                        chain_name=service.chain_name,
                    )

                # Fund safe
                if result["safe_amount"] > 0 and service.multisig_address:
                    self._wallet.send(
                        from_address_or_tag="master",
                        to_address_or_tag=str(service.multisig_address),
                        amount_wei=Web3.to_wei(result["safe_amount"], "ether"),
                        token_address_or_name="native",
                        chain_name=service.chain_name,
                    )

                self.notify("Service funded!", severity="information")
                self.load_services()
            except Exception as e:
                self.notify(f"Error: {e}", severity="error")

        self.app.push_screen(FundServiceModal(service_key, native_symbol), on_modal_result)

    def terminate_service(self, service_key: str) -> None:
        """Terminate (wind down) a service."""
        self.notify("Terminating service...", severity="information")
        try:
            from iwa.core.models import Config
            from iwa.plugins.olas.contracts.staking import StakingContract
            from iwa.plugins.olas.models import OlasConfig
            from iwa.plugins.olas.service_manager import ServiceManager

            config = Config()
            olas_config = OlasConfig.model_validate(config.plugins["olas"])
            service = olas_config.services[service_key]

            manager = ServiceManager(self._wallet)
            manager.service = service

            # Get staking contract if staked
            staking_contract = None
            if service.staking_contract_address:
                staking_contract = StakingContract(service.staking_contract_address, service.chain_name)

            success = manager.wind_down(staking_contract=staking_contract)

            if success:
                self.notify("Service terminated!", severity="information")
                self.load_services()
            else:
                self.notify("Failed to terminate service", severity="error")
        except Exception as e:
            self.notify(f"Error: {e}", severity="error")

