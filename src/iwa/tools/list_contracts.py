"""Tool to list Olas staking contracts status."""

from rich.console import Console
from rich.progress import track
from rich.table import Table

from iwa.plugins.olas.constants import OLAS_TRADER_STAKING_CONTRACTS
from iwa.plugins.olas.contracts.staking import StakingContract


def main():
    """Run the contracts list tool."""
    console = Console()

    # We focus on Gnosis chain as per usual context
    chain_name = "gnosis"
    contracts_map = OLAS_TRADER_STAKING_CONTRACTS.get(chain_name, {})

    if not contracts_map:
        console.print(f"[red]No contracts found for chain {chain_name}[/red]")
        return

    table = Table(title=f"Olas Staking Contracts ({chain_name})")

    table.add_column("Contract Name", style="cyan", no_wrap=True)
    table.add_column("Necessary Olas", justify="right", style="green")
    table.add_column("Slots (Free/Max)", justify="right", style="magenta")
    table.add_column("Available Rewards", justify="right", style="yellow")
    table.add_column("Contract Balance", justify="right", style="blue")
    table.add_column("Epoch End (UTC)", justify="right", style="white")

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
            slots_str = f"{free_slots}/{max_slots}"

            # 3. Rewards
            rewards_wei = contract.available_rewards
            rewards_olas = rewards_wei / 1e18

            # 4. Balance
            balance_wei = contract.balance
            balance_olas = balance_wei / 1e18

            # 5. Epoch End
            epoch_end = contract.get_next_epoch_start()
            epoch_end_str = epoch_end.strftime("%Y-%m-%d %H:%M:%S")

            table.add_row(
                name,
                f"{needed_olas:,.0f} OLAS",
                slots_str,
                f"{rewards_olas:,.2f} OLAS",
                f"{balance_olas:,.2f} OLAS",
                epoch_end_str,
            )

        except Exception as e:
            # Handle individual contract errors without crashing the whole list
            table.add_row(name, "ERROR", "-", "-", "-", str(e))

    console.print(table)


if __name__ == "__main__":
    main()
