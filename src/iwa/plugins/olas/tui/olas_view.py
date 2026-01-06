"""Olas Services TUI View."""

from typing import TYPE_CHECKING, List, Optional

from textual import work
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, ScrollableContainer, Vertical
from textual.widgets import Button, DataTable, Label, Select, Static

if TYPE_CHECKING:
    from iwa.core.wallet import Wallet

from iwa.core.types import EthereumAddress


class OlasView(Static):
    """Olas services view for TUI."""

    DEFAULT_CSS = """
    OlasView {
        height: auto;
        min-height: 10;
    }

    .olas-header {
        height: 3;
        margin-bottom: 1;
    }

    .services-container {
        height: auto;
        min-height: 5;
    }

    .service-card {
        border: solid $primary;
        padding: 0 1;
        margin-bottom: 1;
        height: auto;
    }

    .service-title {
        text-style: bold;
        color: $accent;
        margin-bottom: 0;
    }

    .staking-section {
        margin-top: 0;
        padding: 0 1;
        background: $surface;
        height: auto;
    }

    .staking-label {
        color: $text-muted;
        height: 1;
    }

    .staking-value {
        color: $success;
        height: 1;
    }

    .staking-value.not-staked {
        color: $text-muted;
    }

    .rewards-value {
        color: $accent;
        text-style: bold;
        height: 1;
    }

    .action-buttons {
        margin-top: 0;
        height: 3;
    }

    .action-buttons Button {
        margin-right: 1;
    }

    .accounts-table {
        height: auto;
        max-height: 6;
    }

    .empty-state {
        text-align: center;
        color: $text-muted;
        padding: 2;
    }

    .olas-price {
        text-align: center;
        color: $success;
        padding: 1 0;
        text-style: bold;
    }
    """

    def __init__(self, wallet: Optional["Wallet"] = None):
        """Initialize the Olas view."""
        super().__init__()
        self._wallet = wallet
        self._chain = "gnosis"
        self._services_data = []
        self._loading = False  # Guard against duplicate worker execution

    def compose(self) -> ComposeResult:
        """Compose the Olas view."""
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
        yield Label("OLAS: --", id="olas-price-label", classes="olas-price")
        yield ScrollableContainer(id="services-container")

    def on_mount(self) -> None:
        """Load services when mounted."""
        self.load_services()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        button_id = event.button.id
        if not button_id:
            return

        if button_id == "olas-refresh-btn":
            self.load_services()
        elif button_id == "olas-create-service-btn":
            self.show_create_service_modal()
        else:
            self._handle_service_action_button(button_id)

    def _handle_service_action_button(self, button_id: str) -> None:
        """Handle service-specific action buttons.

        Maps button ID prefixes to handler methods.
        """
        # Map prefixes to handler methods
        handlers = {
            "claim-": self.claim_rewards,
            "unstake-": self.unstake_service,
            "stake-": self.stake_service,
            "drain-": self.drain_service,
            "fund-": self.show_fund_service_modal,
            "terminate-": self.terminate_service,
            "checkpoint-": self.checkpoint_service,
            "deploy-": self.deploy_service,
        }

        for prefix, handler in handlers.items():
            if button_id.startswith(prefix):
                # Convert sanitized ID back to original key format
                # e.g. gnosis_2594 -> gnosis:2594
                service_key = button_id.replace(prefix, "").replace("_", ":", 1)
                handler(service_key)
                return

    def on_select_changed(self, event: Select.Changed) -> None:
        """Handle chain selection change."""
        if event.select.id == "olas-chain-select":
            self._chain = str(event.value)
            self.load_services()

    @work(thread=True)
    def load_services(self) -> None:
        """Load Olas services for the selected chain in background thread."""
        # Prevent duplicate execution
        if self._loading:
            return
        self._loading = True

        if not self._wallet:
            self.app.call_from_thread(self._mount_error, "Wallet not available")
            self._loading = False
            return

        try:
            from iwa.core.models import Config
            from iwa.plugins.olas.models import OlasConfig
            from iwa.plugins.olas.service_manager import ServiceManager

            config = Config()

            if "olas" not in config.plugins:
                self.app.call_from_thread(
                    self._mount_error, f"No Olas services configured for {self._chain}"
                )
                self._loading = False
                return

            olas_config = OlasConfig.model_validate(config.plugins["olas"])

            services = [
                (key, svc)
                for key, svc in olas_config.services.items()
                if svc.chain_name == self._chain
            ]

            if not services:
                self.app.call_from_thread(
                    self._mount_error, f"No Olas services found for {self._chain}"
                )
                self._loading = False
                return

            # Fetch data in background thread (network calls)
            services_data = []
            for service_key, service in services:
                manager = ServiceManager(self._wallet)
                manager.service = service
                staking_status = manager.get_staking_status()
                service_state = manager.get_service_state()
                services_data.append((service_key, service, staking_status, service_state))

            # Fetch OLAS price
            olas_price = None
            try:
                from iwa.core.pricing import PriceService

                price_service = PriceService()
                olas_price = price_service.get_token_price("autonolas", "eur")
            except Exception:
                pass  # Price fetch is optional

            self.app.call_from_thread(self._render_services, services_data, olas_price)

        except Exception as e:
            import traceback

            traceback.print_exc()
            self.app.call_from_thread(self._mount_error, f"Error loading services: {e}")
        finally:
            self._loading = False

    async def _render_services(
        self, services_data: list, olas_price: Optional[float] = None
    ) -> None:
        """Create and mount service cards in UI thread."""
        try:
            # Update OLAS price label
            try:
                price_label = self.query_one("#olas-price-label", Label)
                if olas_price:
                    price_label.update(f"OLAS: €{olas_price:.2f}")
                else:
                    price_label.update("OLAS: --")
            except Exception:
                pass  # Label might not exist yet

            container = self.query_one("#services-container", ScrollableContainer)
            # Synchronously (as much as possible) clear children
            # Querying and removing is safer than remove_children() when mounting immediately
            children = container.query(".service-card")
            if children:
                await children.remove()

            # Use a slightly different approach: clear everything and wait
            await container.query("*").remove()

            if not services_data:
                await container.mount(
                    Label("No services found on this chain.", classes="empty-state")
                )
            else:
                for service_key, service, staking_status, service_state in services_data:
                    card = self._create_service_card(
                        service_key, service, staking_status, service_state
                    )
                    await container.mount(card)

            await container.mount(
                Button("Create New Service", id="olas-create-service-btn", variant="primary")
            )
        except Exception:
            import traceback

            traceback.print_exc()

    def _mount_cards(self, cards: list) -> None:
        """Mount service cards (called from UI thread)."""
        try:
            container = self.query_one("#services-container", ScrollableContainer)
            container.remove_children()
            for card in cards:
                container.mount(card)
            container.mount(
                Button("Create New Service", id="olas-create-service-btn", variant="primary")
            )
        except Exception:
            pass

    def _mount_error(self, message: str) -> None:
        """Mount error message (called from UI thread)."""
        try:
            container = self.query_one("#services-container", ScrollableContainer)
            container.remove_children()
            container.mount(Label(message, classes="empty-state"))
        except Exception:
            pass

    def _create_service_card(
        self, service_key: str, service, staking_status, service_state: str = "UNKNOWN"
    ) -> Container:
        """Create a service card widget."""
        from iwa.plugins.olas.models import Service

        service: Service = service  # type hint

        # Sanitize service_key for use in widget IDs (colons not allowed)
        safe_key = service_key.replace(":", "_")

        # Build accounts logic
        accounts_data = self._build_accounts_data(service)

        # Build staking logic
        staking_info = self._build_staking_info(staking_status)
        is_staked = staking_info["is_staked"]
        rewards = staking_info["rewards"]
        checkpoint_pending = staking_info["checkpoint_pending"]

        # Calculate countdowns
        epoch_text = self._get_epoch_text(staking_status)
        unstake_text = self._get_unstake_text(staking_status)

        # Build accounts table
        table = DataTable(classes="accounts-table")
        table.add_columns("Role", "Account", "Native", "OLAS")
        for row in accounts_data:
            table.add_row(*row)

        # Build staking labels
        staking_widgets = [
            Label(
                f"Status: {'✓ STAKED' if is_staked else '○ NOT STAKED'}",
                classes="staking-value" if is_staked else "staking-value not-staked",
            )
        ]
        if is_staked:
            contract_name = staking_status.staking_contract_name if staking_status else "-"
            staking_widgets.append(
                Label(f"Contract: {contract_name or '-'}", classes="staking-label")
            )
            staking_widgets.append(Label(f"Rewards: {rewards:.4f} OLAS", classes="rewards-value"))
            liveness = staking_status.mech_requests_this_epoch
            required = staking_status.required_mech_requests
            passed = "✓" if staking_status.liveness_ratio_passed else "⚠"
            staking_widgets.append(
                Label(f"Liveness: {liveness}/{required} {passed}", classes="staking-label")
            )
            epoch_num = staking_status.epoch_number if staking_status else "?"
            staking_widgets.append(
                Label(f"Epoch #{epoch_num} ends in: {epoch_text}", classes="staking-label")
            )
            staking_widgets.append(
                Label(f"Unstake available: {unstake_text}", classes="staking-label")
            )
        staking_section = Vertical(*staking_widgets, classes="staking-section")

        # Build action buttons based on service state
        is_pre_registration = service_state == "PRE_REGISTRATION"
        is_deployed = service_state == "DEPLOYED"

        button_list = []

        # Deploy button for PRE_REGISTRATION services
        if is_pre_registration:
            button_list.append(Button("Deploy", id=f"deploy-{safe_key}", variant="success"))
        else:
            button_list.append(Button("Fund", id=f"fund-{safe_key}", variant="primary"))

        if is_staked and checkpoint_pending:
            button_list.append(Button("Checkpoint", id=f"checkpoint-{safe_key}", variant="warning"))
        if is_staked and rewards > 0:
            button_list.append(
                Button(f"Claim {rewards:.2f} OLAS", id=f"claim-{safe_key}", variant="primary")
            )
        if is_deployed and is_staked:
            button_list.append(Button("Unstake", id=f"unstake-{safe_key}", variant="primary"))
        elif is_deployed and not is_staked:
            button_list.append(Button("Stake", id=f"stake-{safe_key}", variant="primary"))

        if not is_pre_registration:
            button_list.append(Button("Drain", id=f"drain-{safe_key}", variant="warning"))
            # Can only terminate if not staked
            if not is_staked:
                button_list.append(Button("Terminate", id=f"terminate-{safe_key}", variant="error"))

        buttons = Horizontal(*button_list, classes="action-buttons")

        # Build card
        card = Vertical(
            Label(
                f"{service.service_name or 'Service'} #{service.service_id}",
                classes="service-title",
            ),
            table,
            staking_section,
            buttons,
            classes="service-card",
            id=f"card-{safe_key}",
        )

        return card

    def _get_balance(self, address: EthereumAddress, token: str) -> str:
        """Get balance for an address."""
        if not self._wallet:
            return "-"
        try:
            if token == "native":
                bal = self._wallet.get_native_balance_eth(address, self._chain)
                return f"{bal:.4f}" if bal else "0.0000"
            else:
                bal = self._wallet.balance_service.get_erc20_balance_wei(
                    address, token, self._chain
                )
                return f"{bal / 1e18:.4f}" if bal else "0.0000"
        except Exception:
            return "-"

    def _get_tag(self, address: EthereumAddress) -> Optional[str]:
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
        """Stake a service with bond-compatible contracts only."""
        from iwa.plugins.olas.constants import OLAS_TRADER_STAKING_CONTRACTS

        contracts_dict = OLAS_TRADER_STAKING_CONTRACTS.get(self._chain, {})
        if not contracts_dict:
            self.notify(f"No staking contracts for {self._chain}", severity="error")
            return

        # 1. Get service bond (security_deposit)
        service_bond = self._get_service_bond(service_key)
        service_bond_olas = service_bond / 10**18 if service_bond else 0

        # 2. Filter contracts
        filtered_contracts = self._get_compatible_staking_contracts(contracts_dict, service_bond)

        if not filtered_contracts:
            if service_bond_olas is not None:
                self.notify(
                    f"No compatible contracts! Your service bond ({service_bond_olas:.0f} OLAS) "
                    "is lower than what staking contracts require.",
                    severity="warning",
                    timeout=10,
                )
            else:
                self.notify("No staking contracts available", severity="error")
            return

        # 3. Show info if some contracts were filtered
        total_contracts = len(contracts_dict)
        if len(filtered_contracts) < total_contracts:
            hidden = total_contracts - len(filtered_contracts)
            self.notify(
                f"Showing {len(filtered_contracts)} of {total_contracts} contracts "
                f"({hidden} hidden - require higher bond)",
                severity="information",
            )

        # 4. Show modal
        self._show_stake_contracts_modal(filtered_contracts, service_key)

    def _get_service_bond(self, service_key: str) -> Optional[int]:
        """Fetch the security deposit (bond) for a service."""
        from iwa.plugins.olas.service_manager import ServiceManager

        try:
            manager = ServiceManager(self._wallet, service_key=service_key)
            if manager.service:
                service_info = manager.registry.get_service(manager.service.service_id)
                return service_info.get("security_deposit", 0)
        except Exception as e:
            self.notify(f"Warning: Could not fetch service bond: {e}", severity="warning")
        return None

    def _get_compatible_staking_contracts(
        self, contracts_dict: dict, service_bond: Optional[int]
    ) -> List[tuple]:
        """Filter staking contracts based on bond requirements and slots."""
        import json

        from iwa.core.chain import ChainInterface
        from iwa.plugins.olas.contracts.base import OLAS_ABI_PATH

        w3 = ChainInterface(self._chain).web3
        with open(OLAS_ABI_PATH / "staking.json", "r") as f:
            abi = json.load(f)

        filtered_contracts = []
        for name, addr in contracts_dict.items():
            try:
                contract = w3.eth.contract(address=str(addr), abi=abi)
                min_deposit = contract.functions.minStakingDeposit().call()

                # Skip if service bond is too low
                if service_bond is not None and service_bond < min_deposit:
                    continue

                # Check available slots
                service_ids = contract.functions.getServiceIds().call()
                max_services = contract.functions.maxNumServices().call()
                available_slots = max_services - len(service_ids)

                if available_slots > 0:
                    filtered_contracts.append((f"{name} ({available_slots} slots)", str(addr)))
            except Exception:
                # If we can't check, include it
                filtered_contracts.append((name, str(addr)))
        return filtered_contracts

    def _show_stake_contracts_modal(
        self, filtered_contracts: List[tuple], service_key: str
    ) -> None:
        """Show the modal to select a staking contract."""
        from iwa.tui.modals.base import StakeServiceModal

        def on_modal_result(contract_address: Optional[str]) -> None:
            if not contract_address:
                return
            self._execute_stake_service(service_key, contract_address)

        self.app.push_screen(StakeServiceModal(filtered_contracts), on_modal_result)

    def _execute_stake_service(self, service_key: str, contract_address: str) -> None:
        """Execute the staking transaction."""
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
            self.notify(
                f"Drained accounts: {', '.join(accounts) or 'none'}", severity="information"
            )
            self.load_services()
        except Exception as e:
            self.notify(f"Error: {e}", severity="error")

    def show_create_service_modal(self) -> None:
        """Show modal to create a new service."""
        from iwa.tui.modals.base import CreateServiceModal

        chains = ["gnosis"]  # Only gnosis has staking contracts

        # 1. Fetch staking contracts with available slots
        staking_contracts = self._fetch_create_service_options()

        # 2. Define callback
        def on_modal_result(result) -> None:
            if not result:
                return
            self._handle_create_service_result(result)

        # 3. Show modal
        self.app.push_screen(
            CreateServiceModal(chains, self._chain, staking_contracts), on_modal_result
        )

    def _fetch_create_service_options(self) -> List[tuple]:
        """Fetch staking contracts with available slots for creation modal."""
        staking_contracts = []
        try:
            import json

            from iwa.core.chain import ChainInterface
            from iwa.plugins.olas.constants import OLAS_TRADER_STAKING_CONTRACTS
            from iwa.plugins.olas.contracts.base import OLAS_ABI_PATH

            contracts_dict = OLAS_TRADER_STAKING_CONTRACTS.get(self._chain, {})

            # Load ABI and check slots for each contract
            w3 = ChainInterface(self._chain).web3
            with open(OLAS_ABI_PATH / "staking.json", "r") as f:
                abi = json.load(f)

            for name, addr in contracts_dict.items():
                try:
                    contract = w3.eth.contract(address=str(addr), abi=abi)
                    service_ids = contract.functions.getServiceIds().call()
                    max_services = contract.functions.maxNumServices().call()
                    available_slots = max_services - len(service_ids)

                    if available_slots > 0:
                        staking_contracts.append((f"{name} ({available_slots} slots)", str(addr)))
                except Exception:
                    # If we can't check, include it without slot info
                    staking_contracts.append((name, str(addr)))
        except Exception:
            pass  # If fetch fails, just use empty list
        return staking_contracts

    def _handle_create_service_result(self, result: dict) -> None:
        """Handle the result from the create service modal."""
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
                # If staking contract was selected, stake the service
                if result.get("staking_contract"):
                    try:
                        manager.stake(result["staking_contract"])
                        self.notify(
                            f"Service deployed and staked! ID: {service_id}",
                            severity="information",
                        )
                    except Exception as e:
                        self.notify(
                            f"Service deployed (ID: {service_id}) but staking failed: {e}",
                            severity="warning",
                        )
                else:
                    self.notify(f"Service deployed! ID: {service_id}", severity="information")
            else:
                self.notify(
                    f"Service created (ID: {service_id}) but deployment failed",
                    severity="warning",
                )
            self.load_services()
        except Exception as e:
            self.notify(f"Error: {e}", severity="error")

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
                staking_contract = StakingContract(
                    service.staking_contract_address, service.chain_name
                )

            success = manager.wind_down(staking_contract=staking_contract)

            if success:
                self.notify("Service terminated!", severity="information")
                self.load_services()
            else:
                self.notify("Failed to terminate service", severity="error")
        except Exception as e:
            self.notify(f"Error: {e}", severity="error")

    def checkpoint_service(self, service_key: str) -> None:
        """Call checkpoint on a staking contract to close the epoch."""
        self.notify("Calling checkpoint...", severity="information")
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
            success = manager.call_checkpoint(staking)

            if success:
                self.notify("Checkpoint successful! Epoch closed.", severity="information")
                self.load_services()
            else:
                self.notify("Checkpoint failed", severity="error")
        except Exception as e:
            self.notify(f"Error: {e}", severity="error")

    def deploy_service(self, service_key: str) -> None:
        """Deploy a service from PRE_REGISTRATION to DEPLOYED state."""
        from iwa.core.models import Config
        from iwa.plugins.olas.models import OlasConfig
        from iwa.plugins.olas.service_manager import ServiceManager

        self.notify("Deploying service...", severity="information")

        try:
            config = Config()
            if "olas" not in config.plugins:
                self.notify("Olas plugin not configured", severity="error")
                return

            olas_config = OlasConfig.model_validate(config.plugins["olas"])
            if service_key not in olas_config.services:
                self.notify(f"Service {service_key} not found", severity="error")
                return

            service = olas_config.services[service_key]

            manager = ServiceManager(self._wallet)
            manager.service = service

            success = manager.spin_up()

            if success:
                self.notify(
                    "Service deployed successfully! State: DEPLOYED",
                    severity="information",
                )
                self.load_services()
            else:
                self.notify("Deployment failed", severity="error")
        except Exception as e:
            self.notify(f"Deployment error: {e}", severity="error")

    def _build_accounts_data(self, service) -> List[tuple]:
        """Build accounts data list."""
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
        return accounts_data

    def _build_staking_info(self, staking_status) -> dict:
        """Build staking info dict."""
        is_staked = staking_status and staking_status.is_staked
        rewards = staking_status.accrued_reward_wei / 1e18 if staking_status else 0
        checkpoint_pending = (
            staking_status
            and staking_status.remaining_epoch_seconds is not None
            and staking_status.remaining_epoch_seconds <= 0
        )
        return {
            "is_staked": is_staked,
            "rewards": rewards,
            "checkpoint_pending": checkpoint_pending,
        }

    def _get_epoch_text(self, staking_status) -> str:
        """Get epoch countdown text."""
        epoch_text = "-"
        if staking_status and staking_status.remaining_epoch_seconds is not None:
            if staking_status.remaining_epoch_seconds <= 0:
                epoch_text = "Checkpoint pending"
            else:
                hours = int(staking_status.remaining_epoch_seconds // 3600)
                mins = int((staking_status.remaining_epoch_seconds % 3600) // 60)
                epoch_text = f"{hours}h {mins}m"
        return epoch_text

    def _get_unstake_text(self, staking_status) -> str:
        """Get unstake countdown text."""
        unstake_text = "-"
        if staking_status and staking_status.unstake_available_at:
            from datetime import datetime, timezone

            try:
                # Parse ISO format string
                unstake_dt = datetime.fromisoformat(
                    staking_status.unstake_available_at.replace("Z", "+00:00")
                )
                now = datetime.now(timezone.utc)
                diff = (unstake_dt - now).total_seconds()
                if diff <= 0:
                    unstake_text = "AVAILABLE"
                else:
                    hours = int(diff // 3600)
                    mins = int((diff % 3600) // 60)
                    unstake_text = f"{hours}h {mins}m"
            except Exception:
                unstake_text = "-"
        return unstake_text
