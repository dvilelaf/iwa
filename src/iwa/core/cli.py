"""CLI"""

from typing import Optional

import typer

from iwa.core.constants import NATIVE_CURRENCY_ADDRESS
from iwa.core.keys import KeyStorage
from iwa.core.wallet import Wallet

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
        raise typer.Exit(code=1)


@wallet_cli.command("create-multisig")
def create_safe(
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
    key_storage = KeyStorage()
    owner_list = [owner.strip() for owner in owners.split(",")]
    try:
        key_storage.create_safe(
            deployer_tag_or_address="master",
            owner_tags_or_addresses=owner_list,
            threshold=threshold,
            chain_name=chain_name,
            tag=tag,
        )
    except ValueError as e:
        typer.echo(f"Error: {e}")
        raise typer.Exit(code=1)


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
    wallet.list_accounts(chain_name, balances)


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
    amount: float = typer.Option(..., "--amount", "-a", help="Amount to send, in ether"),
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
        amount_eth=amount,
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
    amount: float = typer.Option(..., "--amount", "-a", help="Amount to transfer, in ether"),
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
        amount=amount,
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
    amount: float = typer.Option(..., "--amount", "-a", help="Amount to approve, in ether"),
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
        amount=amount,
        chain_name=chain,
    )


if __name__ == "__main__":
    iwa_cli()
