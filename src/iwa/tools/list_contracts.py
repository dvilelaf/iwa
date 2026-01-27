"""Tool to list Olas staking contracts status."""

import argparse
import logging

from rich.console import Console
from rich.progress import track
from rich.table import Table

from iwa.core.utils import configure_logger
from iwa.plugins.olas.constants import OLAS_TRADER_STAKING_CONTRACTS
from iwa.plugins.olas.contracts.staking import StakingContract

# Configure logger and silence noisy third-party loggers
configure_logger()
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


def fetch_contract_data(chain_name):
    """Fetch data for all contracts."""
    contracts_map = OLAS_TRADER_STAKING_CONTRACTS.get(chain_name, {})
    contract_data = []

    for name, address in track(contracts_map.items(), description="Fetching contract data..."):
        try:
            contract = StakingContract(address, chain_name=chain_name)

            # Needed Olas (Bond + Deposit)
            needed_olas = (contract.min_staking_deposit * 2) / 1e18

            # Slots
            service_ids = contract.get_service_ids()
            max_slots = contract.max_num_services

            # Rewards & Balance
            rewards_olas = contract.available_rewards / 1e18
            balance_olas = contract.balance / 1e18

            contract_data.append(
                {
                    "name": name,
                    "needed_olas": needed_olas,
                    "occupied_slots": len(service_ids),
                    "max_slots": max_slots,
                    "free_slots": max_slots - len(service_ids),
                    "rewards_olas": rewards_olas,
                    "balance_olas": balance_olas,
                    "epoch_end": contract.get_next_epoch_start(),
                    "error": None,
                }
            )
        except Exception as e:
            contract_data.append({"name": name, "error": str(e)})

    return contract_data


def sort_contract_data(contract_data, sort_criterion):
    """Sort contract data based on criterion."""
    if sort_criterion == "name":
        contract_data.sort(key=lambda x: x["name"])
    elif sort_criterion == "rewards":
        contract_data.sort(
            key=lambda x: (x.get("rewards_olas", -1) if not x.get("error") else -1), reverse=True
        )
    elif sort_criterion == "epoch":
        safe_max = 32503680000
        contract_data.sort(key=lambda x: safe_max if x.get("error") else x["epoch_end"].timestamp())
    elif sort_criterion == "slots":
        contract_data.sort(
            key=lambda x: (x.get("free_slots", -1) if not x.get("error") else -1), reverse=True
        )
    elif sort_criterion == "olas":
        contract_data.sort(
            key=lambda x: (
                x.get("needed_olas", float("inf")) if not x.get("error") else float("inf")
            )
        )


def print_table(console, contract_data, chain_name, sort_criterion):
    """Print the contracts table."""
    table = Table(title=f"Olas Staking Contracts ({chain_name}) - Sorted by: {sort_criterion}")
    table.add_column("Contract Name", style="cyan", no_wrap=True)
    table.add_column("Necessary Olas", justify="right", style="green")
    table.add_column("Slots (Free/Max)", justify="right", style="magenta")
    table.add_column("Available Rewards", justify="right", style="yellow")
    table.add_column("Contract Balance", justify="right", style="blue")
    table.add_column("Epoch End (UTC)", justify="right", style="white")
    table.add_column("Epoch End (Local)", justify="right", style="white")

    for item in contract_data:
        if item.get("error"):
            table.add_row(item["name"], "ERROR", "-", "-", "-", item["error"])
        else:
            table.add_row(
                item["name"],
                f"{item['needed_olas']:,.0f} OLAS",
                f"{item['free_slots']}/{item['max_slots']}",
                f"{item['rewards_olas']:,.2f} OLAS",
                f"{item['balance_olas']:,.2f} OLAS",
                item["epoch_end"].strftime("%Y-%m-%d %H:%M:%S"),
                item["epoch_end"].astimezone().strftime("%Y-%m-%d %H:%M:%S"),
            )
    console.print(table)


def main():
    """Run the contracts list tool."""
    args = parse_args()
    console = Console()
    chain_name = "gnosis"

    if chain_name not in OLAS_TRADER_STAKING_CONTRACTS:
        console.print(f"[red]No contracts found for chain {chain_name}[/red]")
        return

    contract_data = fetch_contract_data(chain_name)
    sort_contract_data(contract_data, args.sort)
    print_table(console, contract_data, chain_name, args.sort)


if __name__ == "__main__":
    main()
