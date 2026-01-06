"""CLI"""

from typing import Optional

import typer
from web3 import Web3

from iwa.core.chain import ChainInterfaces
from iwa.core.constants import NATIVE_CURRENCY_ADDRESS
from iwa.core.keys import KeyStorage
from iwa.core.services import PluginService
from iwa.core.tables import list_accounts
from iwa.core.wallet import Wallet
from iwa.tui.app import IwaApp

iwa_cli = typer.Typer(help="iwa command line interface")
wallet_cli = typer.Typer(help="Manage wallet")

iwa_cli.add_typer(wallet_cli, name="wallet")


@wallet_cli.command("create")
def account_create(
    tag: Optional[str] = typer.Option(
        None,
        "--tag",
        "-t",
        help="Tag for this account",
    ),
):
    """Create a new wallet account"""
    key_storage = KeyStorage()
    try:
        key_storage.create_account(tag)
    except ValueError as e:
        typer.echo(f"Error: {e}")
        raise typer.Exit(code=1) from e


@wallet_cli.command("list")
def account_list(
    chain_name: Optional[str] = typer.Option(
        "gnosis",
        "--chain",
        "-c",
        help="Chain to retrieve balances from.",
    ),
    balances: Optional[str] = typer.Option(
        None,
        "--balances",
        "-b",
        help="Comma-separated list of token names to fetch balances for. Use 'native' for native currency.",
    ),
):
    """List wallet accounts"""
    wallet = Wallet()
    chain_interface = ChainInterfaces().get(chain_name)
    token_names_list = balances.split(",") if balances else []

    accounts_data, token_balances = wallet.get_accounts_balances(chain_name, token_names_list)

    list_accounts(
        accounts_data,
        chain_interface,
        token_names_list,
        token_balances,
    )


@wallet_cli.command("send")
def account_send(
    from_address_or_tag: str = typer.Option(..., "--from", "-f", help="From address or tag"),
    to_address_or_tag: str = typer.Option(..., "--to", "-t", help="To address or tag"),
    token_address_or_name: str = typer.Option(
        NATIVE_CURRENCY_ADDRESS,
        "--token",
        "-k",
        help="ERC20 token contract address, ignore for native",
    ),
    amount_eth: float = typer.Option(..., "--amount", "-a", help="Amount to send, in ether"),
    chain: str = typer.Option(
        "gnosis",
        "--chain",
        help="Chain to send from",
    ),
):
    """Send native currency or ERC20 tokens to an address"""
    wallet = Wallet()
    wallet.send(
        from_address_or_tag=from_address_or_tag,
        to_address_or_tag=to_address_or_tag,
        token_address_or_name=token_address_or_name,
        amount_wei=Web3.to_wei(amount_eth, "ether"),
        chain_name=chain,
    )


@wallet_cli.command("transfer-from")
def erc20_transfer_from(
    from_address_or_tag: str = typer.Option(..., "--from", "-f", help="From address or tag"),
    sender_address_or_tag: str = typer.Option(..., "--sender", "-s", help="Sender address or tag"),
    recipient_address_or_tag: str = typer.Option(
        ..., "--recipient", "-r", help="Recipient address or tag"
    ),
    token_address_or_name: str = typer.Option(
        ..., "--token", "-k", help="ERC20 token contract address"
    ),
    amount_eth: float = typer.Option(..., "--amount", "-a", help="Amount to transfer, in ether"),
    chain: str = typer.Option(
        "gnosis",
        "--chain",
        help="Chain to send from",
    ),
):
    """Transfer ERC20 tokens from a sender to a recipient using allowance"""
    wallet = Wallet()
    wallet.transfer_from_erc20(
        from_address_or_tag=from_address_or_tag,
        sender_address_or_tag=sender_address_or_tag,
        recipient_address_or_tag=recipient_address_or_tag,
        token_address_or_name=token_address_or_name,
        amount_wei=Web3.to_wei(amount_eth, "ether"),
        chain_name=chain,
    )


@wallet_cli.command("approve")
def erc20_approve(
    owner_address_or_tag: str = typer.Option(..., "--owner", "-f", help="Owner address or tag"),
    spender_address_or_tag: str = typer.Option(
        ..., "--spender", "-t", help="Spender address or tag"
    ),
    token_address_or_name: str = typer.Option(
        ..., "--token", "-k", help="ERC20 token contract address"
    ),
    amount_eth: float = typer.Option(..., "--amount", "-a", help="Amount to approve, in ether"),
    chain: str = typer.Option(
        "gnosis",
        "--chain",
        help="Chain to send from",
    ),
):
    """Approve ERC20 token allowance for a spender"""
    wallet = Wallet()
    wallet.approve_erc20(
        owner_address_or_tag=owner_address_or_tag,
        spender_address_or_tag=spender_address_or_tag,
        token_address_or_name=token_address_or_name,
        amount_wei=Web3.to_wei(amount_eth, "ether"),
        chain_name=chain,
    )


@iwa_cli.command("tui")
def tui():
    """Start Terminal User Interface."""
    app = IwaApp()
    app.run()


@iwa_cli.command("web")
def web_server(
    port: Optional[int] = typer.Option(None, "--port", "-p", help="Port to listen on"),
    host: str = typer.Option("127.0.0.1", "--host", "-h", help="Host to listen on"),
):
    """Start Web Interface."""
    from iwa.core.settings import settings
    from iwa.web.server import run_server

    server_port = port or settings.web_port
    typer.echo(f"Starting web server on http://{host}:{server_port}")
    run_server(host=host, port=server_port)


@wallet_cli.command("drain")
def drain_wallet(
    from_address_or_tag: str = typer.Option(..., "--from", "-f", help="From address or tag"),
    to_address_or_tag: str = typer.Option(..., "--to", "-t", help="To address or tag"),
    chain_name: str = typer.Option(
        "gnosis",
        "--chain",
        "-c",
        help="Chain to drain from.",
    ),
):
    """Drain all tokens and native currency from one wallet to another"""
    wallet = Wallet()
    wallet.drain(
        from_address_or_tag=from_address_or_tag,
        to_address_or_tag=to_address_or_tag,
        chain_name=chain_name,
    )


# Load Plugins
# Removed direct import here, moved to top

plugin_service = PluginService()
plugins = plugin_service.get_all_plugins()

for plugin_name, plugin in plugins.items():
    commands = plugin.get_cli_commands()
    if commands:
        plugin_app = typer.Typer(help=f"{plugin_name} commands")
        for cmd_name, cmd_func in commands.items():
            plugin_app.command(name=cmd_name)(cmd_func)
        iwa_cli.add_typer(plugin_app, name=plugin_name)

if __name__ == "__main__":  # pragma: no cover
    iwa_cli()
