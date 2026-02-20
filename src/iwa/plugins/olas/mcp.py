"""MCP tool definitions for Olas plugin."""

from typing import Optional

from fastmcp import FastMCP
from loguru import logger


def register_olas_tools(mcp: FastMCP) -> None:
    """Register all Olas tools on the MCP server."""
    _register_service_query_tools(mcp)
    _register_service_write_tools(mcp)
    _register_admin_tools(mcp)
    _register_staking_query_tools(mcp)
    _register_staking_action_tools(mcp)
    _register_staking_reward_tools(mcp)
    _register_funding_tools(mcp)
    _register_info_tools(mcp)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_service(service_key: str):
    """Load a Service object from config by key.

    Returns:
        (service, olas_config) tuple.

    Raises:
        ValueError: if service not found.

    """
    from iwa.core.models import Config
    from iwa.plugins.olas.models import OlasConfig

    config = Config()
    if "olas" not in config.plugins:
        raise ValueError("Olas plugin not configured")

    olas_config = OlasConfig.model_validate(config.plugins["olas"])
    service = olas_config.services.get(service_key)
    if not service:
        raise ValueError(f"Service '{service_key}' not found")
    return service, olas_config


def _make_manager(service_key: str):
    """Create a ServiceManager initialized for the given service_key."""
    from iwa.core.wallet import Wallet
    from iwa.plugins.olas.service_manager import ServiceManager

    wallet = Wallet()
    return ServiceManager(wallet, service_key=service_key)


def _make_manager_for_service(service):
    """Create a ServiceManager and attach an already-loaded service."""
    from iwa.core.wallet import Wallet
    from iwa.plugins.olas.service_manager import ServiceManager

    wallet = Wallet()
    manager = ServiceManager(wallet)
    manager.service = service
    manager._init_contracts(service.chain_name)
    return manager


# ---------------------------------------------------------------------------
# Service query tools (2)
# ---------------------------------------------------------------------------


def _register_service_query_tools(mcp: FastMCP) -> None:
    @mcp.tool
    def olas_list_services(chain: str = "gnosis") -> dict:
        """List all configured Olas services with basic info.

        Args:
            chain: Blockchain name to filter services.

        Returns:
            Dictionary with services list and chain name.

        """
        from iwa.core.models import Config
        from iwa.plugins.olas.models import OlasConfig

        config = Config()
        if "olas" not in config.plugins:
            return {"services": [], "chain": chain}

        olas_config = OlasConfig.model_validate(config.plugins["olas"])
        services = []
        for service_key, svc in olas_config.services.items():
            if svc.chain_name != chain:
                continue
            services.append(
                {
                    "service_key": service_key,
                    "name": svc.service_name,
                    "service_id": svc.service_id,
                    "chain": svc.chain_name,
                }
            )
        return {"services": services, "chain": chain}

    @mcp.tool
    def olas_service_details(service_key: str) -> dict:
        """Get detailed status, balances, and staking info for an Olas service.

        Args:
            service_key: Service key in 'chain:id' format (e.g. 'gnosis:42').

        Returns:
            Dictionary with state, staking status, and account balances.

        """
        try:
            manager = _make_manager(service_key)
            state = manager.get_service_state()
            staking = manager.get_staking_status()

            staking_dict = None
            if staking:
                staking_dict = {
                    "is_staked": staking.is_staked,
                    "staking_state": staking.staking_state,
                    "staking_contract_name": staking.staking_contract_name,
                    "accrued_reward_olas": staking.accrued_reward_olas,
                    "epoch_end_utc": staking.epoch_end_utc,
                    "mech_requests_this_epoch": staking.mech_requests_this_epoch,
                    "required_mech_requests": staking.required_mech_requests,
                    "has_enough_requests": staking.has_enough_requests,
                }

            return {
                "service_key": service_key,
                "state": state,
                "staking": staking_dict,
            }
        except Exception as e:
            return {"error": str(e)}


# ---------------------------------------------------------------------------
# Service write tools (2)
# ---------------------------------------------------------------------------


def _register_service_write_tools(mcp: FastMCP) -> None:
    @mcp.tool
    def olas_create_service(
        service_name: str,
        chain: str = "gnosis",
        token_address: str = "OLAS",
        stake_on_create: bool = False,
        staking_contract: Optional[str] = None,
    ) -> dict:
        """Create a new Olas service and deploy it (activate, register, deploy).

        Args:
            service_name: Human-readable name for the service.
            chain: Blockchain name (e.g. 'gnosis').
            token_address: Token address or name for bonding (default 'OLAS').
            stake_on_create: Whether to stake after creation.
            staking_contract: Staking contract address (required if staking).

        Returns:
            Dictionary with service_id, service_key, and final state.

        """
        from iwa.core.wallet import Wallet
        from iwa.plugins.olas.service_manager import ServiceManager

        wallet = Wallet()
        manager = ServiceManager(wallet)

        # Determine bond amount
        bond_amount = 1  # 1 wei default
        if token_address and staking_contract:
            from iwa.plugins.olas.contracts.staking import StakingContract

            sc = StakingContract(staking_contract, chain)
            reqs = sc.get_requirements()
            bond_amount = reqs["required_agent_bond"]

        service_id = manager.create(
            chain_name=chain,
            service_name=service_name,
            token_address_or_tag=token_address,
            bond_amount_wei=bond_amount,
        )
        if not service_id:
            return {"error": "Failed to create service"}

        # Spin up: activate → register → deploy (→ optionally stake)
        staking_obj = None
        if stake_on_create and staking_contract:
            from iwa.plugins.olas.contracts.staking import StakingContract

            staking_obj = StakingContract(staking_contract, chain)

        success = manager.spin_up(
            service_id=service_id,
            staking_contract=staking_obj,
            bond_amount_wei=bond_amount,
        )

        return {
            "status": "success" if success else "partial",
            "service_id": service_id,
            "service_key": manager.service.key if manager.service else None,
            "staked": stake_on_create and staking_obj is not None and success,
        }

    @mcp.tool
    def olas_deploy_service(
        service_key: str,
        staking_contract: Optional[str] = None,
    ) -> dict:
        """Deploy an existing PRE_REGISTRATION service (spin_up).

        Args:
            service_key: Service key in 'chain:id' format.
            staking_contract: Optional staking contract address to stake after deploy.

        Returns:
            Dictionary with final state and staking status.

        """
        service, _ = _load_service(service_key)
        manager = _make_manager_for_service(service)

        staking_obj = None
        if staking_contract:
            from iwa.plugins.olas.contracts.staking import StakingContract

            staking_obj = StakingContract(staking_contract, service.chain_name)

        success = manager.spin_up(
            service_id=service.service_id,
            staking_contract=staking_obj,
        )

        final_state = manager.get_service_state() if success else "UNKNOWN"
        return {
            "status": "success" if success else "failed",
            "service_key": service_key,
            "final_state": final_state,
            "staked": staking_obj is not None and success,
        }


# ---------------------------------------------------------------------------
# Admin / Lifecycle tools (4)
# ---------------------------------------------------------------------------


def _register_admin_tools(mcp: FastMCP) -> None:  # noqa: C901
    @mcp.tool
    def olas_activate_service(service_key: str) -> dict:
        """Activate registration for a service (step 1 after creation).

        Args:
            service_key: Service key in 'chain:id' format.

        Returns:
            Dictionary with operation status.

        """
        service, _ = _load_service(service_key)
        manager = _make_manager_for_service(service)
        success = manager.activate_registration()
        return {"status": "success" if success else "failed"}

    @mcp.tool
    def olas_register_agent(service_key: str) -> dict:
        """Register an agent for the service (step 2 after activation).

        Args:
            service_key: Service key in 'chain:id' format.

        Returns:
            Dictionary with operation status.

        """
        service, _ = _load_service(service_key)
        manager = _make_manager_for_service(service)
        success = manager.register_agent()
        return {"status": "success" if success else "failed"}

    @mcp.tool
    def olas_deploy_step(service_key: str) -> dict:
        """Deploy the service multisig Safe (step 3, creates Safe).

        Args:
            service_key: Service key in 'chain:id' format.

        Returns:
            Dictionary with operation status.

        """
        service, _ = _load_service(service_key)
        manager = _make_manager_for_service(service)
        success = manager.deploy()
        return {"status": "success" if success else "failed"}

    @mcp.tool
    def olas_terminate_service(service_key: str) -> dict:
        """Wind down a service: unstake (if staked) → terminate → unbond.

        Args:
            service_key: Service key in 'chain:id' format.

        Returns:
            Dictionary with operation status and message.

        """
        service, _ = _load_service(service_key)
        manager = _make_manager_for_service(service)

        current_state = manager.get_service_state()
        if current_state == "PRE_REGISTRATION":
            return {"status": "success", "message": "Already in PRE_REGISTRATION"}
        if current_state == "NON_EXISTENT":
            return {"error": "Service does not exist on-chain"}

        staking_contract = None
        if service.staking_contract_address:
            from iwa.plugins.olas.contracts.staking import StakingContract

            staking_contract = StakingContract(
                service.staking_contract_address, service.chain_name
            )

        success = manager.wind_down(staking_contract=staking_contract)
        if success:
            return {"status": "success", "message": "Wound down to PRE_REGISTRATION"}

        # Diagnose failure: check if stuck due to staking epoch lock
        if staking_contract and service.staking_contract_address:
            try:
                from datetime import datetime, timezone

                from iwa.plugins.olas.contracts.staking import StakingState

                staking_state = staking_contract.get_staking_state(service.service_id)
                if staking_state == StakingState.STAKED:
                    svc_info = staking_contract.get_service_info(service.service_id)
                    ts_start = svc_info.get("ts_start", 0)
                    if ts_start > 0:
                        unlock_ts = ts_start + staking_contract.min_staking_duration
                        now_ts = datetime.now(timezone.utc).timestamp()
                        if now_ts < unlock_ts:
                            diff = int(unlock_ts - now_ts)
                            h, m = diff // 3600, (diff % 3600) // 60
                            return {
                                "status": "failed",
                                "message": (
                                    "Cannot terminate: service is staked and minimum"
                                    f" staking duration not met."
                                    f" Unlocks in {diff}s ({h}h {m}m)."
                                ),
                            }
            except Exception:
                pass

        return {"status": "failed", "message": "Wind down failed"}


# ---------------------------------------------------------------------------
# Staking query tools (1)
# ---------------------------------------------------------------------------


def _register_staking_query_tools(mcp: FastMCP) -> None:
    @mcp.tool
    def olas_list_staking_contracts(
        chain: str = "gnosis",
    ) -> dict:
        """List available OLAS staking contracts for a chain.

        Args:
            chain: Blockchain name (e.g. 'gnosis').

        Returns:
            Dictionary with list of staking contracts.

        """
        from iwa.plugins.olas.constants import OLAS_TRADER_STAKING_CONTRACTS

        contracts = OLAS_TRADER_STAKING_CONTRACTS.get(chain, {})
        result = [
            {"name": name, "address": str(addr)} for name, addr in contracts.items()
        ]
        return {"contracts": result, "chain": chain}


# ---------------------------------------------------------------------------
# Staking action tools (5)
# ---------------------------------------------------------------------------


def _register_staking_action_tools(mcp: FastMCP) -> None:  # noqa: C901
    @mcp.tool
    def olas_stake_service(service_key: str, staking_contract: str) -> dict:
        """Stake a service into a staking contract.

        Args:
            service_key: Service key in 'chain:id' format.
            staking_contract: Address of the staking contract.

        Returns:
            Dictionary with operation status.

        """
        from iwa.plugins.olas.contracts.staking import StakingContract

        service, _ = _load_service(service_key)
        manager = _make_manager_for_service(service)
        sc = StakingContract(staking_contract, service.chain_name)
        success = manager.stake(sc)
        return {"status": "success" if success else "failed"}

    @mcp.tool
    def olas_unstake_service(service_key: str) -> dict:
        """Unstake a service from its staking contract.

        Args:
            service_key: Service key in 'chain:id' format.

        Returns:
            Dictionary with operation status.

        """
        from datetime import datetime, timezone

        from iwa.plugins.olas.contracts.staking import StakingContract, StakingState

        service, _ = _load_service(service_key)
        if not service.staking_contract_address:
            return {"error": "Service is not staked"}

        manager = _make_manager_for_service(service)
        sc = StakingContract(service.staking_contract_address, service.chain_name)

        # Surface epoch lock reason before attempting unstake
        try:
            staking_state = sc.get_staking_state(service.service_id)
            if staking_state == StakingState.STAKED:
                svc_info = sc.get_service_info(service.service_id)
                ts_start = svc_info.get("ts_start", 0)
                if ts_start > 0:
                    unlock_ts = ts_start + sc.min_staking_duration
                    now_ts = datetime.now(timezone.utc).timestamp()
                    if now_ts < unlock_ts:
                        diff = int(unlock_ts - now_ts)
                        h, m = diff // 3600, (diff % 3600) // 60
                        return {
                            "status": "failed",
                            "reason": (
                                f"Minimum staking duration not met."
                                f" Unlocks in {diff}s ({h}h {m}m)."
                            ),
                        }
        except Exception:
            pass  # Let unstake() handle unexpected errors

        success = manager.unstake(sc)
        return {"status": "success" if success else "failed"}

    @mcp.tool
    def olas_restake_service(service_key: str) -> dict:
        """Restake an evicted service: unstake + stake on the same contract.

        Args:
            service_key: Service key in 'chain:id' format.

        Returns:
            Dictionary with operation status and staking contract used.

        """
        from iwa.plugins.olas.contracts.staking import StakingContract, StakingState

        service, _ = _load_service(service_key)
        if not service.staking_contract_address:
            return {"error": "Service has no staking contract"}

        contract_address = str(service.staking_contract_address)
        manager = _make_manager_for_service(service)
        sc = StakingContract(contract_address, service.chain_name)

        # Verify evicted state
        staking_state = sc.get_staking_state(service.service_id)
        if staking_state != StakingState.EVICTED:
            return {
                "error": f"Service is {staking_state.name}, not EVICTED. Use unstake/stake separately."
            }

        if not manager.unstake(sc):
            return {"error": "Failed to unstake evicted service"}

        if not manager.stake(sc):
            return {"error": "Unstake succeeded but stake failed"}

        return {"status": "success", "staking_contract": contract_address}



# ---------------------------------------------------------------------------
# Staking reward tools (2)
# ---------------------------------------------------------------------------


def _register_staking_reward_tools(mcp: FastMCP) -> None:
    @mcp.tool
    def olas_claim_rewards(service_key: str) -> dict:
        """Claim accrued staking rewards for a service.

        Args:
            service_key: Service key in 'chain:id' format.

        Returns:
            Dictionary with claim status and amount.

        """
        service, _ = _load_service(service_key)
        manager = _make_manager_for_service(service)
        success, amount = manager.claim_rewards()
        if not success and amount == 0:
            status = "nothing_to_claim"
        else:
            status = "claimed" if success else "failed"
        return {
            "status": status,
            "amount_olas": amount,
        }

    @mcp.tool
    def olas_checkpoint(service_key: str) -> dict:
        """Trigger a checkpoint for a staked service to update its liveness.

        Args:
            service_key: Service key in 'chain:id' format.

        Returns:
            Dictionary with operation status.

        """
        from iwa.plugins.olas.contracts.staking import StakingContract

        service, _ = _load_service(service_key)
        if not service.staking_contract_address:
            return {"error": "Service is not staked"}

        manager = _make_manager_for_service(service)
        sc = StakingContract(service.staking_contract_address, service.chain_name)
        success = manager.call_checkpoint(sc)

        if success:
            return {"status": "success"}

        if not sc.is_checkpoint_needed():
            return {"status": "skipped", "message": "Checkpoint not needed yet"}

        return {"status": "failed"}


# ---------------------------------------------------------------------------
# Funding tools (2)
# ---------------------------------------------------------------------------


def _register_funding_tools(mcp: FastMCP) -> None:
    @mcp.tool
    def olas_fund_service(
        service_key: str,
        agent_amount_eth: float = 0,
        safe_amount_eth: float = 0,
    ) -> dict:
        """Fund a service's agent and/or safe accounts with native currency.

        Args:
            service_key: Service key in 'chain:id' format.
            agent_amount_eth: Amount to send to the agent in ETH.
            safe_amount_eth: Amount to send to the safe in ETH.

        Returns:
            Dictionary with funded accounts and transaction hashes.

        """
        from web3 import Web3

        from iwa.core.wallet import Wallet

        service, _ = _load_service(service_key)
        wallet = Wallet()
        funded = {}

        if agent_amount_eth > 0 and service.agent_address:
            amount_wei = Web3.to_wei(agent_amount_eth, "ether")
            tx_hash = wallet.send(
                from_address_or_tag="master",
                to_address_or_tag=service.agent_address,
                amount_wei=amount_wei,
                token_address_or_name="native",
                chain_name=service.chain_name,
            )
            funded["agent"] = {"amount": agent_amount_eth, "tx_hash": tx_hash}

        if safe_amount_eth > 0 and service.multisig_address:
            amount_wei = Web3.to_wei(safe_amount_eth, "ether")
            tx_hash = wallet.send(
                from_address_or_tag="master",
                to_address_or_tag=str(service.multisig_address),
                amount_wei=amount_wei,
                token_address_or_name="native",
                chain_name=service.chain_name,
            )
            funded["safe"] = {"amount": safe_amount_eth, "tx_hash": tx_hash}

        if not funded:
            return {"error": "No valid accounts to fund or amounts are zero"}

        return {"status": "success", "funded": funded}

    @mcp.tool
    def olas_drain_service(service_key: str) -> dict:
        """Drain all funds from a service's accounts to the master account.

        Args:
            service_key: Service key in 'chain:id' format.

        Returns:
            Dictionary with drain results.

        """
        service, _ = _load_service(service_key)
        manager = _make_manager_for_service(service)
        drained = manager.drain_service()

        if not drained:
            return {"error": "Nothing drained. Accounts may have no balance."}

        return {"status": "success", "drained": drained}


# ---------------------------------------------------------------------------
# Info tools (1)
# ---------------------------------------------------------------------------


def _register_info_tools(mcp: FastMCP) -> None:
    @mcp.tool
    def olas_get_price() -> dict:
        """Get the current price of OLAS token in EUR from CoinGecko.

        Returns:
            Dictionary with OLAS price in EUR.

        """
        try:
            from iwa.core.pricing import PriceService

            price_service = PriceService()
            price = price_service.get_token_price("autonolas", "eur")
            return {"price_eur": price, "symbol": "OLAS"}
        except Exception as e:
            logger.error(f"Error fetching OLAS price: {e}")
            return {"price_eur": None, "symbol": "OLAS", "error": str(e)}
