"""Olas Staking Router."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from loguru import logger
from slowapi import Limiter
from slowapi.util import get_remote_address

from iwa.core.models import Config
from iwa.plugins.olas.models import OlasConfig
from iwa.web.dependencies import get_config, verify_auth, wallet

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
        from iwa.core.chain import ChainInterfaces
        from iwa.plugins.olas.constants import OLAS_TRADER_STAKING_CONTRACTS

        contracts = OLAS_TRADER_STAKING_CONTRACTS.get(chain, {})

        # Get service bond and token if filtered
        service_bond, service_token = _get_service_filter_info(service_key)

        # Get correct interface from singleton manager
        interface = ChainInterfaces().get(chain)

        results = _fetch_all_contracts(contracts, interface)
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
    """Retrieve service bond and token if service_key is provided.

    Uses ServiceRegistryTokenUtilityContract.get_service_token_deposit() which returns
    the persistent bond value, even for terminated services. This is the correct source
    because bonds are stored separately from service state.
    """
    service_bond = None
    service_token = None

    if service_key:
        try:
            from iwa.core.contracts.cache import ContractCache
            from iwa.plugins.olas.constants import OLAS_CONTRACTS
            from iwa.plugins.olas.contracts.service import ServiceRegistryTokenUtilityContract
            from iwa.plugins.olas.service_manager import ServiceManager

            # Initialize wallet dependencies for ServiceManager
            manager = ServiceManager(wallet, service_key)
            if manager.service:
                service_id_int = manager.service.service_id
                chain_name = manager.service.chain_name

                # Get token and deposit from TokenUtility contract (persists after terminate)
                try:
                    protocol_contracts = OLAS_CONTRACTS.get(chain_name.lower(), {})
                    utility_address = protocol_contracts.get("OLAS_SERVICE_REGISTRY_TOKEN_UTILITY")

                    if utility_address:
                        token_utility = ContractCache().get_contract(
                            ServiceRegistryTokenUtilityContract,
                            address=str(utility_address),
                            chain_name=chain_name,
                        )
                        token_addr, security_deposit = token_utility.get_service_token_deposit(
                            service_id_int
                        )
                        service_bond = security_deposit
                        service_token = token_addr.lower() if token_addr else ""
                        logger.info(
                            f"Filtering for service {service_key}: security_deposit={service_bond}, token={service_token}"
                        )
                    else:
                        logger.warning(f"Token utility address not found for chain {chain_name}")
                        service_token = (manager.service.token_address or "").lower()
                except Exception as e:
                    logger.warning(f"Failed to get token deposit for filtering: {e}")
                    # Fallback to configured token_address
                    service_token = (manager.service.token_address or "").lower()

        except Exception as e:
            logger.warning(f"Could not fetch service details for filtering: {e}")
            # Don't fail the request, just skip filtering
            pass

    return service_bond, service_token


def _check_availability(name, address, interface):
    """Check availability of a single staking contract."""
    # Import at module level would cause circular import, but we can cache it
    # The import is cached by Python after first call so this is efficient
    from iwa.core.contracts.cache import ContractCache
    from iwa.plugins.olas.contracts.staking import StakingContract

    try:
        # Use ContractCache to benefit from shared instances and property caching
        contract = ContractCache().get_contract(
            StakingContract, address, chain_name=interface.chain.name
        )

        # StakingContract uses .call() which handles with_retry and rotation
        # Use properties instead of .call() to leverage caching
        service_ids = contract.call("getServiceIds")
        max_services = contract.max_num_services
        min_deposit = contract.min_staking_deposit
        staking_token = contract.staking_token_address
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


def _fetch_all_contracts(contracts: dict, interface) -> list:
    """Fetch availability for all contracts using threads.

    Note: Using limited parallelism (2 workers) to avoid overwhelming RPC
    endpoints with parallel requests that cause 429 rate limit errors.
    The RPC rotation mechanism is global but Contract objects are thread-local,
    so excessive parallelism leads to stale providers being used.
    """
    from concurrent.futures import ThreadPoolExecutor

    results = []
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(_check_availability, name, addr, interface)
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
