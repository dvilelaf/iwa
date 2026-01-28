"""Tool to drain specific accounts to a master address."""

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

# Ensure src is in pythonpath
sys.path.append(str(Path(__file__).resolve().parents[2]))

from loguru import logger

from iwa.core.constants import SECRETS_PATH
from iwa.core.wallet import Wallet


def main() -> None:
    """Run the account draining tool."""
    parser = argparse.ArgumentParser(description="Drain specific accounts to master.")
    parser.add_argument(
        "tags",
        nargs="+",
        help="List of account tags to drain (or 'all' for all configured accounts)",
    )
    parser.add_argument(
        "--chain",
        "-c",
        default="gnosis",
        help="Target chain (default: gnosis)",
    )
    args = parser.parse_args()

    # Load secrets
    if SECRETS_PATH.exists():
        load_dotenv(SECRETS_PATH, override=True)

    wallet = Wallet()

    tags = args.tags
    if "all" in tags:
        # Get all configured accounts except master
        all_accounts = wallet.account_service.get_account_data()
        tags = [acc.tag for acc in all_accounts.values() if acc.tag != "master"]
        logger.info(f"Draining ALL accounts: {tags}")

    for tag in tags:
        logger.info(f"Processing drain for account: {tag}")
        try:
            tx_hash = wallet.drain(from_address_or_tag=tag, chain_name=args.chain)
            if tx_hash:
                logger.success(f"Drain tx sent for {tag}: {tx_hash}")
                # Optional: link to explorer
            else:
                logger.warning(f"Drain failed or nothing to drain for {tag}")
        except Exception:
            logger.exception(f"Error draining {tag}")


if __name__ == "__main__":
    main()
