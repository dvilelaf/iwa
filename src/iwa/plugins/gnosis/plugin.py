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
        return {"create-safe": self.create_safe_command}

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
