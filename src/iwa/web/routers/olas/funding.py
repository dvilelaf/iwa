"""Olas Funding Router."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from slowapi import Limiter
from slowapi.util import get_remote_address

from iwa.core.models import Config
from iwa.plugins.olas.models import OlasConfig
from iwa.web.dependencies import verify_auth, wallet

logger = logging.getLogger(__name__)
router = APIRouter(tags=["olas"])
limiter = Limiter(key_func=get_remote_address)


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
@limiter.limit("3/minute")
def drain_service(request: Request, service_key: str, auth: bool = Depends(verify_auth)):
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
