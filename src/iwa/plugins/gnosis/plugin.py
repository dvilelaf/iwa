"""Gnosis Safe plugin."""

from typing import Dict, Optional

import typer

from iwa.core.keys import KeyStorage
from iwa.core.plugins import Plugin


class GnosisPlugin(Plugin):
    """Gnosis Safe Plugin."""

    @property
    def name(self) -> str:
        """Get plugin name."""
        return "gnosis"

    def get_cli_commands(self) -> Dict[str, callable]:
        """Get CLI commands."""
        return {
            "create-safe": self.create_safe_command,
            "send-noop": self.send_noop_command,
            "allocator-invalidate": self.allocator_invalidate_command,
            "nonce-check": self.nonce_check_command,
        }

    def create_safe_command(
        self,
        tag: Optional[str] = typer.Option(
            None,
            "--tag",
            "-t",
            help="Tag for this account",
        ),
        owners: str = typer.Option(
            ...,
            "--owners",
            "-o",
            help="Comma-separated list of owner addresses or tags.",
        ),
        threshold: int = typer.Option(
            ...,
            "--threshold",
            "-h",
            help="Number of required confirmations.",
        ),
        chain_name: str = typer.Option(
            "gnosis",
            "--chain",
            "-c",
            help="Chain to deploy the multisig on.",
        ),
    ):
        """Create a new multisig account (Safe)"""
        from iwa.core.services import AccountService, SafeService

        key_storage = KeyStorage()
        account_service = AccountService(key_storage)
        safe_service = SafeService(key_storage, account_service)

        owner_list = [owner.strip() for owner in owners.split(",")]
        try:
            safe_service.create_safe(
                deployer_tag_or_address="master",
                owner_tags_or_addresses=owner_list,
                threshold=threshold,
                chain_name=chain_name,
                tag=tag,
            )
        except ValueError as e:
            typer.echo(f"Error: {e}")
            raise typer.Exit(code=1) from e

    def send_noop_command(
        self,
        safe_address: str = typer.Argument(..., help="Safe address or tag"),
        chain_name: str = typer.Option(
            "gnosis", "--chain", "-c", help="Chain name"
        ),
    ):
        """Send a zero-value native transfer from the Safe to itself.

        Advances the on-chain Safe nonce by 1. Use this to unblock a stuck
        nonce when a pending TX has been dropped from the mempool.
        See: docs/runbook_safe_nonce_stuck.md

        NOTE: Run only when the main micromech process is stopped or when you
        are certain no other process is using the NonceAllocator for this Safe.
        Concurrent use can cause nonce collisions.
        """
        from iwa.core.services import AccountService, SafeService

        key_storage = KeyStorage()
        account_service = AccountService(key_storage)
        safe_service = SafeService(key_storage, account_service)
        try:
            tx_hash = safe_service.execute_safe_transaction(
                safe_address_or_tag=safe_address,
                to=safe_address,
                value=0,
                chain_name=chain_name,
                data="",
            )
            typer.echo(f"Noop TX submitted: {tx_hash}")
        except Exception as e:
            typer.echo(f"Error: {e}", err=True)
            raise typer.Exit(code=1) from e

    def allocator_invalidate_command(
        self,
        safe_address: str = typer.Argument(..., help="Safe address or tag"),
        chain_name: str = typer.Option(
            "gnosis", "--chain", "-c", help="Chain name"
        ),
    ):
        """Force-invalidate the NonceAllocator for a Safe.

        Causes the allocator to refetch the on-chain nonce on the next TX.

        WARNING: This creates a fresh SafeService instance in this CLI process.
        The running micromech process has its own allocator that is NOT affected
        by this command. To invalidate the live allocator, restart micromech:
          ssh triton "cd /opt/micromech && just update"
        """
        from iwa.core.services import AccountService, SafeService

        key_storage = KeyStorage()
        account_service = AccountService(key_storage)
        safe_service = SafeService(key_storage, account_service)
        typer.echo(
            "WARNING: this command operates on a LOCAL allocator instance only.",
            err=True,
        )
        typer.echo(
            "The running micromech process is NOT affected."
            " To invalidate the live allocator, restart micromech:",
            err=True,
        )
        typer.echo('  ssh triton "cd /opt/micromech && just update"', err=True)
        try:
            allocator = safe_service.get_allocator(safe_address, chain_name)
            allocator.invalidate("cli_manual")
            s = allocator.stats()
            typer.echo(
                f"Allocator invalidated for {safe_address[:10]}... on {chain_name}"
            )
            typer.echo(
                f"allocate_count={s['allocate_count']}"
                f"  invalidate_count={s['invalidate_count']}"
            )
        except Exception as e:
            typer.echo(f"Error: {e}", err=True)
            raise typer.Exit(code=1) from e

    def nonce_check_command(
        self,
        safe_address: str = typer.Argument(..., help="Safe address or tag"),
        chain_name: str = typer.Option(
            "gnosis", "--chain", "-c", help="Chain name"
        ),
        threshold: int = typer.Option(
            3,
            "--threshold",
            "-t",
            help="Gap threshold above which a warning is shown.",
        ),
    ):
        """Show on-chain Safe nonce and signer EOA mempool nonce pair."""
        from iwa.core.services import AccountService, SafeService

        key_storage = KeyStorage()
        account_service = AccountService(key_storage)
        safe_service = SafeService(key_storage, account_service)
        try:
            safe_nonce = safe_service.get_safe_nonce(safe_address, chain_name)
            confirmed, pending = safe_service.get_eoa_nonce_pair(
                safe_address, chain_name
            )
            gap = pending - confirmed
            typer.echo(f"Safe nonce (on-chain):      {safe_nonce}")
            typer.echo(f"EOA signer confirmed nonce: {confirmed}")
            typer.echo(f"EOA signer pending nonce:   {pending}")
            typer.echo(f"EOA mempool gap:            {gap}")
            if gap > threshold:
                typer.echo(
                    f"WARNING: gap {gap} > {threshold} — possible stuck TX in mempool.",
                    err=True,
                )
        except Exception as e:
            typer.echo(f"Error: {e}", err=True)
            raise typer.Exit(code=1) from e
