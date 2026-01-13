"""Tool to list Olas staking contracts status."""

import argparse
import logging
from datetime import datetime

from rich.console import Console
from rich.progress import track
from rich.table import Table

from iwa.core.utils import configure_logger
from iwa.plugins.olas.constants import OLAS_TRADER_STAKING_CONTRACTS
from iwa.plugins.olas.contracts.staking import StakingContract

# Configure logger to avoid noise during execution
logger = configure_logger()
logging.getLogger("web3").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="List Olas staking contracts.")
    parser.add_argument(
        "--sort",
        type=str,
        choices=["name", "rewards", "epoch", "slots", "olas"],
        default="name",
        help="Sort by field (default: name)",
    )
    return parser.parse_args()


def main():
    """Run the contracts list tool."""
    args = parse_args()
    console = Console()

    # We focus on Gnosis chain as per usual context
    chain_name = "gnosis"
    contracts_map = OLAS_TRADER_STAKING_CONTRACTS.get(chain_name, {})

    if not contracts_map:
        console.print(f"[red]No contracts found for chain {chain_name}[/red]")
        return

    contract_data = []

    # Iterate over contracts with a progress bar
    for name, address in track(contracts_map.items(), description="Fetching contract data..."):
        try:
            # Instantiate contract - this fetches some data in __init__
            contract = StakingContract(address, chain_name=chain_name)

            # 1. Necessary Olas (Bond + Deposit)
            needed_wei = contract.min_staking_deposit * 2
            needed_olas = needed_wei / 1e18

            # 2. Slots
            service_ids = contract.get_service_ids()
            occupied = len(service_ids)
            max_slots = contract.max_num_services
            free_slots = max_slots - occupied

            # 3. Rewards
            rewards_wei = contract.available_rewards
            rewards_olas = rewards_wei / 1e18

            # 4. Balance
            balance_wei = contract.balance
            balance_olas = balance_wei / 1e18

            # 5. Epoch End
            epoch_end = contract.get_next_epoch_start()

            contract_data.append({
                "name": name,
                "needed_olas": needed_olas,
                "occupied_slots": occupied,
                "max_slots": max_slots,
                "free_slots": free_slots,
                "rewards_olas": rewards_olas,
                "balance_olas": balance_olas,
                "epoch_end": epoch_end,
                "error": None
            })

        except Exception as e:
            # Handle individual contract errors without crashing the whole list
            contract_data.append({
                "name": name,
                "error": str(e)
            })

    # Sort data
    if args.sort == "name":
        contract_data.sort(key=lambda x: x["name"])
    elif args.sort == "rewards":
        # Sort by rewards descending (highest rewards first)
        contract_data.sort(key=lambda x: (x.get("rewards_olas", -1) if not x.get("error") else -1), reverse=True)
    elif args.sort == "epoch":
        # Sort by epoch end ascending (sooner ending first)
        # Use simple future date for errors to put them last
        future = datetime.max.replace(tzinfo=None) # Ensure naive for comparison if needed, though objects are timezone-aware usually.
        # epoch_end is likely tz-aware UTC.
        # Making a safe key function
        SAFE_MAX_TIMESTAMP = 32503680000  # Year 3000
        def epoch_key(item):
            if item.get("error"):
                return SAFE_MAX_TIMESTAMP
            dt = item["epoch_end"]
            return dt.timestamp()

        contract_data.sort(key=epoch_key)
    elif args.sort == "slots":
        # Sort by free slots descending (most free slots first)
        contract_data.sort(key=lambda x: (x.get("free_slots", -1) if not x.get("error") else -1), reverse=True)
    elif args.sort == "olas":
        # Sort by needed olas ascending (cheapest first)
        contract_data.sort(key=lambda x: (x.get("needed_olas", float('inf')) if not x.get("error") else float('inf')))


    # Build Table
    table = Table(title=f"Olas Staking Contracts ({chain_name}) - Sorted by: {args.sort}")

    table.add_column("Contract Name", style="cyan", no_wrap=True)
    table.add_column("Necessary Olas", justify="right", style="green")
    table.add_column("Slots (Free/Max)", justify="right", style="magenta")
    table.add_column("Available Rewards", justify="right", style="yellow")
    table.add_column("Contract Balance", justify="right", style="blue")
    table.add_column("Epoch End (UTC)", justify="right", style="white")

    for item in contract_data:
        if item.get("error"):
            table.add_row(item["name"], "ERROR", "-", "-", "-", item["error"])
        else:
            epoch_str = item["epoch_end"].strftime("%Y-%m-%d %H:%M:%S")
            slots_str = f"{item['free_slots']}/{item['max_slots']}"

            table.add_row(
                item["name"],
                f"{item['needed_olas']:,.0f} OLAS",
                slots_str,
                f"{item['rewards_olas']:,.2f} OLAS",
                f"{item['balance_olas']:,.2f} OLAS",
                epoch_str,
            )

    console.print(table)


if __name__ == "__main__":
    main()
