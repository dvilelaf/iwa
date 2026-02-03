"""Olas Services Router."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from loguru import logger
from pydantic import BaseModel, Field

from iwa.core.models import Config
from iwa.plugins.olas.models import OlasConfig
from iwa.web.cache import CacheTTL, response_cache
from iwa.web.dependencies import verify_auth, wallet

router = APIRouter(tags=["olas"])


class CreateServiceRequest(BaseModel):
    """Request model for creating an Olas service."""

    service_name: str = Field(description="Human-readable name for the service")
    chain: str = Field(default="gnosis", description="Chain to create the service on")
    agent_type: str = Field(default="trader", description="Agent type (trader)")
    token_address: Optional[str] = Field(
        default="OLAS", description="Token address or name for bonding (OLAS for staking)"
    )
    stake_on_create: bool = Field(default=False, description="Whether to stake after creation")
    staking_contract: Optional[str] = Field(
        default=None, description="Staking contract address if staking"
    )


def _determine_bond_amount(req: CreateServiceRequest) -> int:
    """Determine the bond amount required for the service."""
    from web3 import Web3

    from iwa.core.contracts.erc20 import ERC20Contract
    from iwa.plugins.olas.contracts.staking import StakingContract
    from iwa.web.dependencies import wallet

    # Default to 1 wei of the service token if no staking contract specified
    bond_amount = Web3.to_wei(1, "wei")

    if req.token_address and req.staking_contract:
        # If a contract is specified, we MUST use its requirements
        staking_name = (
            wallet.account_service.get_tag_by_address(req.staking_contract) or req.staking_contract
        )
        logger.info(f"Fetching requirements from {staking_name}...")
        staking_contract = StakingContract(req.staking_contract, req.chain)
        reqs = staking_contract.get_requirements()
        bond_amount = reqs["required_agent_bond"]
        min_staking_deposit = reqs["min_staking_deposit"]
        logger.info(f"Required bond amount from contract: {bond_amount} wei")
        logger.info(f"Required min_staking_deposit: {min_staking_deposit} wei")

        # Validate upfront: total OLAS needed = bond + min_staking_deposit
        if req.stake_on_create:
            total_olas_needed = bond_amount + min_staking_deposit
            logger.info(
                f"Total OLAS needed for create + stake: {total_olas_needed / 1e18:.2f} OLAS"
            )

            # Check owner balance (master is default owner for new services)
            staking_token = reqs.get("staking_token")
            if staking_token:
                erc20 = ERC20Contract(staking_token, req.chain)
                owner_balance = erc20.balance_of_wei(wallet.master_account.address)
                logger.info(f"Owner OLAS balance: {owner_balance / 1e18:.2f} OLAS")

                if owner_balance < total_olas_needed:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Insufficient OLAS balance. Need {total_olas_needed / 1e18:.2f} OLAS "
                        f"(bond: {bond_amount / 1e18:.2f} + deposit: {min_staking_deposit / 1e18:.2f}), "
                        f"but owner has {owner_balance / 1e18:.2f} OLAS",
                    )
    return bond_amount


@router.post(
    "/create",
    summary="Create Service",
    description="Create a new Olas service on the specified chain and deploy it.",
)
def create_service(req: CreateServiceRequest, auth: bool = Depends(verify_auth)):
    """Create a new Olas service using spin_up for seamless deployment."""
    try:
        from iwa.plugins.olas.contracts.staking import StakingContract
        from iwa.plugins.olas.service_manager import ServiceManager

        manager = ServiceManager(wallet)

        # Determine bond amount
        bond_amount = _determine_bond_amount(req)

        # Step 1: Create the service (PRE_REGISTRATION state)
        logger.info(
            f"Calling manager.create with: chain={req.chain}, name={req.service_name}, "
            f"token={req.token_address}, bond={bond_amount}"
        )
        try:
            service_id = manager.create(
                chain_name=req.chain,
                service_name=req.service_name,
                token_address_or_tag=req.token_address,
                bond_amount_wei=bond_amount,
            )
        except Exception as create_error:
            logger.error(f"manager.create raised exception: {create_error}")
            raise HTTPException(
                status_code=400, detail=f"Service creation error: {create_error}"
            ) from None

        if not service_id:
            logger.error("manager.create returned None - check service_manager logs")
            raise HTTPException(
                status_code=400, detail="Failed to create service - see server logs"
            )

        logger.info(f"Service {service_id} created. Running spin_up...")

        # Step 2: Spin up the service (activate → register → deploy → optionally stake)
        # Only pass staking_contract if user wants to stake on create
        staking_obj = None
        if req.stake_on_create and req.staking_contract:
            # We need to instantiate the staking contract object for spin_up
            staking_obj = StakingContract(req.staking_contract, req.chain)

        success = manager.spin_up(
            service_id=service_id,
            staking_contract=staking_obj,
            bond_amount_wei=bond_amount,
        )

        if not success:
            raise HTTPException(
                status_code=400,
                detail="Service created but spin_up failed. Check logs for details.",
            )

        # Get final state
        final_state = manager.get_service_state()

        # Invalidate caches for services list
        response_cache.invalidate("service_state:")
        response_cache.invalidate("staking_status:")
        response_cache.invalidate("balances:")

        return {
            "status": "success",
            "service_id": service_id,
            "service_key": manager.service.key if manager.service else None,
            "multisig": str(manager.service.multisig_address) if manager.service else None,
            "final_state": final_state,
            "staked": req.stake_on_create and staking_obj is not None,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating service: {e}")
        raise HTTPException(status_code=400, detail=str(e)) from None


@router.post(
    "/deploy/{service_key}",
    summary="Deploy Service",
    description="Deploy an existing PRE_REGISTRATION service using spin_up.",
)
def deploy_service(
    service_key: str,
    staking_contract: Optional[str] = None,
    auth: bool = Depends(verify_auth),
):
    """Deploy an existing service (spin_up from PRE_REGISTRATION to DEPLOYED/STAKED)."""
    try:
        from iwa.plugins.olas.contracts.staking import StakingContract
        from iwa.plugins.olas.service_manager import ServiceManager

        config = Config()
        if "olas" not in config.plugins:
            raise HTTPException(status_code=404, detail="Olas plugin not configured")

        olas_config = OlasConfig.model_validate(config.plugins["olas"])
        service = olas_config.services.get(service_key)

        if not service:
            raise HTTPException(status_code=404, detail="Service not found")

        manager = ServiceManager(wallet)
        manager.service = service
        manager._init_contracts(service.chain_name)

        # Get current state
        current_state = manager.get_service_state()
        if current_state != "PRE_REGISTRATION":
            raise HTTPException(
                status_code=400,
                detail=f"Service is not in PRE_REGISTRATION state (current: {current_state})",
            )

        # Set up staking contract if provided
        staking_obj = None
        if staking_contract:
            try:
                staking_obj = StakingContract(staking_contract, service.chain_name)
                staking_name = (
                    wallet.account_service.get_tag_by_address(staking_contract) or staking_contract
                )
                logger.info(f"Will stake in {staking_name} after deployment")
            except Exception as e:
                logger.warning(f"Could not set up staking contract: {e}")

        logger.info(f"Running spin_up for service {service_key}...")

        # Use spin_up to deploy (and optionally stake)
        success = manager.spin_up(
            service_id=service.service_id,
            staking_contract=staking_obj,
        )

        if not success:
            raise HTTPException(
                status_code=400,
                detail="spin_up failed. Check server logs for details.",
            )

        final_state = manager.get_service_state()

        # Invalidate caches for this service
        response_cache.invalidate(f"service_state:{service_key}")
        response_cache.invalidate(f"staking_status:{service_key}")
        response_cache.invalidate(f"balances:{service_key}")

        return {
            "status": "success",
            "service_key": service_key,
            "final_state": final_state,
            "staked": staking_obj is not None,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deploying service: {e}")
        raise HTTPException(status_code=400, detail=str(e)) from None


def _resolve_service_accounts(service) -> dict:
    """Resolve basic accounts info including owner_signer if applicable."""
    accounts = {}
    for role, addr in [
        ("agent", service.agent_address),
        ("safe", str(service.multisig_address) if service.multisig_address else None),
        ("owner", service.service_owner_address),
    ]:
        if addr:
            stored = wallet.key_storage.find_stored_account(addr)
            # If this role is 'owner' and it's a Safe, add owner_signer role
            if role == "owner" and stored and hasattr(stored, "signers") and stored.signers:
                signer_addr = stored.signers[0]
                signer_stored = wallet.key_storage.find_stored_account(signer_addr)
                accounts["owner_signer"] = {
                    "address": signer_addr,
                    "tag": signer_stored.tag if signer_stored else None,
                    "native": None,
                    "olas": None,
                }

            accounts[role] = {
                "address": addr,
                "tag": stored.tag if stored else None,
                "native": None,
                "olas": None,
            }
    return accounts


def _resolve_service_balances(service, chain: str) -> dict:
    """Resolve detailed balances including owner_signer."""
    balances = {}
    for role, addr in [
        ("agent", service.agent_address),
        ("safe", str(service.multisig_address) if service.multisig_address else None),
        ("owner", service.service_owner_address),
    ]:
        if addr:
            native_bal = wallet.get_native_balance_eth(addr, chain)
            olas_bal = wallet.balance_service.get_erc20_balance_wei(addr, "OLAS", chain)
            olas_bal_eth = float(olas_bal) / 1e18 if olas_bal else 0
            stored = wallet.key_storage.find_stored_account(addr)

            # If this role is 'owner' and it's a Safe, resolve owner_signer
            if role == "owner" and stored and hasattr(stored, "signers") and stored.signers:
                signer_addr = stored.signers[0]
                s_native = wallet.get_native_balance_eth(signer_addr, chain)
                s_olas_wei = wallet.balance_service.get_erc20_balance_wei(
                    signer_addr, "OLAS", chain
                )
                s_olas = float(s_olas_wei) / 1e18 if s_olas_wei else 0
                s_stored = wallet.key_storage.find_stored_account(signer_addr)
                balances["owner_signer"] = {
                    "address": signer_addr,
                    "tag": s_stored.tag if s_stored else None,
                    "native": f"{s_native:.2f}" if s_native else "0.00",
                    "olas": f"{s_olas:.2f}",
                }

            balances[role] = {
                "address": addr,
                "tag": stored.tag if stored else None,
                "native": f"{native_bal:.2f}" if native_bal else "0.00",
                "olas": f"{olas_bal_eth:.2f}",
            }
    return balances


def _get_balances_cached(
    service_key: str, service, chain: str, force_refresh: bool = False
) -> dict:
    """Get service balances with caching to prevent excessive RPC calls."""
    cache_key = f"balances:{service_key}:{chain}"

    if force_refresh:
        response_cache.invalidate(cache_key)

    def fetch_balances():
        return _resolve_service_balances(service, chain)

    return response_cache.get_or_compute(
        cache_key, fetch_balances, CacheTTL.BALANCES
    )


def _staking_status_to_dict(status) -> Optional[dict]:
    """Convert StakingStatus dataclass to dict for JSON serialization."""
    if not status:
        return None
    return {
        "is_staked": status.is_staked,
        "staking_state": status.staking_state,
        "staking_contract_address": status.staking_contract_address,
        "staking_contract_name": status.staking_contract_name,
        "accrued_reward_olas": status.accrued_reward_olas,
        "accrued_reward_wei": status.accrued_reward_wei,
        "epoch_number": status.epoch_number,
        "epoch_end_utc": status.epoch_end_utc,
        "remaining_epoch_seconds": status.remaining_epoch_seconds,
        "mech_requests_this_epoch": status.mech_requests_this_epoch,
        "required_mech_requests": status.required_mech_requests,
        "has_enough_requests": status.has_enough_requests,
        "liveness_ratio_passed": status.liveness_ratio_passed,
        "unstake_available_at": status.unstake_available_at,
    }


@router.get(
    "/services/basic",
    summary="Get Basic Services",
    description="Get a lightweight list of configured Olas services.",
)
def get_olas_services_basic(
    chain: str = "gnosis",
    refresh: bool = False,
    auth: bool = Depends(verify_auth),
):
    """Get basic Olas service info from config.

    Args:
        chain: Chain name to filter services.
        refresh: If true, bypass cache and fetch fresh data.
        auth: Authentication dependency (injected).

    """
    if not chain.replace("-", "").isalnum():
        raise HTTPException(status_code=400, detail="Invalid chain name")

    try:
        from iwa.plugins.olas.service_manager import ServiceManager

        config = Config()
        if "olas" not in config.plugins:
            return []

        olas_config = OlasConfig.model_validate(config.plugins["olas"])

        result = []
        for service_key, service in olas_config.services.items():
            if service.chain_name != chain:
                continue

            # Get service state using ServiceManager's built-in caching
            try:
                manager = ServiceManager(wallet)
                manager.service = service
                manager._init_contracts(service.chain_name)
                state = manager.get_service_state(force_refresh=refresh)
            except Exception as e:
                logger.warning(f"Could not get state for {service_key}: {e}")
                state = "UNKNOWN"

            # Get tags from wallet storage (fast, local lookup)
            accounts = _resolve_service_accounts(service)

            result.append(
                {
                    "key": service_key,
                    "name": service.service_name,
                    "service_id": service.service_id,
                    "chain": service.chain_name,
                    "state": state,
                    "accounts": accounts,
                    "staking": {"is_staked": bool(service.staking_contract_address)}
                    if service.staking_contract_address
                    else None,
                }
            )

        return result

    except ImportError:
        return []
    except Exception as e:
        logger.error(f"Error getting basic Olas services: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from None


@router.get(
    "/services/{service_key}/details",
    summary="Get Service Details",
    description="Get detailed status, balances, and staking info for a specific Olas service.",
)
def get_olas_service_details(
    service_key: str,
    refresh: bool = False,
    auth: bool = Depends(verify_auth),
):
    """Get full details for a single Olas service (staking, balances).

    Args:
        service_key: The service key (chain:id format).
        refresh: If true, bypass cache and fetch fresh data.
        auth: Authentication dependency (injected).

    """
    try:
        from iwa.plugins.olas.service_manager import ServiceManager

        config = Config()
        if "olas" not in config.plugins:
            raise HTTPException(status_code=404, detail="Olas plugin not configured")

        olas_config = OlasConfig.model_validate(config.plugins["olas"])
        if service_key not in olas_config.services:
            raise HTTPException(
                status_code=404, detail=f"Service '{service_key}' not found"
            )

        service = olas_config.services[service_key]
        chain = service.chain_name

        # Use ServiceManager with built-in caching
        manager = ServiceManager(wallet)
        manager.service = service
        manager._init_contracts(service.chain_name)

        # Get data with force_refresh if requested
        service_state = manager.get_service_state(force_refresh=refresh)
        staking_status = manager.get_staking_status(force_refresh=refresh)
        balances = _get_balances_cached(service_key, service, chain, refresh)

        return {
            "key": service_key,
            "state": service_state,
            "accounts": balances,
            "staking": _staking_status_to_dict(staking_status),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting service details: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from None


@router.get(
    "/services",
    summary="Get All Services",
    description="Get comprehensive list of Olas services with full details.",
)
def get_olas_services(
    chain: str = "gnosis",
    refresh: bool = False,
    auth: bool = Depends(verify_auth),
):
    """Get all Olas services with staking status for a specific chain.

    Args:
        chain: Chain name to filter services.
        refresh: If true, bypass cache and fetch fresh data.
        auth: Authentication dependency (injected).

    """
    if not chain.replace("-", "").isalnum():
        raise HTTPException(status_code=400, detail="Invalid chain name")

    try:
        basic = get_olas_services_basic(chain, refresh, auth)
        result = []
        for svc in basic:
            try:
                details = get_olas_service_details(svc["key"], refresh, auth)
                # Merge details into basic info
                svc["staking"] = details["staking"]
                svc["accounts"] = details["accounts"]
                result.append(svc)
            except Exception as e:
                logger.error(f"Failed to get details for {svc['key']}: {e}")
                result.append(svc)  # Return basic info if details fail

        return result
    except Exception as e:
        logger.error(f"Error getting Olas services: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from None
