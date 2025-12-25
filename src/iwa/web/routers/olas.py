"""Olas Router for Web API."""

import logging

from fastapi import APIRouter, Depends, HTTPException

from iwa.core.models import Config
from iwa.plugins.olas.models import OlasConfig
from iwa.web.dependencies import verify_auth, wallet

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
def get_staking_contracts(chain: str = "gnosis", auth: bool = Depends(verify_auth)):
    """Get available staking contracts for a chain."""
    if not chain.replace("-", "").isalnum():
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail="Invalid chain name")

    try:
        from iwa.plugins.olas.constants import OLAS_TRADER_STAKING_CONTRACTS

        contracts = OLAS_TRADER_STAKING_CONTRACTS.get(chain, {})
        return [{"name": name, "address": addr} for name, addr in contracts.items()]
    except Exception as e:
        logger.error(f"Error fetching staking contracts: {e}")
        return []


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
        config = Config()
        if "olas" not in config.plugins:
            return []

        olas_config = OlasConfig.model_validate(config.plugins["olas"])

        result = []
        for service_key, service in olas_config.services.items():
            if service.chain_name != chain:
                continue

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
        staking_contract = StakingContract.from_address(
            service.staking_contract_address, service.chain_name
        )

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

        staking_contract = StakingContract.from_address(
            service.staking_contract_address, service.chain_name
        )

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
