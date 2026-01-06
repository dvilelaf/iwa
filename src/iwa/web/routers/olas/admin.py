"""Olas Admin Router."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from iwa.core.models import Config
from iwa.plugins.olas.models import OlasConfig
from iwa.web.dependencies import verify_auth, wallet

logger = logging.getLogger(__name__)
router = APIRouter(tags=["olas"])
limiter = Limiter(key_func=get_remote_address)


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


@router.post(
    "/terminate/{service_key}",
    summary="Terminate Service",
    description="Wind down a service: unstake (if staked) → terminate → unbond.",
)
@limiter.limit("3/minute")
def terminate_service(request: Request, service_key: str, auth: bool = Depends(verify_auth)):
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
