"""UI utilities for mnemonic handling."""

import getpass
import os

from rich import box
from rich.align import Align
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from iwa.core.mnemonic import MnemonicManager


def prompt_and_store_mnemonic(
    manager: MnemonicManager, out_file: str = None, max_attempts: int = 3
) -> None:
    """Prompt for a password twice, verify they match, and store mnemonic.

    Args:
        manager (MnemonicManager): The manager instance.
        out_file (str): Optional destination file for the encrypted object.
        max_attempts (int): Number of attempts allowed for confirmation.

    Returns:
        str | None: The plaintext mnemonic if successful, otherwise None.

    """
    target_file = out_file or manager.mnemonic_file
    if os.path.exists(target_file):
        print(f"Mnemonic file '{target_file}' already exists.")
        return None

    for _ in range(max_attempts):
        p1 = getpass.getpass("Enter a strong password to encrypt the mnemonic: ").strip()
        if not p1:
            print("Empty password not allowed.")
            continue
        p2 = getpass.getpass("Confirm password: ").strip()
        if p1 != p2:
            print("Passwords do not match. Please try again.")
            continue
        # Passwords match — generate and store mnemonic
        manager.generate_and_store_mnemonic(p1, target_file)
        return None
    raise ValueError("Maximum password attempts exceeded.")


def display_mnemonic(
    mnemonic: str,
    columns: int = 6,
    rows: int = 4,
) -> None:
    """Format and print a mnemonic as a numbered table wrapped in a Panel.

    Args:
        mnemonic (str): The plaintext mnemonic (space separated words).
        columns (int): Number of columns per row (default 6).
        rows (int): Number of rows (default 4).

    """
    words = mnemonic.split()
    console = Console()
    # build table without internal borders; we'll wrap it in a Panel
    table = Table(
        show_header=False,
        box=None,
        show_lines=False,
        expand=False,
    )
    # add columns
    for _ in range(columns):
        table.add_column(justify="left")
    # warning: advise user to create a paper backup
    console.print(
        "[bold yellow]Warning:[/bold yellow] Make a paper backup of "
        "your mnemonic and store it in a safe place:"
    )
    # prepare numbered cells (colored green) with padded indices
    cells = []
    for i, w in enumerate(words):
        cells.append(f"[green]{i + 1:2d}. {w}[/green]")
    # add rows of `columns` columns
    for r in range(rows):
        start = r * columns
        row = cells[start : start + columns]
        # if row shorter than columns, pad with empty strings
        if len(row) < columns:
            row += [""] * (columns - len(row))
        table.add_row(*row)
    # wrap table in a panel to draw only the outer border
    panel = Panel(
        table,
        box=box.ROUNDED,
        border_style="bright_blue",
        padding=(0, 1),
        expand=False,
    )
    console.print(Align.center(panel))
