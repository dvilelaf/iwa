"""Olas Router for Web API."""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from iwa.core.models import Config
from iwa.plugins.olas.models import OlasConfig
from iwa.web.dependencies import get_config, verify_auth, wallet

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/olas", tags=["olas"])


@router.get(
    "/price",
    summary="Get OLAS Price",
    description="Get the current price of OLAS token in EUR from CoinGecko.",
)
def get_olas_price(auth: bool = Depends(verify_auth)):
    """Get current OLAS token price in EUR from CoinGecko."""
    try:
        from iwa.core.pricing import PriceService

        price_service = PriceService()
        price = price_service.get_token_price("autonolas", "eur")

        return {"price_eur": price, "symbol": "OLAS"}
    except Exception as e:
        logger.error(f"Error fetching OLAS price: {e}")
        return {"price_eur": None, "symbol": "OLAS", "error": str(e)}


@router.get(
    "/staking-contracts",
    summary="Get Staking Contracts",
    description="Get the list of available OLAS staking contracts for a specific chain.",
)
def get_staking_contracts(
    chain: str = "gnosis",
    service_key: Optional[str] = None,
    auth: bool = Depends(verify_auth),
    config: Config = Depends(get_config),
):
    """Get available staking contracts for a chain, optionally filtered by service bond."""
    if not chain.replace("-", "").isalnum():
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail="Invalid chain name")

    try:
        import json
        from concurrent.futures import ThreadPoolExecutor

        from iwa.core.chain import ChainInterface
        from iwa.plugins.olas.constants import OLAS_TRADER_STAKING_CONTRACTS
        from iwa.plugins.olas.contracts.base import OLAS_ABI_PATH
        from iwa.plugins.olas.service_manager import ServiceManager

        contracts = OLAS_TRADER_STAKING_CONTRACTS.get(chain, {})
        print(f"DEBUG: Staking Contracts for {chain}: {contracts}")

        # Get service bond and token if filtered
        service_bond = None
        service_token = None

        if service_key:
            try:
                # Need to use ServiceManager to get accurate info including security deposit
                chain_name, service_id = service_key.split(":")
                # Initialize wallet dependencies for ServiceManager
                from iwa.core.constants import ZERO_ADDRESS
                manager = ServiceManager(wallet, service_key)
                if manager.service:
                    # Get service requirements
                    service_token = (manager.service.token_address or "").lower()
                    service_id_int = manager.service.service_id


                    # Get Agent Bond (checking first agent)
                    # We need the bond the agent actually has, to compare with what the contract REQUIRES
                    agent_ids = manager.service.agent_ids
                    if not agent_ids:
                         # Fallback to registry lookup if local model doesn't have agent details
                         try:
                             service_info = manager.registry.get_service_info(service_id_int)
                             agent_ids = service_info.get("agent_ids", [])
                         except Exception as registry_error:
                             logger.warning(f"Failed to fetch service info from registry: {registry_error}")
                             agent_ids = []

                    if agent_ids:
                        first_agent_id = agent_ids[0]
                        agent_params = manager.registry.get_agent_params(service_id_int, first_agent_id)
                        service_bond = agent_params.get("bond")
                        logger.info(f"Filtering for service {service_key}: bond={service_bond}, token={service_token}")

            except Exception as e:
                logger.warning(f"Could not fetch service details for filtering: {e}")
                # Don't fail the request, just skip filtering
                pass

        # Load ABI once
        with open(OLAS_ABI_PATH / "staking.json", "r") as f:
            abi = json.load(f)

        # Get correct web3 instance
        w3 = ChainInterface(chain).web3
        print(f"DEBUG: Web3 Instance: {w3}")

        def check_availability(name, address):
            try:
                contract = w3.eth.contract(address=address, abi=abi)
                service_ids = contract.functions.getServiceIds().call()
                max_services = contract.functions.maxNumServices().call()
                min_deposit = contract.functions.minStakingDeposit().call()
                staking_token = contract.functions.stakingToken().call()
                used = len(service_ids)

                print(f"DEBUG: {name}: {used}/{max_services} (min: {min_deposit}, token: {staking_token})")

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
                print(f"DEBUG: Failed for {name}: {e}")
                logger.warning(f"Failed to check availability for {name} ({address}): {e}")
                # Don't need full traceback here, just the error
                # import traceback
                # traceback.print_exc()
                # Return basic info with assumed availability (or not)
                return {
                    "name": name,
                    "address": address,
                    "usage": None,  # Could not verify
                    "min_staking_deposit": None,
                }

        results = []
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [
                executor.submit(check_availability, name, addr) for name, addr in contracts.items()
            ]
            for future in futures:
                results.append(future.result())

        print(f"DEBUG: Final Results: {results}")

        # Filter valid contracts (fetched info) OR unverified (RPC failed)
        # But exclude contracts KNOWN to be full (usage exists AND available <= 0)
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

    except Exception as e:
        print(f"DEBUG: Top Level Error: {e}")
        import traceback

        traceback.print_exc()
        logger.error(f"Error fetching staking contracts: {e}")
        return []


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


@router.post(
    "/create",
    summary="Create Service",
    description="Create a new Olas service on the specified chain and deploy it.",
)
def create_service(req: CreateServiceRequest, auth: bool = Depends(verify_auth)):
    """Create a new Olas service using spin_up for seamless deployment."""
    try:
        from web3 import Web3

        from iwa.plugins.olas.contracts.staking import StakingContract
        from iwa.plugins.olas.service_manager import ServiceManager

        manager = ServiceManager(wallet)

        # Determine bond amount based on staking contract
        bond_amount = 1  # Default for native token (1 wei)

        staking_contract = None
        if req.token_address:
            if req.staking_contract:
                # If a contract is specified, we MUST use its requirements
                logger.info(f"Fetching requirements from {req.staking_contract}...")
                staking_contract = StakingContract(req.staking_contract, req.chain)
                reqs = staking_contract.get_requirements()
                bond_amount = reqs["required_agent_bond"]
                logger.info(f"Required bond amount from contract: {bond_amount} wei")
            else:
                # Default to 1 wei of the service token if no staking contract specified
                bond_amount = Web3.to_wei(1, "wei")

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
        spin_up_staking = staking_contract if req.stake_on_create else None

        success = manager.spin_up(
            service_id=service_id,
            staking_contract=spin_up_staking,
            bond_amount_wei=bond_amount,
        )

        if not success:
            raise HTTPException(
                status_code=400,
                detail="Service created but spin_up failed. Check logs for details.",
            )

        # Get final state
        final_state = manager.get_service_state()

        return {
            "status": "success",
            "service_id": service_id,
            "service_key": manager.service.key if manager.service else None,
            "multisig": str(manager.service.multisig_address) if manager.service else None,
            "final_state": final_state,
            "staked": req.stake_on_create and spin_up_staking is not None,
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
                logger.info(f"Will stake in {staking_contract} after deployment")
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


@router.post(
    "/activate/{service_key}",
    summary="Activate Registration",
    description="Activate registration for a service (step 1 after creation).",
)
def activate_registration(service_key: str, auth: bool = Depends(verify_auth)):
    """Activate service registration."""
    try:
        from iwa.plugins.olas.service_manager import ServiceManager

        config = Config()
        olas_config = OlasConfig.model_validate(config.plugins["olas"])
        service = olas_config.services.get(service_key)

        if not service:
            raise HTTPException(status_code=404, detail="Service not found")

        manager = ServiceManager(wallet)
        manager.service = service

        success = manager.activate_registration()
        if success:
            return {"status": "success"}
        else:
            raise HTTPException(status_code=400, detail="Failed to activate registration")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error activating registration: {e}")
        raise HTTPException(status_code=400, detail=str(e)) from None


@router.post(
    "/register/{service_key}",
    summary="Register Agent",
    description="Register an agent for the service (step 2 after activation).",
)
def register_agent(service_key: str, auth: bool = Depends(verify_auth)):
    """Register agent for service."""
    try:
        from iwa.plugins.olas.service_manager import ServiceManager

        config = Config()
        olas_config = OlasConfig.model_validate(config.plugins["olas"])
        service = olas_config.services.get(service_key)

        if not service:
            raise HTTPException(status_code=404, detail="Service not found")

        manager = ServiceManager(wallet)
        manager.service = service

        success = manager.register_agent()
        if success:
            return {"status": "success"}
        else:
            raise HTTPException(status_code=400, detail="Failed to register agent")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error registering agent: {e}")
        raise HTTPException(status_code=400, detail=str(e)) from None


@router.post(
    "/deploy-step/{service_key}",
    summary="Deploy Service (Step 3)",
    description="Deploy the service (step 3, creates multisig Safe).",
)
def deploy_service_step(service_key: str, auth: bool = Depends(verify_auth)):
    """Deploy the service."""
    try:
        from iwa.plugins.olas.service_manager import ServiceManager

        config = Config()
        olas_config = OlasConfig.model_validate(config.plugins["olas"])
        service = olas_config.services.get(service_key)

        if not service:
            raise HTTPException(status_code=404, detail="Service not found")

        manager = ServiceManager(wallet)
        manager.service = service

        success = manager.deploy()
        if success:
            return {"status": "success"}
        else:
            raise HTTPException(status_code=400, detail="Failed to deploy service")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deploying service: {e}")
        raise HTTPException(status_code=400, detail=str(e)) from None


@router.get(
    "/services/basic",
    summary="Get Basic Services",
    description="Get a lightweight list of configured Olas services without RPC calls.",
)
def get_olas_services_basic(chain: str = "gnosis", auth: bool = Depends(verify_auth)):
    """Get basic Olas service info from config (fast, no RPC calls)."""
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

            # Get service state from registry
            state = "UNKNOWN"
            try:
                manager = ServiceManager(wallet)
                manager.service = service
                state = manager.get_service_state()
            except Exception as e:
                logger.warning(f"Could not get state for {service_key}: {e}")

            # Get tags from wallet storage (fast, local lookup)
            accounts = {}
            for role, addr in [
                ("agent", service.agent_address),
                ("safe", str(service.multisig_address) if service.multisig_address else None),
                ("owner", service.service_owner_address),
            ]:
                if addr:
                    stored = wallet.key_storage.find_stored_account(addr)
                    accounts[role] = {
                        "address": addr,
                        "tag": stored.tag if stored else None,
                        "native": None,  # Will be filled by details endpoint
                        "olas": None,
                    }

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
def get_olas_service_details(service_key: str, auth: bool = Depends(verify_auth)):
    """Get full details for a single Olas service (staking, balances)."""
    try:
        from iwa.plugins.olas.service_manager import ServiceManager

        config = Config()
        if "olas" not in config.plugins:
            raise HTTPException(status_code=404, detail="Olas plugin not configured")

        olas_config = OlasConfig.model_validate(config.plugins["olas"])
        if service_key not in olas_config.services:
            raise HTTPException(status_code=404, detail=f"Service '{service_key}' not found")

        service = olas_config.services[service_key]
        chain = service.chain_name

        manager = ServiceManager(wallet)
        manager.service = service
        staking_status = manager.get_staking_status()
        service_state = manager.get_service_state()

        # Get balances
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
                balances[role] = {
                    "address": addr,
                    "tag": stored.tag if stored else None,
                    "native": f"{native_bal:.2f}" if native_bal else "0.00",
                    "olas": f"{olas_bal_eth:.2f}",
                }

        staking = None
        if staking_status:
            staking = {
                "is_staked": staking_status.is_staked,
                "staking_state": staking_status.staking_state,
                "staking_contract_address": staking_status.staking_contract_address,
                "staking_contract_name": staking_status.staking_contract_name,
                "accrued_reward_olas": staking_status.accrued_reward_olas,
                "accrued_reward_wei": staking_status.accrued_reward_wei,
                "epoch_number": staking_status.epoch_number,
                "epoch_end_utc": staking_status.epoch_end_utc,
                "remaining_epoch_seconds": staking_status.remaining_epoch_seconds,
                "mech_requests_this_epoch": staking_status.mech_requests_this_epoch,
                "required_mech_requests": staking_status.required_mech_requests,
                "has_enough_requests": staking_status.has_enough_requests,
                "liveness_ratio_passed": staking_status.liveness_ratio_passed,
                "unstake_available_at": staking_status.unstake_available_at,
            }

        return {
            "key": service_key,
            "state": service_state,
            "accounts": balances,
            "staking": staking,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting service details: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from None


@router.get(
    "/services",
    summary="Get All Services",
    description="Get comprehensive list of Olas services with full details (slower than basic).",
)
def get_olas_services(chain: str = "gnosis", auth: bool = Depends(verify_auth)):
    """Get all Olas services with staking status for a specific chain."""
    if not chain.replace("-", "").isalnum():
        raise HTTPException(status_code=400, detail="Invalid chain name")

    try:
        # Re-using detail logic iteratively (inefficient but safe for now)
        # Ideally we refactor this to be more efficient bulk query later
        basic = get_olas_services_basic(chain, auth)
        result = []
        for svc in basic:
            try:
                details = get_olas_service_details(svc["key"], auth)
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


@router.post(
    "/stake/{service_key}",
    summary="Stake Service",
    description="Stake a service into a staking contract.",
)
def stake_service(
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
    "/terminate/{service_key}",
    summary="Terminate Service",
    description="Wind down a service: unstake (if staked) → terminate → unbond.",
)
def terminate_service(service_key: str, auth: bool = Depends(verify_auth)):
    """Terminate and unbond a service using wind_down."""
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

        # Get current state for logging
        current_state = manager.get_service_state()
        logger.info(f"[WIND_DOWN] Service {service_key} state: {current_state}")

        if current_state == "PRE_REGISTRATION":
            return {"status": "success", "message": "Service already in PRE_REGISTRATION state"}

        if current_state == "NON_EXISTENT":
            raise HTTPException(status_code=400, detail="Service does not exist")

        # Prepare staking contract if service is staked
        staking_contract = None
        if service.staking_contract_address:
            staking_contract = StakingContract(service.staking_contract_address, service.chain_name)

        # Use wind_down which handles unstake → terminate → unbond
        success = manager.wind_down(staking_contract=staking_contract)

        if success:
            return {"status": "success", "message": "Service wound down to PRE_REGISTRATION"}
        else:
            raise HTTPException(
                status_code=400,
                detail="Wind down failed. Check logs for details.",
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error winding down service: {e}")
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


class FundRequest(BaseModel):
    """Request model for funding a service."""

    agent_amount_eth: float = Field(default=0, description="Amount to fund agent in ETH")
    safe_amount_eth: float = Field(default=0, description="Amount to fund safe in ETH")


@router.post(
    "/fund/{service_key}",
    summary="Fund Service",
    description="Fund a service's agent and safe accounts with native currency.",
)
def fund_service(service_key: str, req: FundRequest, auth: bool = Depends(verify_auth)):
    """Fund a service's agent and safe accounts."""
    try:
        from web3 import Web3

        config = Config()
        olas_config = OlasConfig.model_validate(config.plugins["olas"])
        service = olas_config.services.get(service_key)

        if not service:
            raise HTTPException(status_code=404, detail="Service not found")

        funded = {}

        # Fund agent if amount provided and agent exists
        if req.agent_amount_eth > 0 and service.agent_address:
            amount_wei = Web3.to_wei(req.agent_amount_eth, "ether")
            tx_hash = wallet.send(
                from_address_or_tag="master",
                to_address_or_tag=service.agent_address,
                amount_wei=amount_wei,
                token_address_or_name="native",
                chain_name=service.chain_name,
            )
            funded["agent"] = {"amount": req.agent_amount_eth, "tx_hash": tx_hash}

        # Fund safe if amount provided and safe exists
        if req.safe_amount_eth > 0 and service.multisig_address:
            amount_wei = Web3.to_wei(req.safe_amount_eth, "ether")
            tx_hash = wallet.send(
                from_address_or_tag="master",
                to_address_or_tag=str(service.multisig_address),
                amount_wei=amount_wei,
                token_address_or_name="native",
                chain_name=service.chain_name,
            )
            funded["safe"] = {"amount": req.safe_amount_eth, "tx_hash": tx_hash}

        if not funded:
            raise HTTPException(
                status_code=400, detail="No valid accounts to fund or amounts are zero"
            )

        return {"status": "success", "funded": funded}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error funding service: {e}")
        raise HTTPException(status_code=400, detail=str(e)) from None


@router.post(
    "/drain/{service_key}",
    summary="Drain Service",
    description="Drain all funds from a service's accounts to the master account.",
)
def drain_service(service_key: str, auth: bool = Depends(verify_auth)):
    """Drain all funds from a service's accounts."""
    try:
        from iwa.plugins.olas.service_manager import ServiceManager

        config = Config()
        olas_config = OlasConfig.model_validate(config.plugins["olas"])
        service = olas_config.services.get(service_key)

        if not service:
            raise HTTPException(status_code=404, detail="Service not found")

        manager = ServiceManager(wallet)
        manager.service = service

        logger.info(f"[DRAIN] Starting drain for service {service_key}")
        logger.info(f"[DRAIN] Agent: {service.agent_address}")
        logger.info(f"[DRAIN] Safe: {service.multisig_address}")
        logger.info(f"[DRAIN] Owner: {service.service_owner_address}")

        # Drain all accounts (Safe, Agent, Owner)
        try:
            drained = manager.drain_service()
            logger.info(f"[DRAIN] drain_service returned: {drained}")
        except Exception as drain_ex:
            logger.error(f"[DRAIN] drain_service threw exception: {drain_ex}")
            import traceback

            logger.error(f"[DRAIN] Traceback: {traceback.format_exc()}")
            raise HTTPException(status_code=400, detail=str(drain_ex)) from drain_ex

        if not drained:
            raise HTTPException(
                status_code=400,
                detail="Nothing drained. Accounts may have no balance or private keys may be missing.",
            )

        return {
            "status": "success",
            "drained": drained,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error draining service: {e}")
        raise HTTPException(status_code=400, detail=str(e)) from None
