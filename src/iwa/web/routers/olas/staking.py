"""Olas Staking Router."""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from iwa.core.models import Config
from iwa.plugins.olas.models import OlasConfig
from iwa.web.dependencies import get_config, verify_auth, wallet

logger = logging.getLogger(__name__)
router = APIRouter(tags=["olas"])
limiter = Limiter(key_func=get_remote_address)


@router.get(
    "/staking-contracts",
    summary="Get Staking Contracts",
    description="Get the list of available OLAS staking contracts for a specific chain.",
)
def get_staking_contracts(
    chain: str = "gnosis",
    service_key: Optional[str] = None,
    auth: bool = Depends(verify_auth),  # noqa: B008
    config: Config = Depends(get_config),  # noqa: B008
):
    """Get available staking contracts for a chain, optionally filtered by service bond."""
    if not chain.replace("-", "").isalnum():
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail="Invalid chain name")

    try:
        import json

        from iwa.core.chain import ChainInterface
        from iwa.plugins.olas.constants import OLAS_TRADER_STAKING_CONTRACTS
        from iwa.plugins.olas.contracts.base import OLAS_ABI_PATH

        contracts = OLAS_TRADER_STAKING_CONTRACTS.get(chain, {})

        # Get service bond and token if filtered
        service_bond, service_token = _get_service_filter_info(service_key)

        # Load ABI once
        with open(OLAS_ABI_PATH / "staking.json", "r") as f:
            abi = json.load(f)

        # Get correct web3 instance
        w3 = ChainInterface(chain).web3

        results = _fetch_all_contracts(contracts, w3, abi)
        filtered_results = _filter_contracts(results, service_bond, service_token)

        # Return with filter metadata so frontend can explain filtering
        return {
            "contracts": filtered_results,
            "filter_info": {
                "service_bond": service_bond,
                "service_bond_olas": service_bond / 10**18 if service_bond else None,
                "total_contracts": len(results),
                "filtered_count": len(filtered_results),
                "is_filtered": service_key is not None,
            },
        }

    except Exception as e:
        import traceback

        traceback.print_exc()
        logger.error(f"Error fetching staking contracts: {e}")
        return []


def _get_service_filter_info(service_key: Optional[str]) -> tuple[Optional[int], Optional[str]]:
    """Retrieve service bond and token if service_key is provided."""
    service_bond = None
    service_token = None

    if service_key:
        try:
            from iwa.plugins.olas.service_manager import ServiceManager

            # Initialize wallet dependencies for ServiceManager
            manager = ServiceManager(wallet, service_key)
            if manager.service:
                # Get service requirements
                service_token = (manager.service.token_address or "").lower()
                service_id_int = manager.service.service_id

                # Get security deposit from registry - this is the actual bond value
                try:
                    service_info = manager.registry.get_service(service_id_int)
                    service_bond = service_info.get("security_deposit", 0)
                    logger.info(
                        f"Filtering for service {service_key}: security_deposit={service_bond}, token={service_token}"
                    )
                except Exception as e:
                    logger.warning(f"Failed to get service info for filtering: {e}")

        except Exception as e:
            logger.warning(f"Could not fetch service details for filtering: {e}")
            # Don't fail the request, just skip filtering
            pass

    return service_bond, service_token


def _check_availability(name, address, w3, abi):
    """Check availability of a single staking contract."""
    try:
        contract = w3.eth.contract(address=address, abi=abi)
        service_ids = contract.functions.getServiceIds().call()
        max_services = contract.functions.maxNumServices().call()
        min_deposit = contract.functions.minStakingDeposit().call()
        staking_token = contract.functions.stakingToken().call()
        used = len(service_ids)

        return {
            "name": name,
            "address": address,
            "usage": {
                "used": used,
                "max": max_services,
                "available_slots": max_services - used,
                "available": used < max_services,
            },
            "min_staking_deposit": min_deposit,
            "staking_token": staking_token,
        }
    except Exception as e:
        logger.warning(f"Failed to check availability for {name} ({address}): {e}")
        return {
            "name": name,
            "address": address,
            "usage": None,  # Could not verify
            "min_staking_deposit": None,
        }


def _fetch_all_contracts(contracts: dict, w3, abi) -> list:
    """Fetch availability for all contracts using threads."""
    from concurrent.futures import ThreadPoolExecutor

    results = []
    with ThreadPoolExecutor(max_workers=10) as executor:
        # Pass w3 and abi to the helper
        futures = [
            executor.submit(_check_availability, name, addr, w3, abi)
            for name, addr in contracts.items()
        ]
        for future in futures:
            results.append(future.result())
    return results


def _filter_contracts(
    results: list, service_bond: Optional[int], service_token: Optional[str]
) -> list:
    """Filter contracts based on usage and service compatibility."""
    filtered_results = []
    for r in results:
        # 1. Availability check
        if r["usage"] is not None and not r["usage"]["available"]:
            continue

        # 2. Compatibility check (if service info is known)
        if service_bond is not None and r.get("min_staking_deposit") is not None:
            # Bond Check
            if service_bond < r["min_staking_deposit"]:
                # Incompatible: Service bond is too low for this contract
                continue

            # Token Check
            contract_token = str(r.get("staking_token", "")).lower()
            if service_token and contract_token and service_token != contract_token:
                # Incompatible: Tokens do not match
                continue

        filtered_results.append(r)
    return filtered_results


@router.post(
    "/stake/{service_key}",
    summary="Stake Service",
    description="Stake a service into a staking contract.",
)
@limiter.limit("5/minute")
def stake_service(
    request: Request,
    service_key: str,
    staking_contract: str,
    auth: bool = Depends(verify_auth),
):
    """Stake a service into a staking contract."""
    try:
        from iwa.plugins.olas.contracts.staking import StakingContract
        from iwa.plugins.olas.service_manager import ServiceManager

        config = Config()
        olas_config = OlasConfig.model_validate(config.plugins["olas"])
        service = olas_config.services.get(service_key)

        if not service:
            raise HTTPException(status_code=404, detail="Service not found")

        manager = ServiceManager(wallet)
        manager.service = service

        # Ensure staking_contract is a valid address format
        if not staking_contract.startswith("0x"):
            raise HTTPException(
                status_code=400, detail=f"Invalid staking contract address: {staking_contract}"
            )

        staking = StakingContract(staking_contract, service.chain_name)
        success = manager.stake(staking)

        if success:
            return {"status": "success"}
        else:
            raise HTTPException(status_code=400, detail="Failed to stake service")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error staking service: {e}")
        raise HTTPException(status_code=400, detail=str(e)) from None


@router.post(
    "/claim/{service_key}",
    summary="Claim Rewards",
    description="Claim accrued staking rewards for a specific service.",
)
def claim_rewards(service_key: str, auth: bool = Depends(verify_auth)):
    """Claim accrued staking rewards for a service."""
    try:
        from iwa.plugins.olas.service_manager import ServiceManager

        config = Config()
        olas_config = OlasConfig.model_validate(config.plugins["olas"])
        service = olas_config.services.get(service_key)

        if not service:
            raise HTTPException(status_code=404, detail="Service not found")

        manager = ServiceManager(wallet)
        manager.service = service

        success, amount = manager.claim_rewards()
        if success:
            return {"status": "success", "amount": amount}
        else:
            raise HTTPException(status_code=400, detail="Failed to claim rewards")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error claiming rewards: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from None


@router.post(
    "/unstake/{service_key}",
    summary="Unstake Service",
    description="Unstake a service from the registry.",
)
def unstake_service(service_key: str, auth: bool = Depends(verify_auth)):
    """Unstake a service."""
    try:
        from iwa.plugins.olas.contracts.staking import StakingContract
        from iwa.plugins.olas.service_manager import ServiceManager

        config = Config()
        olas_config = OlasConfig.model_validate(config.plugins["olas"])
        service = olas_config.services.get(service_key)

        if not service or not service.staking_contract_address:
            raise HTTPException(status_code=404, detail="Service not found or not staked")

        manager = ServiceManager(wallet)
        manager.service = service

        # We need the staking contract instance
        staking_contract = StakingContract(service.staking_contract_address, service.chain_name)

        success = manager.unstake(staking_contract)
        if success:
            return {"status": "success"}
        else:
            raise HTTPException(status_code=400, detail="Failed to unstake")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error unstaking: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from None


@router.post(
    "/checkpoint/{service_key}",
    summary="Checkpoint Service",
    description="Trigger a checkpoint for a staked service to update its liveness.",
)
def checkpoint_service(service_key: str, auth: bool = Depends(verify_auth)):
    """Checkpoint a service."""
    try:
        from iwa.plugins.olas.contracts.staking import StakingContract
        from iwa.plugins.olas.service_manager import ServiceManager

        config = Config()
        olas_config = OlasConfig.model_validate(config.plugins["olas"])
        service = olas_config.services.get(service_key)

        if not service or not service.staking_contract_address:
            raise HTTPException(status_code=404, detail="Service not found or not staked")

        manager = ServiceManager(wallet)
        manager.service = service

        staking_contract = StakingContract(service.staking_contract_address, service.chain_name)

        success = manager.call_checkpoint(staking_contract)
        if success:
            return {"status": "success"}
        else:
            # Check if it was just not needed
            if not staking_contract.is_checkpoint_needed():
                return {"status": "skipped", "message": "Checkpoint not needed yet"}
            raise HTTPException(status_code=400, detail="Failed to checkpoint")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error checkpointing: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from None
