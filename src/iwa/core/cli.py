"""CLI"""

from typer import Typer
from wallet import Wallet

iwa_cli = Typer(help="iwa command line interface")
wallet_cli = Typer(help="Manage wallet")

iwa_cli.add_typer(wallet_cli, name="wallet")


@wallet_cli.command()
def wallet_list():
    """List wallet accounts"""
    wallet = Wallet.load()
    wallet.list_accounts()


if __name__ == "__main__":
    iwa_cli()
