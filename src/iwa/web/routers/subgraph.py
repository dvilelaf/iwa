"""Subgraph Router — OLAS network data from on-chain subgraphs."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from loguru import logger

from iwa.plugins.olas.subgraph import SubgraphClient
from iwa.plugins.olas.subgraph.endpoints import SubgraphType, get_available_chains
from iwa.web.cache import response_cache
from iwa.web.dependencies import verify_auth

router = APIRouter(prefix="/api/subgraph", tags=["subgraph"])

# Lazy-initialized SubgraphClient (reads API key from secrets on first use)
_client: Optional[SubgraphClient] = None

# Subgraph data changes slowly — use 5 min cache
SUBGRAPH_TTL = 300


def _get_client() -> SubgraphClient:
    """Get or create the SubgraphClient singleton."""
    global _client
    if _client is None:
        _client = SubgraphClient()
    return _client


def _wei_to_olas(amount_wei: int) -> float:
    """Convert wei to OLAS (18 decimals)."""
    return amount_wei / 1e18


@router.get("/chains")
def get_chains(auth: bool = Depends(verify_auth)):
    """Get available chains for each subgraph type."""
    client = _get_client()
    api_key = client._api_key

    def _compute():
        return {
            "service_registry": get_available_chains(SubgraphType.SERVICE_REGISTRY, api_key),
            "staking": get_available_chains(SubgraphType.STAKING, api_key),
            "tokenomics": get_available_chains(SubgraphType.TOKENOMICS, api_key),
        }

    return response_cache.get_or_compute("subgraph:chains", _compute, SUBGRAPH_TTL)


@router.get("/overview")
def get_overview(chain: str = "gnosis", auth: bool = Depends(verify_auth)):
    """Get summary overview for a chain."""
    client = _get_client()
    cache_key = f"subgraph:overview:{chain}"

    cached = response_cache.get(cache_key, SUBGRAPH_TTL)
    if cached is not None:
        return cached

    try:
        services = client.registry.get_services(chain)
        services_count = len(services)
    except Exception as exc:
        logger.warning(f"Subgraph overview: registry error for {chain}: {exc}")
        services_count = 0

    # Staking stats
    staking_contracts_count = 0
    global_staking = None
    try:
        contracts = client.staking.get_all_contracts(chain)
        staking_contracts_count = len(contracts)
        stats = client.staking.get_global_stats(chain)
        if stats:
            global_staking = {
                "current_olas_staked": round(_wei_to_olas(stats.current_olas_staked), 2),
                "cumulative_olas_staked": round(_wei_to_olas(stats.cumulative_olas_staked), 2),
                "total_rewards": round(_wei_to_olas(stats.total_rewards), 2),
            }
    except Exception as exc:
        logger.warning(f"Subgraph overview: staking error for {chain}: {exc}")

    # Registry global stats
    global_registry = None
    try:
        reg_stats = client.registry.get_global_stats(chain)
        if reg_stats:
            global_registry = {
                "tx_count": reg_stats.tx_count,
                "total_operators": reg_stats.total_operators,
            }
    except Exception as exc:
        logger.warning(f"Subgraph overview: global stats error for {chain}: {exc}")

    # Protocol Registry global stats (Ethereum only)
    protocol_global = None
    try:
        proto_stats = client.protocol.get_global_stats()
        if proto_stats:
            protocol_global = {
                "total_builders": proto_stats.total_builders,
                "total_agents": proto_stats.total_agents,
                "total_components": proto_stats.total_components,
                "total_services": proto_stats.total_services,
            }
    except Exception as exc:
        logger.warning(f"Subgraph overview: protocol global error: {exc}")

    result = {
        "chain": chain,
        "services_count": services_count,
        "staking_contracts_count": staking_contracts_count,
        "global_staking": global_staking,
        "global_registry": global_registry,
        "protocol_global": protocol_global,
    }

    response_cache.set(cache_key, result)
    return result


@router.get("/services")
def get_services(
    chain: str = "gnosis",
    agent_id: Optional[int] = None,
    auth: bool = Depends(verify_auth),
):
    """Get all services on a chain, optionally filtered by agent ID."""
    client = _get_client()
    agent_suffix = f":agent{agent_id}" if agent_id else ""
    cache_key = f"subgraph:services:{chain}{agent_suffix}"

    cached = response_cache.get(cache_key, SUBGRAPH_TTL)
    if cached is not None:
        return cached

    try:
        services = client.registry.get_services(chain, agent_id=agent_id)
        result = {
            "chain": chain,
            "agent_id": agent_id,
            "count": len(services),
            "services": [
                {
                    "service_id": s.service_id,
                    "multisig": s.multisig,
                    "agent_ids": s.agent_ids,
                    "creator": s.creator,
                    "created": s.creation_timestamp.isoformat() if s.creation_timestamp else None,
                    "config_hash": s.config_hash,
                }
                for s in services
            ],
        }
        response_cache.set(cache_key, result)
        return result
    except Exception as exc:
        logger.error(f"Subgraph services error for {chain}: {exc}")
        raise HTTPException(status_code=500, detail=str(exc)) from None


@router.get("/staking")
def get_staking(
    chain: str = "gnosis",
    agent_id: Optional[int] = None,
    auth: bool = Depends(verify_auth),
):
    """Get staking contracts on a chain, optionally filtered by agent ID."""
    client = _get_client()
    agent_suffix = f":agent{agent_id}" if agent_id else ""
    cache_key = f"subgraph:staking:{chain}{agent_suffix}"

    cached = response_cache.get(cache_key, SUBGRAPH_TTL)
    if cached is not None:
        return cached

    try:
        contracts = client.staking.get_all_contracts(chain, agent_id=agent_id)
        result = {
            "chain": chain,
            "agent_id": agent_id,
            "count": len(contracts),
            "contracts": [
                {
                    "address": c.address,
                    "max_num_services": c.max_num_services,
                    "rewards_per_second": round(_wei_to_olas(c.rewards_per_second), 8),
                    "min_staking_deposit": round(_wei_to_olas(c.min_staking_deposit), 2),
                    "min_staking_duration": c.min_staking_duration,
                    "liveness_period": c.liveness_period,
                    "num_agent_instances": c.num_agent_instances,
                    "agent_ids": c.agent_ids,
                    "threshold": c.threshold,
                    "activity_checker": c.activity_checker,
                    "max_num_inactivity_periods": c.max_num_inactivity_periods,
                    "time_for_emissions": c.time_for_emissions,
                }
                for c in contracts
            ],
        }
        response_cache.set(cache_key, result)
        return result
    except ValueError:
        # Chain not supported for staking — return empty result
        return {"chain": chain, "agent_id": agent_id, "count": 0, "contracts": []}
    except Exception as exc:
        logger.error(f"Subgraph staking error for {chain}: {exc}")
        raise HTTPException(status_code=500, detail=str(exc)) from None


@router.get("/staking/checkpoints")
def get_staking_checkpoints(
    chain: str = "gnosis",
    limit: int = 100,
    auth: bool = Depends(verify_auth),
):
    """Get recent staking checkpoints."""
    client = _get_client()
    cache_key = f"subgraph:staking-checkpoints:{chain}"

    cached = response_cache.get(cache_key, SUBGRAPH_TTL)
    if cached is not None:
        return cached

    try:
        checkpoints = client.staking.get_checkpoints(chain, limit=limit)
        result = {
            "chain": chain,
            "count": len(checkpoints),
            "checkpoints": [
                {
                    "epoch": c.epoch,
                    "available_rewards": round(_wei_to_olas(c.available_rewards), 4),
                    "service_ids": c.service_ids,
                    "rewards": [round(_wei_to_olas(r), 4) for r in c.rewards],
                    "epoch_length": c.epoch_length,
                    "block_number": c.block_number,
                    "timestamp": c.block_timestamp.isoformat() if c.block_timestamp else None,
                    "transaction_hash": c.transaction_hash,
                    "contract_address": c.contract_address,
                }
                for c in checkpoints
            ],
        }
        response_cache.set(cache_key, result)
        return result
    except ValueError:
        return {"chain": chain, "count": 0, "checkpoints": []}
    except Exception as exc:
        logger.error(f"Subgraph checkpoints error for {chain}: {exc}")
        raise HTTPException(status_code=500, detail=str(exc)) from None


@router.get("/staking/events")
def get_staking_events(
    chain: str = "gnosis",
    limit: int = 100,
    auth: bool = Depends(verify_auth),
):
    """Get recent staking lifecycle events (unified)."""
    client = _get_client()
    cache_key = f"subgraph:staking-events:{chain}"

    cached = response_cache.get(cache_key, SUBGRAPH_TTL)
    if cached is not None:
        return cached

    try:
        events = client.staking.get_recent_events(chain, limit=limit)
        result = {
            "chain": chain,
            "count": len(events),
            "events": [
                {
                    "event_type": e.event_type,
                    "epoch": e.epoch,
                    "service_id": e.service_id,
                    "service_ids": e.service_ids if e.service_ids else None,
                    "owner": e.owner or None,
                    "multisig": e.multisig or None,
                    "amount": round(_wei_to_olas(e.amount), 4) if e.amount else None,
                    "timestamp": e.block_timestamp.isoformat() if e.block_timestamp else None,
                    "transaction_hash": e.transaction_hash,
                }
                for e in events
            ],
        }
        response_cache.set(cache_key, result)
        return result
    except ValueError:
        return {"chain": chain, "count": 0, "events": []}
    except Exception as exc:
        logger.error(f"Subgraph staking events error for {chain}: {exc}")
        raise HTTPException(status_code=500, detail=str(exc)) from None


@router.get("/staking/daily")
def get_staking_daily(
    chain: str = "gnosis",
    limit: int = 90,
    auth: bool = Depends(verify_auth),
):
    """Get daily staking trends."""
    client = _get_client()
    cache_key = f"subgraph:staking-daily:{chain}"

    cached = response_cache.get(cache_key, SUBGRAPH_TTL)
    if cached is not None:
        return cached

    try:
        trends = client.staking.get_daily_trends(chain, limit=limit)
        result = {
            "chain": chain,
            "count": len(trends),
            "trends": [
                {
                    "date": t.timestamp.isoformat() if t.timestamp else None,
                    "num_services": t.num_services,
                    "total_rewards": round(_wei_to_olas(t.total_rewards), 2),
                    "median_cumulative_rewards": round(_wei_to_olas(t.median_cumulative_rewards), 2),
                }
                for t in trends
            ],
        }
        response_cache.set(cache_key, result)
        return result
    except ValueError:
        return {"chain": chain, "count": 0, "trends": []}
    except Exception as exc:
        logger.error(f"Subgraph daily trends error for {chain}: {exc}")
        raise HTTPException(status_code=500, detail=str(exc)) from None


@router.get("/agents")
def get_agents(auth: bool = Depends(verify_auth)):
    """Get all agents from Protocol Registry with full details."""
    client = _get_client()
    cache_key = "subgraph:agents:full:v2"

    cached = response_cache.get(cache_key, SUBGRAPH_TTL)
    if cached is not None:
        return cached

    try:
        agents = client.protocol.get_agents()
        agent_names = {str(a.token_id): a.public_id for a in agents}
        result = {
            "agents": agent_names,
            "count": len(agents),
            "units": [
                {
                    "token_id": a.token_id,
                    "public_id": a.public_id,
                    "description": a.description,
                    "owner": a.owner,
                    "package_hash": a.package_hash,
                    "image": a.image,
                    "metadata_hash": a.metadata_hash,
                    "block": a.block,
                    "tx_hash": a.tx_hash,
                }
                for a in agents
            ],
        }
        response_cache.set(cache_key, result)
        return result
    except Exception as exc:
        logger.warning(f"Subgraph agents error: {exc}")
        return {"agents": {}, "count": 0, "units": []}


@router.get("/components")
def get_components(auth: bool = Depends(verify_auth)):
    """Get all components from Protocol Registry."""
    client = _get_client()
    cache_key = "subgraph:components:v2"

    cached = response_cache.get(cache_key, SUBGRAPH_TTL)
    if cached is not None:
        return cached

    try:
        components = client.protocol.get_components()
        result = {
            "count": len(components),
            "units": [
                {
                    "token_id": c.token_id,
                    "public_id": c.public_id,
                    "package_type": c.package_type,
                    "description": c.description,
                    "owner": c.owner,
                    "package_hash": c.package_hash,
                    "image": c.image,
                    "metadata_hash": c.metadata_hash,
                    "block": c.block,
                    "tx_hash": c.tx_hash,
                }
                for c in components
            ],
        }
        response_cache.set(cache_key, result)
        return result
    except Exception as exc:
        logger.error(f"Subgraph components error: {exc}")
        raise HTTPException(status_code=500, detail=str(exc)) from None


@router.get("/builders")
def get_builders(auth: bool = Depends(verify_auth)):
    """Get all builder addresses from Protocol Registry."""
    client = _get_client()
    cache_key = "subgraph:builders"

    cached = response_cache.get(cache_key, SUBGRAPH_TTL)
    if cached is not None:
        return cached

    try:
        builders = client.protocol.get_builders()
        result = {
            "count": len(builders),
            "builders": builders,
        }
        response_cache.set(cache_key, result)
        return result
    except Exception as exc:
        logger.error(f"Subgraph builders error: {exc}")
        raise HTTPException(status_code=500, detail=str(exc)) from None


@router.get("/protocol")
def get_protocol(auth: bool = Depends(verify_auth)):
    """Get Protocol Registry data (Ethereum only)."""
    client = _get_client()
    cache_key = "subgraph:protocol:v2"

    cached = response_cache.get(cache_key, SUBGRAPH_TTL)
    if cached is not None:
        return cached

    try:
        global_stats = client.protocol.get_global_stats()
        services = client.protocol.get_services()

        result = {
            "global_stats": {
                "total_builders": global_stats.total_builders,
                "total_agents": global_stats.total_agents,
                "total_components": global_stats.total_components,
                "total_services": global_stats.total_services,
            } if global_stats else None,
            "count": len(services),
            "services": [
                {
                    "service_id": s.service_id,
                    "public_id": s.public_id,
                    "state": s.state,
                    "agent_ids": s.agent_ids,
                    "threshold": s.threshold,
                    "security_deposit": round(_wei_to_olas(s.security_deposit), 2),
                    "number_of_instances": s.number_of_instances,
                    "max_number_of_instances": s.max_number_of_instances,
                    "owner": s.owner,
                }
                for s in services
            ],
        }
        response_cache.set(cache_key, result)
        return result
    except Exception as exc:
        logger.error(f"Subgraph protocol error: {exc}")
        raise HTTPException(status_code=500, detail=str(exc)) from None


@router.get("/tokenomics")
def get_tokenomics(
    chain: str = "gnosis",
    auth: bool = Depends(verify_auth),
):
    """Get tokenomics data: token info, top holders, recent transfers."""
    client = _get_client()
    cache_key = f"subgraph:tokenomics:{chain}"

    cached = response_cache.get(cache_key, SUBGRAPH_TTL)
    if cached is not None:
        return cached

    try:
        data = client.tokenomics.get_all_data(chain)
        token_info = data["token_info"]
        result = {
            "chain": chain,
            "token_info": {
                "balance": round(_wei_to_olas(token_info.balance), 2),
                "holder_count": token_info.holder_count,
            } if token_info else None,
            "top_holders": [
                {
                    "address": h.address,
                    "balance": round(_wei_to_olas(h.balance), 2),
                }
                for h in data["top_holders"]
            ],
            "recent_transfers": [
                {
                    "from": t.from_address,
                    "to": t.to_address,
                    "value": round(_wei_to_olas(t.value), 4),
                    "block_number": t.block_number,
                    "timestamp": t.block_timestamp.isoformat() if t.block_timestamp else None,
                    "transaction_hash": t.transaction_hash,
                }
                for t in data["recent_transfers"]
            ],
        }
        response_cache.set(cache_key, result)
        return result
    except ValueError:
        return {"chain": chain, "token_info": None, "top_holders": [], "recent_transfers": []}
    except Exception as exc:
        logger.error(f"Subgraph tokenomics error for {chain}: {exc}")
        raise HTTPException(status_code=500, detail=str(exc)) from None
