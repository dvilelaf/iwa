"""Recreates Tenderly networks and funds wallets as per configuration."""

import argparse
import json
import os
import random
import re
import string
import sys
from typing import List, Optional, Tuple

import requests
from web3 import Web3

from iwa.core.constants import SECRETS_PATH, get_tenderly_config_path
from iwa.core.keys import KeyStorage
from iwa.core.models import TenderlyConfig
from iwa.core.settings import settings


def get_tenderly_credentials() -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Get Tenderly credentials from settings (based on current profile)."""
    return (
        settings.tenderly_account_slug.get_secret_value()
        if settings.tenderly_account_slug
        else None,
        settings.tenderly_project_slug.get_secret_value()
        if settings.tenderly_project_slug
        else None,
        settings.tenderly_access_key.get_secret_value() if settings.tenderly_access_key else None,
    )


def _generate_default_config() -> TenderlyConfig:
    """Generate a default TenderlyConfig from SupportedChains."""
    from iwa.core.chain import SupportedChains
    from iwa.core.models import FundRequirements, TokenAmount, VirtualNet

    vnets = {}
    chains = SupportedChains()

    for chain_name, chain in [
        ("gnosis", chains.gnosis),
        ("ethereum", chains.ethereum),
        ("base", chains.base),
    ]:
        # Get OLAS token address for this chain
        olas_address = chain.tokens.get("OLAS")

        tokens = []
        if olas_address:
            tokens.append(
                TokenAmount(
                    address=str(olas_address),
                    symbol="OLAS",
                    amount_eth=settings.tenderly_olas_funds,
                )
            )

        vnets[chain_name] = VirtualNet(
            chain_id=chain.chain_id,
            funds_requirements={
                "all": FundRequirements(
                    native_eth=settings.tenderly_native_funds,
                    tokens=tokens,
                )
            },
        )

    return TenderlyConfig(vnets=vnets)


def _delete_vnet(
    tenderly_access_key: str, account_slug: str, project_slug: str, vnet_id: str
) -> None:
    url = f"https://api.tenderly.co/api/v1/account/{account_slug}/project/{project_slug}/vnets/{vnet_id}"
    requests.delete(
        url=url,
        timeout=300,
        headers={"Accept": "application/json", "X-Access-Key": tenderly_access_key},
    )
    print(f"Deleted vnet {vnet_id}")


def _create_vnet(
    tenderly_access_key: str,
    account_slug: str,
    project_slug: str,
    network_id: int,
    chain_id: int,
    vnet_slug: str,
    vnet_display_name: str,
    block_number: Optional[str] = "latest",
) -> Tuple[str | None, str | None, str | None]:
    # Define the payload for the fork creation
    payload = {
        "slug": vnet_slug,
        "display_name": vnet_display_name,
        "fork_config": {"network_id": network_id, "block_number": str(block_number)},
        "virtual_network_config": {"chain_config": {"chain_id": chain_id}},
        "sync_state_config": {"enabled": False},
        "explorer_page_config": {
            "enabled": False,
            "verification_visibility": "bytecode",
        },
    }

    url = f"https://api.tenderly.co/api/v1/account/{account_slug}/project/{project_slug}/vnets"
    response = requests.post(
        url=url,
        timeout=300,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-Access-Key": tenderly_access_key,
        },
        data=json.dumps(payload),
    )

    json_response = response.json()
    vnet_id = json_response.get("id")
    admin_rpc = next(
        (rpc["url"] for rpc in json_response.get("rpcs", []) if rpc["name"] == "Admin RPC"),
        None,
    )
    public_rpc = next(
        (rpc["url"] for rpc in json_response.get("rpcs", []) if rpc["name"] == "Public RPC"),
        None,
    )
    print(f"Created vnet of chain_id={network_id} at block number {block_number}")
    return vnet_id, admin_rpc, public_rpc


def _generate_vnet_slug(preffix: str = "vnet", length: int = 4):
    characters = string.ascii_lowercase
    return (
        preffix + "-" + "".join(random.choice(characters) for _ in range(length))  # nosec
    )


def update_rpc_variables(tenderly_config: TenderlyConfig) -> None:
    """Updates several files"""
    with open(SECRETS_PATH, "r", encoding="utf-8") as file:
        content = file.read()

    for chain_name, vnet in tenderly_config.vnets.items():
        pattern = rf"{chain_name.lower()}_test_rpc=(\S+)"

        if re.search(pattern, content, re.MULTILINE):
            content = re.sub(
                pattern,
                f"{chain_name.lower()}_test_rpc={vnet.public_rpc}",
                content,
                flags=re.MULTILINE,
            )
        else:
            if content and not content.endswith("\n"):
                content += "\n"
            content += f"{chain_name.lower()}_test_rpc={vnet.public_rpc}\n"

    with open(SECRETS_PATH, "w", encoding="utf-8") as file:
        file.write(content)

    print("Updated RPCs in secrets.env")


def _fund_wallet(  # nosec
    admin_rpc: str,
    wallet_addresses: List[str],
    amount_eth: float,
    native_or_token_address: str = "native",
) -> None:
    if native_or_token_address == "native":  # nosec
        json_data = {
            "jsonrpc": "2.0",
            "method": "tenderly_setBalance",
            "params": [
                wallet_addresses,
                hex(Web3.to_wei(amount_eth, "ether")),  # to wei
            ],
            "id": "1234",
        }
    else:
        json_data = {
            "jsonrpc": "2.0",
            "method": "tenderly_setErc20Balance",
            "params": [
                native_or_token_address,
                wallet_addresses,
                hex(Web3.to_wei(amount_eth, "ether")),  # to wei
            ],
            "id": "1234",
        }

    response = requests.post(
        url=admin_rpc,
        timeout=300,
        headers={"Content-Type": "application/json"},
        json=json_data,
    )
    if response.status_code != 200:
        print(response.status_code)
        try:
            print(response.json())
        except requests.exceptions.JSONDecodeError:  # type: ignore
            pass


def _process_vnet(
    vnet_name: str,
    vnet,
    tenderly_access_key: str,
    account_slug: str,
    project_slug: str,
    tenderly_config,
) -> bool:
    """Process a single vnet: delete old, create new, capture block."""
    # Delete existing vnet
    if vnet.vnet_id:
        _delete_vnet(
            tenderly_access_key=tenderly_access_key,
            account_slug=account_slug,
            project_slug=project_slug,
            vnet_id=vnet.vnet_id,
        )

    # Create new network
    vnet_slug = _generate_vnet_slug(preffix=vnet_name.lower())
    vnet_id, admin_rpc, public_rpc = _create_vnet(
        tenderly_access_key=tenderly_access_key,
        account_slug=account_slug,
        project_slug=project_slug,
        network_id=vnet.chain_id,
        chain_id=vnet.chain_id,
        vnet_slug=vnet_slug,
        vnet_display_name=vnet_slug,
    )

    if not vnet_id or not admin_rpc or not public_rpc:
        print(f"Failed to create valid vnet for {vnet_name}")
        return False

    vnet.vnet_id = vnet_id
    vnet.admin_rpc = admin_rpc
    vnet.public_rpc = public_rpc
    vnet.vnet_slug = vnet_slug

    # Capture initial block
    try:
        w3 = Web3(Web3.HTTPProvider(public_rpc))
        start_block = w3.eth.block_number
        vnet.initial_block = start_block
        print(f"Captured initial block for {vnet_name}: {start_block}")
    except Exception as e:
        print(f"Failed to capture initial block: {e}")
        vnet.initial_block = 0

    tenderly_config.save()
    update_rpc_variables(tenderly_config)
    return True


def _fund_vnet_accounts(vnet, keys) -> None:
    """Fund all accounts for a vnet based on requirements."""
    for account_tags, requirement in vnet.funds_requirements.items():
        tags = account_tags.split(",")
        if account_tags != "all":
            addresses = []
            for tag in tags:
                if acc := keys.get_account(tag):
                    addresses.append(acc.address)
        else:
            addresses = list(keys.accounts.keys())

        if not addresses:
            continue

        if requirement.native_eth > 0:
            _fund_wallet(
                admin_rpc=vnet.admin_rpc,
                wallet_addresses=addresses,
                amount_eth=requirement.native_eth,
                native_or_token_address="native",
            )
            print(f"Funded {tags} with {requirement.native_eth} native")

        for token in requirement.tokens:
            _fund_wallet(
                admin_rpc=vnet.admin_rpc,
                wallet_addresses=addresses,
                amount_eth=token.amount_eth,
                native_or_token_address=str(token.address),
            )
            print(f"Funded {tags} with {token.amount_eth} {token.symbol}")


def main() -> None:
    """Main - uses tenderly_profile from settings."""
    profile = settings.tenderly_profile
    print(f"Recreating Tenderly Networks (Profile {profile})")

    account_slug, project_slug, tenderly_access_key = get_tenderly_credentials()

    if not account_slug or not project_slug or not tenderly_access_key:
        print(f"Missing Tenderly environment variables for profile {profile}")
        return

    config_path = get_tenderly_config_path(profile)

    if not config_path.exists():
        print(f"Generating new config file: {config_path}")
        tenderly_config = _generate_default_config()
        tenderly_config.save(config_path)

    tenderly_config = TenderlyConfig.load(config_path)

    for vnet_name, vnet in tenderly_config.vnets.items():
        if not _process_vnet(
            vnet_name, vnet, tenderly_access_key, account_slug, project_slug, tenderly_config
        ):
            continue

        # Fund wallets
        keys = KeyStorage()
        from iwa.core.services import AccountService, SafeService

        account_service = AccountService(keys)
        safe_service = SafeService(keys, account_service)

        _fund_vnet_accounts(vnet, keys)

        # Redeploy safes for Gnosis
        if vnet_name == "Gnosis":
            safe_service.redeploy_safes()


if __name__ == "__main__":  # pragma: no cover
    parser = argparse.ArgumentParser(description="Reset Tenderly networks")
    parser.add_argument(
        "--profile",
        "-p",
        type=int,
        default=1,
        choices=[1, 2, 3],
        help="Tenderly profile to use (1 or 2)",
    )
    args = parser.parse_args()

    # Set profile env var
    os.environ["TENDERLY_PROFILE"] = str(args.profile)

    # Reset the singleton to reload with new env
    from iwa.core.settings import Settings

    Settings._instance = None  # type: ignore

    # Reimport settings to get fresh instance
    if "iwa.core.settings" in sys.modules:
        del sys.modules["iwa.core.settings"]
    from iwa.core.settings import settings  # noqa: F401

    main()
