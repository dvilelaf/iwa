"""Olas plugin."""

from pathlib import Path
from typing import Dict, Optional, Type

import typer
from pydantic import BaseModel

from iwa.core.plugins import Plugin
from iwa.core.wallet import Wallet
from iwa.plugins.olas.models import OlasConfig
from iwa.plugins.olas.service_manager import ServiceManager


class OlasPlugin(Plugin):
    """Olas Plugin."""

    @property
    def name(self) -> str:
        """Get plugin name."""
        return "olas"

    @property
    def config_model(self) -> Type[BaseModel]:
        """Get config model."""
        return OlasConfig

    def get_cli_commands(self) -> Dict[str, callable]:
        """Get CLI commands."""
        return {
            "create": self.create_service,
            "import": self.import_services,
        }

    def get_tui_view(self, wallet=None):
        """Get TUI widget for this plugin."""
        from iwa.plugins.olas.tui.olas_view import OlasView

        return OlasView(wallet=wallet)

    def create_service(
        self,
        chain_name: str = typer.Option("gnosis", "--chain", "-c"),
        owner: Optional[str] = typer.Option(None, "--owner", "-o"),
        token: Optional[str] = typer.Option(None, "--token"),
        bond: int = typer.Option(1, "--bond", "-b"),
    ):
        """Create a new Olas service"""
        wallet = Wallet()
        manager = ServiceManager(wallet)
        manager.create(
            chain_name=chain_name,
            service_owner_address_or_tag=owner,
            token_address_or_tag=token,
            bond_amount_wei=bond,
        )

    def _get_safe_signers(self, safe_address: str, chain_name: str) -> tuple:
        """Query Safe signers on-chain.

        Returns:
            Tuple of (signers_list, safe_exists):
            - (list, True) if Safe exists and query succeeds
            - ([], False) if Safe doesn't exist on-chain
            - (None, None) if RPC not configured (skip verification)

        """
        try:
            from safe_eth.eth import EthereumClient
            from safe_eth.safe import Safe

            from iwa.core.chain import ChainInterfaces

            try:
                chain_interface = ChainInterfaces().get(chain_name)
                if not chain_interface.current_rpc:
                    return None, None
            except ValueError:
                return None, None  # Chain not supported/configured

            ethereum_client = EthereumClient(chain_interface.current_rpc)
            safe = Safe(safe_address, ethereum_client)
            owners = safe.retrieve_owners()
            return owners, True
        except Exception:
            # Query failed - Safe likely doesn't exist
            return [], False

    def _resolve_staking_name(self, address: str, chain_name: str) -> str | None:
        """Resolve staking contract address to human-readable name."""
        from iwa.plugins.olas.constants import OLAS_TRADER_STAKING_CONTRACTS

        chain_contracts = OLAS_TRADER_STAKING_CONTRACTS.get(chain_name, {})
        addr_lower = address.lower()
        for name, contract_addr in chain_contracts.items():
            if str(contract_addr).lower() == addr_lower:
                return name
        return None

    def _display_service_table(self, console, service, index: int) -> None:
        """Display a single discovered service as a Rich table."""
        from rich.table import Table

        from iwa.plugins.olas.constants import OLAS_TRADER_STAKING_CONTRACTS

        table = Table(
            title=f"Service {index}: {service.service_name or 'Unknown'}", show_header=False
        )
        table.add_column("Property", style="cyan")
        table.add_column("Value")

        table.add_row("Format", service.format)
        table.add_row("Source", str(service.source_folder))
        table.add_row("Service ID", str(service.service_id) if service.service_id else "[red]Not detected[/red]")
        table.add_row("Chain", service.chain_name)

        # Verify Safe and display
        on_chain_signers, safe_exists = None, None
        if service.safe_address:
            on_chain_signers, safe_exists = self._get_safe_signers(
                service.safe_address, service.chain_name
            )
            safe_color = "green" if safe_exists else "white"
            safe_text = service.safe_address
            if safe_exists:
                safe_text += " [green]✓[/green]"
            elif safe_exists is False:
                safe_text = f"[bold red]⚠ {service.safe_address} - DOES NOT EXIST ON-CHAIN![/bold red]"

            table.add_row("Multisig", safe_text)
        else:
            table.add_row("Multisig", "[red]Not detected[/red]")

        # Display staking contract info (always show)
        if service.staking_contract_address:
            staking_name = self._resolve_staking_name(
                service.staking_contract_address, service.chain_name
            )
            if staking_name:
                table.add_row("Staking", f"{staking_name}")
                table.add_row("Staking Addr", service.staking_contract_address)
            else:
                table.add_row("Staking", "[red]Unknown[/red]")
                table.add_row("Staking Addr", service.staking_contract_address)
        else:
            table.add_row("Staking", "[red]Not detected[/red]")
            table.add_row("Staking Addr", "[red]Not detected[/red]")

        # Display owner (address + encryption status if key available)
        owner_key = next((k for k in service.keys if k.role == "owner"), None)
        owner_addr = service.service_owner_address
        if not owner_addr and owner_key:
            owner_addr = owner_key.address

        if owner_addr:
            val = owner_addr
            if owner_key:
                if owner_key.signature_verified:
                    val = f"[green]{owner_addr}[/green]"
                elif not owner_key.is_encrypted:
                    # Plaintext key that wasn't verified = failed
                    val = f"[red]{owner_addr}[/red]"
                # Encrypted keys stay white (can't verify without password)

                status = "🔒 encrypted" if owner_key.is_encrypted else "🔓 plaintext"
                table.add_row("Owner", f"{val} {status}")
            else:
                table.add_row("Owner", val)
        else:
            table.add_row("Owner", "[red]Not detected[/red]")

        # Display agent key
        agent_key = next((k for k in service.keys if k.role == "agent"), None)

        if agent_key:
            status = "🔒 encrypted" if agent_key.is_encrypted else "🔓 plaintext"
            addr_val = agent_key.address
            if agent_key.signature_verified:
                addr_val = f"[green]{agent_key.address}[/green]"
            elif not agent_key.is_encrypted:
                # Plaintext key that wasn't verified = failed
                addr_val = f"[red]{agent_key.address}[/red]"
            # Encrypted keys stay white (can't verify without password)

            key_info = f"{addr_val} {status}"
            if service.safe_address:
                if safe_exists is False:
                    key_info = f"[bold red]⚠ {agent_key.address} - NOT A SIGNER OF THE SAFE![/bold red]"
                elif on_chain_signers is not None:
                    is_signer = agent_key.address.lower() in [s.lower() for s in on_chain_signers]
                    if not is_signer:
                        key_info = f"[bold red]⚠ {agent_key.address} - NOT A SIGNER OF THE SAFE![/bold red]"
            table.add_row("Agent", key_info)
        else:
            table.add_row("Agent", "[red]Not detected[/red]")

        console.print(table)
        console.print()

    def _import_and_print_results(self, console, importer, discovered, password) -> tuple:
        """Import all discovered services and print results."""
        total_keys = 0
        total_safes = 0
        total_services = 0
        all_skipped = []
        all_errors = []

        for service in discovered:
            console.print(
                f"\n[bold]Importing[/bold] {service.service_name or service.source_folder}..."
            )
            result = importer.import_service(service, password)

            total_keys += len(result.imported_keys)
            total_safes += len(result.imported_safes)
            total_services += len(result.imported_services)
            all_skipped.extend(result.skipped)
            all_errors.extend(result.errors)

            if result.imported_keys:
                console.print(
                    f"  [green]✓[/green] Imported keys: {', '.join(result.imported_keys)}"
                )
            if result.imported_safes:
                console.print(
                    f"  [green]✓[/green] Imported safes: {', '.join(result.imported_safes)}"
                )
            if result.imported_services:
                console.print(
                    f"  [green]✓[/green] Imported services: {', '.join(result.imported_services)}"
                )
            if result.skipped:
                for item in result.skipped:
                    console.print(f"  [yellow]⊘[/yellow] Skipped: {item}")
            if result.errors:
                for error in result.errors:
                    console.print(f"  [red]✗[/red] Error: {error}")

        return total_keys, total_safes, total_services, all_skipped, all_errors

    def import_services(
        self,
        path: str = typer.Argument(..., help="Directory to scan for Olas services"),
        dry_run: bool = typer.Option(
            False, "--dry-run", "-n", help="Show what would be imported without making changes"
        ),
        password: Optional[str] = typer.Option(
            None, "--password", "-p", help="Password for encrypted keys (will prompt if needed)"
        ),
        yes: bool = typer.Option(
            False, "--yes", "-y", help="Import all without confirmation prompts"
        ),
    ):
        """Import Olas services and keys from external directories."""
        from rich.console import Console

        from iwa.plugins.olas.importer import OlasServiceImporter

        console = Console()

        # Scan directory
        console.print(f"\n[bold]Scanning[/bold] {path}...")

        # Ask for password in dry-run to allow signature verification of encrypted keys
        if dry_run and not password:
            password = typer.prompt(
                "Enter wallet password to verify encrypted keys (optional, press Enter to skip)",
                hide_input=True,
                default="",
            )
            if not password:
                password = None

        importer = OlasServiceImporter(password=password)
        discovered = importer.scan_directory(Path(path))

        if not discovered:
            console.print("[yellow]No Olas services found.[/yellow]")
            raise typer.Exit(code=0)

        # Display discovered services
        console.print(f"\n[bold green]Found {len(discovered)} service(s):[/bold green]\n")
        for i, service in enumerate(discovered, 1):
            self._display_service_table(console, service, i)

        if dry_run:
            console.print("[yellow]Dry run mode - no changes made.[/yellow]")
            raise typer.Exit(code=0)

        # Confirm import
        if not yes:
            confirm = typer.confirm("Import these services?")
            if not confirm:
                console.print("[yellow]Aborted.[/yellow]")
                raise typer.Exit(code=0)

        # Check if we need a password for encrypted keys
        needs_password = any(key.is_encrypted for service in discovered for key in service.keys)
        if needs_password and not password:
            console.print(
                "\n[yellow]Some keys are encrypted. Please enter the source password.[/yellow]"
            )
            password = typer.prompt("Password", hide_input=True)

        # Import services
        total_keys, total_safes, total_services, all_skipped, all_errors = (
            self._import_and_print_results(console, importer, discovered, password)
        )

        # Summary
        console.print("\n[bold]Summary:[/bold]")
        console.print(f"  Keys imported: {total_keys}")
        console.print(f"  Safes imported: {total_safes}")
        console.print(f"  Services imported: {total_services}")
        if all_skipped:
            console.print(f"  Skipped: {len(all_skipped)}")
        if all_errors:
            console.print(f"  [red]Errors: {len(all_errors)}[/red]")
            raise typer.Exit(code=1)
