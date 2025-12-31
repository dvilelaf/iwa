"""Integration tests for Olas staking contracts."""

import builtins
import json
from unittest.mock import MagicMock, mock_open, patch

from eth_account import Account

from iwa.plugins.olas.contracts.service import (
    ServiceManagerContract,
    ServiceRegistryContract,
    get_deployment_payload,
)
from iwa.plugins.olas.contracts.staking import StakingContract, StakingState

# --- Helpers ---
VALID_ADDR_1 = Account.create().address
VALID_ADDR_2 = Account.create().address
VALID_ADDR_3 = Account.create().address
VALID_ADDR_4 = Account.create().address

original_open = builtins.open

# Minimal ABI
MINIMAL_ABI = [
    {
        "constant": True,
        "inputs": [],
        "name": "agentMech",
        "outputs": [{"name": "", "type": "address"}],
        "payable": False,
        "stateMutability": "view",
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [],
        "name": "livenessRatio",
        "outputs": [{"name": "", "type": "uint256"}],
        "payable": False,
        "stateMutability": "view",
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [{"name": "_multisig", "type": "address"}],
        "name": "getMultisigNonces",
        "outputs": [{"name": "", "type": "uint256[]"}],
        "payable": False,
        "stateMutability": "view",
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [
            {"name": "currentNonces", "type": "uint256"},
            {"name": "lastNonces", "type": "uint256"},
            {"name": "timestamp", "type": "uint256"},
        ],
        "name": "isRatioPass",
        "outputs": [{"name": "", "type": "bool"}],
        "payable": False,
        "stateMutability": "view",
        "type": "function",
    },
    {
        "name": "create",
        "type": "function",
        "inputs": [{"name": "", "type": "address"}] * 6,
        "outputs": [],
    },
    {
        "name": "activateRegistration",
        "type": "function",
        "inputs": [{"name": "", "type": "uint256"}],
        "outputs": [],
    },
    {
        "name": "registerAgents",
        "type": "function",
        "inputs": [
            {"name": "", "type": "uint256"},
            {"name": "", "type": "address[]"},
            {"name": "", "type": "uint256[]"},
        ],
        "outputs": [],
    },
    {
        "name": "deploy",
        "type": "function",
        "inputs": [
            {"name": "", "type": "uint256"},
            {"name": "", "type": "address"},
            {"name": "", "type": "bytes"},
        ],
        "outputs": [],
    },
    {
        "name": "terminate",
        "type": "function",
        "inputs": [{"name": "", "type": "uint256"}],
        "outputs": [],
    },
    {
        "name": "unbond",
        "type": "function",
        "inputs": [{"name": "", "type": "uint256"}],
        "outputs": [],
    },
]


def side_effect_open(*args, **kwargs):
    """Side effect for open() to return mock ABI content."""
    filename = args[0] if args else kwargs.get("file")
    s_file = str(filename)

    if (
        "service_registry.json" in s_file
        or "service_manager.json" in s_file
        or "staking.json" in s_file
        or "activity_checker.json" in s_file
    ):
        return mock_open(read_data=json.dumps(MINIMAL_ABI))(*args, **kwargs)

    return original_open(*args, **kwargs)


# --- Contract Tests ---


def test_service_contracts():
    """Test ServiceRegistry and ServiceManager contract interactions."""
    with patch("builtins.open", side_effect=side_effect_open):
        registry = ServiceRegistryContract(VALID_ADDR_1)

        # Test get_service
        with patch.object(registry, "call") as mock_call:
            mock_call.return_value = (100, VALID_ADDR_2, b"hash", 3, 4, 4, 4, [1, 2])
            data = registry.get_service(1)
            assert data["state"].name == "DEPLOYED"
            assert data["config_hash"] == b"hash".hex()

        # Test prepare_approve_tx
        with patch.object(registry, "prepare_transaction") as mock_prep:
            mock_prep.return_value = {"data": "0xTx"}
            tx = registry.prepare_approve_tx(VALID_ADDR_2, VALID_ADDR_3, 1)
            assert tx == {"data": "0xTx"}

        manager = ServiceManagerContract(VALID_ADDR_1)

        # Mock ChainInterfaces for get_contract_address
        with patch.object(manager.chain_interface, "get_contract_address") as mock_get_addr:
            mock_get_addr.return_value = VALID_ADDR_4

            # Test prepare methods
            with patch.object(manager, "prepare_transaction") as mock_prep:
                mock_prep.return_value = {}

                manager.prepare_create_tx(
                    VALID_ADDR_2, VALID_ADDR_3, VALID_ADDR_1, "hash", [], [], 3
                )
                assert mock_prep.called
                mock_prep.reset_mock()

                manager.prepare_activate_registration_tx(VALID_ADDR_2, 1)
                assert mock_prep.called
                mock_prep.reset_mock()

                manager.prepare_register_agents_tx(VALID_ADDR_2, 1, [], [])
                assert mock_prep.called
                mock_prep.reset_mock()

                manager.prepare_deploy_tx(VALID_ADDR_2, 1)
                assert mock_prep.called
                mock_prep.reset_mock()

                manager.prepare_terminate_tx(VALID_ADDR_2, 1)
                assert mock_prep.called
                mock_prep.reset_mock()

                manager.prepare_unbond_tx(VALID_ADDR_2, 1)
                assert mock_prep.called

        # Test get_deployment_payload
        payload = get_deployment_payload(VALID_ADDR_4)
        assert isinstance(payload, str)


def test_staking_contract(tmp_path):  # noqa: C901
    """Test StakingContract logic and integration."""
    with patch("builtins.open", side_effect=side_effect_open):
        with patch("iwa.core.contracts.contract.ChainInterfaces") as mock_interfaces:
            mock_chain = MagicMock()
            mock_interfaces.return_value.get.return_value = mock_chain

            # Mock web3
            mock_web3 = MagicMock()
            mock_chain.web3 = mock_web3

            # Mock contract factory
            mock_contract = MagicMock()
            mock_web3.eth.contract.return_value = mock_contract

            # Mock function calls (ActivityChecker)
            mock_contract.functions.agentMech.return_value.call.return_value = VALID_ADDR_2
            mock_contract.functions.livenessRatio.return_value.call.return_value = 10**18

            with patch(
                "iwa.plugins.olas.contracts.staking.ContractInstance.call"
            ) as mock_call_base:
                # Initialization side effect
                def init_side_effect(method, *args):
                    if method == "activityChecker":
                        return VALID_ADDR_4
                    if method == "stakingToken":
                        return VALID_ADDR_2
                    return 0

                mock_call_base.side_effect = init_side_effect

                staking = StakingContract(VALID_ADDR_1)

                # Logic side effect
                def logic_side_effect(method, *args):
                    if method == "getServiceInfo":
                        # Returns: (multisig, owner, nonces_on_last_checkpoint, ts_start, accrued_reward, inactivity)
                        # nonces_on_last_checkpoint must be [safe_nonce, mech_requests]
                        return (VALID_ADDR_2, VALID_ADDR_3, [1, 1], 1000, 50, 0)
                    if method == "getNextRewardCheckpointTimestamp":
                        return 4700000000  # Timestamp in future
                    if method == "calculateStakingLastReward":
                        return 50
                    if method == "calculateStakingReward":
                        return 50
                    if method == "getStakingState":
                        return 1
                    return 0

                mock_call_base.side_effect = logic_side_effect

                # Test methods
                # Note: logic_side_effect handles different calls now
                assert staking.calculate_accrued_staking_reward(1) == 50
                assert staking.calculate_staking_reward(1) == 50
                assert staking.get_staking_state(1) == StakingState.STAKED
                assert staking.call("nonexistent") == 0

                # Activity checker interactions - nonces now returns [safe_nonce, mech_requests]
                mock_contract.functions.getMultisigNonces.return_value.call.return_value = [5, 3]
                staking.activity_checker.contract = mock_contract

                staking.ts_checkpoint = MagicMock(return_value=0)

                # Trigger original_open hit
                try:
                    test_file = tmp_path / "test_lookup.txt"
                    with builtins.open(str(test_file), "w") as f:
                        f.write("test")
                except Exception:
                    pass

                info = staking.get_service_info(1)
                assert info["owner_address"] == VALID_ADDR_3
                assert "remaining_epoch_seconds" in info
                assert info["remaining_epoch_seconds"] > 0
                # Verify new nonces fields
                assert info["current_safe_nonce"] == 5
                assert info["current_mech_requests"] == 3
