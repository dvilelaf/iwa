"""Olas plugin."""

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
        }

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
