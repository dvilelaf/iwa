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

            # Mock web3 - use _web3 since contract.py now accesses _web3 directly
            mock_web3 = MagicMock()
            mock_chain.web3 = mock_web3
            mock_chain.web3._web3 = mock_web3  # For RPC rotation fix

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
                # Mock via patch since contract is now a property
                staking.activity_checker.get_multisig_nonces = MagicMock(return_value=(5, 3))

                staking.ts_checkpoint = MagicMock(return_value=0)

                # Mock get_required_requests to return an int (not MagicMock)
                staking.get_required_requests = MagicMock(return_value=2)

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


def test_get_checkpoint_events():
    """Test get_checkpoint_events method."""
    with patch("builtins.open", side_effect=side_effect_open):
        with patch("iwa.core.contracts.contract.ChainInterfaces") as mock_interfaces:
            mock_chain = MagicMock()
            mock_interfaces.return_value.get.return_value = mock_chain

            mock_web3 = MagicMock()
            mock_chain.web3 = mock_web3
            mock_chain.web3._web3 = mock_web3
            mock_web3.eth.block_number = 1000

            mock_contract = MagicMock()
            mock_web3.eth.contract.return_value = mock_contract

            # Mock ActivityChecker calls
            mock_contract.functions.agentMech.return_value.call.return_value = VALID_ADDR_2
            mock_contract.functions.livenessRatio.return_value.call.return_value = 10**18

            with patch(
                "iwa.plugins.olas.contracts.staking.ContractInstance.call"
            ) as mock_call_base:

                def init_side_effect(method, *args):
                    if method == "activityChecker":
                        return VALID_ADDR_4
                    if method == "stakingToken":
                        return VALID_ADDR_2
                    return 0

                mock_call_base.side_effect = init_side_effect

                staking = StakingContract(VALID_ADDR_1)

                # Test 1: Checkpoint event with rewarded services
                mock_checkpoint_log = MagicMock()
                mock_checkpoint_log.args = {
                    "epoch": 42,
                    "serviceIds": [101, 102, 103],
                    "rewards": [1000, 2000, 3000],
                }
                mock_checkpoint_log.blockNumber = 999

                mock_checkpoint_filter = MagicMock()
                mock_checkpoint_filter.get_all_entries.return_value = [mock_checkpoint_log]
                mock_contract.events.Checkpoint.create_filter.return_value = (
                    mock_checkpoint_filter
                )

                # No warnings or evictions
                mock_warning_filter = MagicMock()
                mock_warning_filter.get_all_entries.return_value = []
                mock_contract.events.ServiceInactivityWarning.create_filter.return_value = (
                    mock_warning_filter
                )

                mock_evicted_filter = MagicMock()
                mock_evicted_filter.get_all_entries.return_value = []
                mock_contract.events.ServicesEvicted.create_filter.return_value = (
                    mock_evicted_filter
                )

                result = staking.get_checkpoint_events(from_block=900, to_block=1000)

                assert result["epoch"] == 42
                assert result["checkpoint_block"] == 999
                assert result["rewarded_services"] == {101: 1000, 102: 2000, 103: 3000}
                assert result["inactivity_warnings"] == []
                assert result["evicted_services"] == []


def test_get_checkpoint_events_with_warnings():
    """Test get_checkpoint_events with inactivity warnings."""
    with patch("builtins.open", side_effect=side_effect_open):
        with patch("iwa.core.contracts.contract.ChainInterfaces") as mock_interfaces:
            mock_chain = MagicMock()
            mock_interfaces.return_value.get.return_value = mock_chain

            mock_web3 = MagicMock()
            mock_chain.web3 = mock_web3
            mock_chain.web3._web3 = mock_web3
            mock_web3.eth.block_number = 1000

            mock_contract = MagicMock()
            mock_web3.eth.contract.return_value = mock_contract

            mock_contract.functions.agentMech.return_value.call.return_value = VALID_ADDR_2
            mock_contract.functions.livenessRatio.return_value.call.return_value = 10**18

            with patch(
                "iwa.plugins.olas.contracts.staking.ContractInstance.call"
            ) as mock_call_base:

                def init_side_effect(method, *args):
                    if method == "activityChecker":
                        return VALID_ADDR_4
                    if method == "stakingToken":
                        return VALID_ADDR_2
                    return 0

                mock_call_base.side_effect = init_side_effect

                staking = StakingContract(VALID_ADDR_1)

                # Checkpoint event
                mock_checkpoint_log = MagicMock()
                mock_checkpoint_log.args = {
                    "epoch": 10,
                    "serviceIds": [101, 102],
                    "rewards": [1000, 2000],
                }
                mock_checkpoint_log.blockNumber = 999

                mock_checkpoint_filter = MagicMock()
                mock_checkpoint_filter.get_all_entries.return_value = [mock_checkpoint_log]
                mock_contract.events.Checkpoint.create_filter.return_value = (
                    mock_checkpoint_filter
                )

                # Inactivity warnings
                mock_warning_log_1 = MagicMock()
                mock_warning_log_1.args = {"serviceId": 101}
                mock_warning_log_2 = MagicMock()
                mock_warning_log_2.args = {"serviceId": 103}

                mock_warning_filter = MagicMock()
                mock_warning_filter.get_all_entries.return_value = [
                    mock_warning_log_1,
                    mock_warning_log_2,
                ]
                mock_contract.events.ServiceInactivityWarning.create_filter.return_value = (
                    mock_warning_filter
                )

                mock_evicted_filter = MagicMock()
                mock_evicted_filter.get_all_entries.return_value = []
                mock_contract.events.ServicesEvicted.create_filter.return_value = (
                    mock_evicted_filter
                )

                result = staking.get_checkpoint_events(from_block=900)

                assert result["epoch"] == 10
                assert result["inactivity_warnings"] == [101, 103]
                assert result["evicted_services"] == []


def test_get_checkpoint_events_with_evictions():
    """Test get_checkpoint_events with evicted services."""
    with patch("builtins.open", side_effect=side_effect_open):
        with patch("iwa.core.contracts.contract.ChainInterfaces") as mock_interfaces:
            mock_chain = MagicMock()
            mock_interfaces.return_value.get.return_value = mock_chain

            mock_web3 = MagicMock()
            mock_chain.web3 = mock_web3
            mock_chain.web3._web3 = mock_web3
            mock_web3.eth.block_number = 1000

            mock_contract = MagicMock()
            mock_web3.eth.contract.return_value = mock_contract

            mock_contract.functions.agentMech.return_value.call.return_value = VALID_ADDR_2
            mock_contract.functions.livenessRatio.return_value.call.return_value = 10**18

            with patch(
                "iwa.plugins.olas.contracts.staking.ContractInstance.call"
            ) as mock_call_base:

                def init_side_effect(method, *args):
                    if method == "activityChecker":
                        return VALID_ADDR_4
                    if method == "stakingToken":
                        return VALID_ADDR_2
                    return 0

                mock_call_base.side_effect = init_side_effect

                staking = StakingContract(VALID_ADDR_1)

                # Checkpoint event
                mock_checkpoint_log = MagicMock()
                mock_checkpoint_log.args = {
                    "epoch": 5,
                    "serviceIds": [102],
                    "rewards": [5000],
                }
                mock_checkpoint_log.blockNumber = 888

                mock_checkpoint_filter = MagicMock()
                mock_checkpoint_filter.get_all_entries.return_value = [mock_checkpoint_log]
                mock_contract.events.Checkpoint.create_filter.return_value = (
                    mock_checkpoint_filter
                )

                # No warnings
                mock_warning_filter = MagicMock()
                mock_warning_filter.get_all_entries.return_value = []
                mock_contract.events.ServiceInactivityWarning.create_filter.return_value = (
                    mock_warning_filter
                )

                # Evictions
                mock_evicted_log = MagicMock()
                mock_evicted_log.args = {"serviceIds": [101, 104]}

                mock_evicted_filter = MagicMock()
                mock_evicted_filter.get_all_entries.return_value = [mock_evicted_log]
                mock_contract.events.ServicesEvicted.create_filter.return_value = (
                    mock_evicted_filter
                )

                result = staking.get_checkpoint_events(from_block=800)

                assert result["epoch"] == 5
                assert result["checkpoint_block"] == 888
                assert result["rewarded_services"] == {102: 5000}
                assert result["evicted_services"] == [101, 104]


def test_get_checkpoint_events_no_events():
    """Test get_checkpoint_events when no checkpoint events found."""
    with patch("builtins.open", side_effect=side_effect_open):
        with patch("iwa.core.contracts.contract.ChainInterfaces") as mock_interfaces:
            mock_chain = MagicMock()
            mock_interfaces.return_value.get.return_value = mock_chain

            mock_web3 = MagicMock()
            mock_chain.web3 = mock_web3
            mock_chain.web3._web3 = mock_web3
            mock_web3.eth.block_number = 1000

            mock_contract = MagicMock()
            mock_web3.eth.contract.return_value = mock_contract

            mock_contract.functions.agentMech.return_value.call.return_value = VALID_ADDR_2
            mock_contract.functions.livenessRatio.return_value.call.return_value = 10**18

            with patch(
                "iwa.plugins.olas.contracts.staking.ContractInstance.call"
            ) as mock_call_base:

                def init_side_effect(method, *args):
                    if method == "activityChecker":
                        return VALID_ADDR_4
                    if method == "stakingToken":
                        return VALID_ADDR_2
                    return 0

                mock_call_base.side_effect = init_side_effect

                staking = StakingContract(VALID_ADDR_1)

                # No checkpoint events
                mock_checkpoint_filter = MagicMock()
                mock_checkpoint_filter.get_all_entries.return_value = []
                mock_contract.events.Checkpoint.create_filter.return_value = (
                    mock_checkpoint_filter
                )

                mock_warning_filter = MagicMock()
                mock_warning_filter.get_all_entries.return_value = []
                mock_contract.events.ServiceInactivityWarning.create_filter.return_value = (
                    mock_warning_filter
                )

                mock_evicted_filter = MagicMock()
                mock_evicted_filter.get_all_entries.return_value = []
                mock_contract.events.ServicesEvicted.create_filter.return_value = (
                    mock_evicted_filter
                )

                result = staking.get_checkpoint_events(from_block=900)

                assert result["epoch"] is None
                assert result["checkpoint_block"] is None
                assert result["rewarded_services"] == {}
                assert result["inactivity_warnings"] == []
                assert result["evicted_services"] == []


def test_get_checkpoint_events_handles_exceptions():
    """Test get_checkpoint_events handles exceptions gracefully."""
    with patch("builtins.open", side_effect=side_effect_open):
        with patch("iwa.core.contracts.contract.ChainInterfaces") as mock_interfaces:
            mock_chain = MagicMock()
            mock_interfaces.return_value.get.return_value = mock_chain

            mock_web3 = MagicMock()
            mock_chain.web3 = mock_web3
            mock_chain.web3._web3 = mock_web3
            mock_web3.eth.block_number = 1000

            mock_contract = MagicMock()
            mock_web3.eth.contract.return_value = mock_contract

            mock_contract.functions.agentMech.return_value.call.return_value = VALID_ADDR_2
            mock_contract.functions.livenessRatio.return_value.call.return_value = 10**18

            with patch(
                "iwa.plugins.olas.contracts.staking.ContractInstance.call"
            ) as mock_call_base:

                def init_side_effect(method, *args):
                    if method == "activityChecker":
                        return VALID_ADDR_4
                    if method == "stakingToken":
                        return VALID_ADDR_2
                    return 0

                mock_call_base.side_effect = init_side_effect

                staking = StakingContract(VALID_ADDR_1)

                # Checkpoint filter raises an exception
                mock_contract.events.Checkpoint.create_filter.side_effect = Exception(
                    "RPC error"
                )

                result = staking.get_checkpoint_events(from_block=900)

                # Should return default empty result
                assert result["epoch"] is None
                assert result["rewarded_services"] == {}
                assert result["inactivity_warnings"] == []
                assert result["evicted_services"] == []


def test_fetch_events_chunked_splits_large_range():
    """Test that _fetch_events_chunked splits large block ranges into chunks."""
    with patch("builtins.open", side_effect=side_effect_open):
        with patch("iwa.core.contracts.contract.ChainInterfaces") as mock_interfaces:
            mock_chain = MagicMock()
            mock_interfaces.return_value.get.return_value = mock_chain

            mock_web3 = MagicMock()
            mock_chain.web3 = mock_web3
            mock_chain.web3._web3 = mock_web3
            mock_web3.eth.block_number = 2000

            mock_contract = MagicMock()
            mock_web3.eth.contract.return_value = mock_contract

            mock_contract.functions.agentMech.return_value.call.return_value = VALID_ADDR_2
            mock_contract.functions.livenessRatio.return_value.call.return_value = 10**18

            with patch(
                "iwa.plugins.olas.contracts.staking.ContractInstance.call"
            ) as mock_call_base:

                def init_side_effect(method, *args):
                    if method == "activityChecker":
                        return VALID_ADDR_4
                    if method == "stakingToken":
                        return VALID_ADDR_2
                    return 0

                mock_call_base.side_effect = init_side_effect

                staking = StakingContract(VALID_ADDR_1)

                # Track calls to create_filter
                call_ranges = []

                def track_filter_calls(from_block, to_block):
                    call_ranges.append((from_block, to_block))
                    mock_filter = MagicMock()
                    mock_filter.get_all_entries.return_value = []
                    return mock_filter

                mock_contract.events.Checkpoint.create_filter.side_effect = (
                    track_filter_calls
                )

                # Fetch 1200 blocks with chunk_size=500 -> should make 3 calls
                staking._fetch_events_chunked("Checkpoint", 0, 1199, chunk_size=500)

                assert len(call_ranges) == 3
                assert call_ranges[0] == (0, 499)
                assert call_ranges[1] == (500, 999)
                assert call_ranges[2] == (1000, 1199)


def test_fetch_events_chunked_retries_with_smaller_chunks():
    """Test that _fetch_events_chunked retries with smaller chunks on range error."""
    with patch("builtins.open", side_effect=side_effect_open):
        with patch("iwa.core.contracts.contract.ChainInterfaces") as mock_interfaces:
            mock_chain = MagicMock()
            mock_interfaces.return_value.get.return_value = mock_chain

            mock_web3 = MagicMock()
            mock_chain.web3 = mock_web3
            mock_chain.web3._web3 = mock_web3
            mock_web3.eth.block_number = 1000

            mock_contract = MagicMock()
            mock_web3.eth.contract.return_value = mock_contract

            mock_contract.functions.agentMech.return_value.call.return_value = VALID_ADDR_2
            mock_contract.functions.livenessRatio.return_value.call.return_value = 10**18

            with patch(
                "iwa.plugins.olas.contracts.staking.ContractInstance.call"
            ) as mock_call_base:

                def init_side_effect(method, *args):
                    if method == "activityChecker":
                        return VALID_ADDR_4
                    if method == "stakingToken":
                        return VALID_ADDR_2
                    return 0

                mock_call_base.side_effect = init_side_effect

                staking = StakingContract(VALID_ADDR_1)

                call_count = [0]

                def fail_then_succeed(from_block, to_block):
                    call_count[0] += 1
                    # First call fails with range error, subsequent calls succeed
                    if call_count[0] == 1:
                        raise Exception("block range too large")
                    mock_filter = MagicMock()
                    mock_filter.get_all_entries.return_value = []
                    return mock_filter

                mock_contract.events.Checkpoint.create_filter.side_effect = (
                    fail_then_succeed
                )

                # Should retry with smaller chunks
                result = staking._fetch_events_chunked(
                    "Checkpoint", 0, 499, chunk_size=500
                )

                # First call fails, then retries with chunk_size=250 (2 calls)
                assert call_count[0] >= 2
                assert result == []


def test_fetch_events_chunked_aggregates_results():
    """Test that _fetch_events_chunked aggregates events from all chunks."""
    with patch("builtins.open", side_effect=side_effect_open):
        with patch("iwa.core.contracts.contract.ChainInterfaces") as mock_interfaces:
            mock_chain = MagicMock()
            mock_interfaces.return_value.get.return_value = mock_chain

            mock_web3 = MagicMock()
            mock_chain.web3 = mock_web3
            mock_chain.web3._web3 = mock_web3
            mock_web3.eth.block_number = 1000

            mock_contract = MagicMock()
            mock_web3.eth.contract.return_value = mock_contract

            mock_contract.functions.agentMech.return_value.call.return_value = VALID_ADDR_2
            mock_contract.functions.livenessRatio.return_value.call.return_value = 10**18

            with patch(
                "iwa.plugins.olas.contracts.staking.ContractInstance.call"
            ) as mock_call_base:

                def init_side_effect(method, *args):
                    if method == "activityChecker":
                        return VALID_ADDR_4
                    if method == "stakingToken":
                        return VALID_ADDR_2
                    return 0

                mock_call_base.side_effect = init_side_effect

                staking = StakingContract(VALID_ADDR_1)

                chunk_num = [0]

                def return_different_events(from_block, to_block):
                    chunk_num[0] += 1
                    mock_filter = MagicMock()
                    # Each chunk returns a different event
                    event = MagicMock()
                    event.args = {"serviceId": 100 + chunk_num[0]}
                    mock_filter.get_all_entries.return_value = [event]
                    return mock_filter

                mock_contract.events.ServiceInactivityWarning.create_filter.side_effect = (
                    return_different_events
                )

                # Fetch 600 blocks with chunk_size=200 -> 3 chunks
                result = staking._fetch_events_chunked(
                    "ServiceInactivityWarning", 0, 599, chunk_size=200
                )

                # Should have 3 events aggregated
                assert len(result) == 3
                service_ids = [e.args["serviceId"] for e in result]
                assert service_ids == [101, 102, 103]
