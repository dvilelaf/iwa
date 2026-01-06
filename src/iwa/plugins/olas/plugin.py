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
        # Note: Manager logic currently depends on internal config state which might need setup
        manager.create(chain_name, owner, token, bond)

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

            from iwa.core.settings import settings

            rpc_secret = getattr(settings, f"{chain_name}_rpc", None)
            if not rpc_secret:
                return None, None  # Can't verify, skip

            ethereum_client = EthereumClient(rpc_secret.get_secret_value())
            safe = Safe(safe_address, ethereum_client)
            owners = safe.retrieve_owners()
            return owners, True
        except Exception:
            # Query failed - Safe likely doesn't exist
            return [], False

    def _display_service_table(self, console, service, index: int) -> None:
        """Display a single discovered service as a Rich table."""
        from rich.table import Table

        table = Table(
            title=f"Service {index}: {service.service_name or 'Unknown'}", show_header=False
        )
        table.add_column("Property", style="cyan")
        table.add_column("Value")

        table.add_row("Format", service.format)
        table.add_row("Source", str(service.source_folder))
        table.add_row("Service ID", str(service.service_id) if service.service_id else "N/A")
        table.add_row("Chain", service.chain_name)

        # Verify Safe and display
        on_chain_signers, safe_exists = None, None
        if service.safe_address:
            on_chain_signers, safe_exists = self._get_safe_signers(
                service.safe_address, service.chain_name
            )
            if safe_exists is None:
                table.add_row("Safe", service.safe_address)
            elif safe_exists:
                table.add_row("Safe", f"{service.safe_address} [green]✓[/green]")
            else:
                table.add_row(
                    "Safe",
                    f"[bold red]⚠ {service.safe_address} - DOES NOT EXIST ON-CHAIN![/bold red]",
                )
        else:
            table.add_row("Safe", "N/A")

        # Display keys with signer verification
        for key in service.keys:
            status = "🔒 encrypted" if key.is_encrypted else "🔓 plaintext"
            key_info = f"{key.address} {status}"

            if key.role == "agent" and service.safe_address:
                if not safe_exists:
                    key_info = f"[bold red]⚠ {key.address} - NOT A SIGNER OF THE SAFE![/bold red]"
                elif on_chain_signers is not None:
                    is_signer = key.address.lower() in [s.lower() for s in on_chain_signers]
                    if not is_signer:
                        key_info = (
                            f"[bold red]⚠ {key.address} - NOT A SIGNER OF THE SAFE![/bold red]"
                        )

            table.add_row(f"Key ({key.role})", key_info)

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
        importer = OlasServiceImporter()
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
