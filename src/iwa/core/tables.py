"""Account storage protocol definitions"""

from typing import Dict, List, Optional

from rich.console import Console
from rich.table import Table
from rich.text import Text

from iwa.core.chain import ChainInterface
from iwa.core.models import StoredSafeAccount


def list_accounts(
    accounts: Optional[Dict],
    chain_interface: ChainInterface,
    token_names: Optional[List[str]],
    token_balances: Optional[Dict],
) -> None:
    """List accounts"""
    console = Console()
    table = Table(
        title="Accounts",
        show_header=True,
    )

    table.add_column("Address", style="dim", width=42, justify="center")
    table.add_column("Type", style="dim", width=10, justify="center")
    table.add_column("Tag", style="dim", width=20, justify="center")

    if token_names:
        for token_name in token_names:
            token = (
                chain_interface.chain.native_currency
                if token_name == "native"
                else token_name.upper()
            )
            table.add_column(f"Balance {token}", style="dim", justify="center")

    if accounts:
        for acct in accounts.values():
            acct_type = "Safe" if isinstance(acct, StoredSafeAccount) else "EOA"
            tag_cell = Text(acct.tag, style="bold green")
            args = (acct.address, acct_type, tag_cell)
            if token_balances:
                balances = token_balances.get(acct.address)
                for token_name, token_balance in balances.items():
                    token = (
                        chain_interface.chain.native_currency
                        if token_name == "native"
                        else token_name.upper()
                    )
                    args += (f"{token_balance:.2f} {token}",)
            table.add_row(*args)
    else:
        row_args = ("No accounts found", "-")
        if token_balances:
            row_args += tuple("-" for _ in token_balances)
        table.add_row(*row_args)

    console.print(table, justify="center")
