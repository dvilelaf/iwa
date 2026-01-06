"""Tests for Olas contracts and ServiceManager advanced scenarios."""

from unittest.mock import MagicMock, patch

import pytest

from iwa.core.contracts.contract import ContractInstance
from iwa.plugins.olas.contracts.mech import MechContract
from iwa.plugins.olas.contracts.service import (
    ServiceManagerContract,
    ServiceRegistryContract,
    ServiceState,
)
from iwa.plugins.olas.contracts.staking import StakingContract
from iwa.plugins.olas.mech_reference import MECH_ECOSYSTEM
from iwa.plugins.olas.models import Service
from iwa.plugins.olas.service_manager import ServiceManager

VALID_ADDR = "0x1234567890123456789012345678901234567890"


@pytest.fixture
def mock_wallet():
    """Create a mock wallet fixture with necessary services."""
    wallet = MagicMock(name="wallet_mock")
    wallet.master_account.address = VALID_ADDR
    wallet.key_storage = MagicMock(name="key_storage_mock")
    wallet.transfer_service = MagicMock(name="transfer_service_mock")
    wallet.account_service = MagicMock(name="account_service_mock")
    wallet.account_service.get_accounts.return_value = []
    wallet.safe_service = MagicMock(name="safe_service_mock")
    wallet.safe_service.get_registry_address.return_value = VALID_ADDR
    wallet.sign_and_send_transaction.return_value = (
        True,
        {"status": 1, "transactionHash": b"\x01" * 32},
    )
    return wallet


def setup_manager(wallet):
    """Set up a ServiceManager instance with mocked dependencies."""
    with patch("iwa.plugins.olas.service_manager.Config"):
        with patch("iwa.plugins.olas.service_manager.ChainInterfaces") as mock_ci:
            mock_ci.return_value.get.return_value = MagicMock()
            mock_ci.return_value.get_contract_address.return_value = VALID_ADDR
            with patch.object(ServiceManager, "_init_contracts"):
                manager = ServiceManager(wallet)
                manager.registry = MagicMock(name="registry_mock")
                manager.manager = MagicMock(name="manager_mock")
                manager.chain_name = "gnosis"
                manager.wallet = wallet
                return manager


def test_staking_contract_properties(mock_wallet):
    """Test StakingContract properties and method integration."""
    with patch("iwa.plugins.olas.contracts.staking.ActivityCheckerContract"):
        with patch.object(ContractInstance, "call") as mock_call:

            def side_effect(method, *args):
                if method in [
                    "availableRewards",
                    "balance",
                    "livenessPeriod",
                    "rewardsPerSecond",
                    "maxNumServices",
                    "minStakingDeposit",
                    "minStakingDuration",
                    "epochCounter",
                    "getNextRewardCheckpointTimestamp",
                    "tsCheckpoint",
                    "getStakingState",
                    "calculateStakingReward",
                ]:
                    return 3600
                if method == "getServiceIds":
                    return [1]
                return VALID_ADDR

            mock_call.side_effect = side_effect
            c = StakingContract(VALID_ADDR, chain_name="gnosis")
            c.calculate_accrued_staking_reward(1)
            c.calculate_staking_reward(1)
            c.get_epoch_counter()
            c.get_next_epoch_start()
            c.get_service_ids()
            c.ts_checkpoint()
            with patch("time.time", return_value=1000):
                assert c.is_liveness_ratio_passed((1, 1), (0, 0), 1000) is False
            with patch.object(c, "prepare_transaction", return_value={"ok": True}):
                assert c.prepare_stake_tx(VALID_ADDR, 1) == {"ok": True}
                assert c.prepare_unstake_tx(VALID_ADDR, 1) == {"ok": True}


@patch("iwa.plugins.olas.service_manager.ERC20Contract")
def test_service_manager_complex_registration(mock_erc20_cls, mock_wallet):
    """Test ServiceManager complex registration and deployment scenarios."""
    manager = setup_manager(mock_wallet)
    manager.service = Service(
        service_name="t",
        chain_name="gnosis",
        service_id=1,
        agent_ids=[1],
        multisig_address=VALID_ADDR,
    )
    manager.service.token_address = VALID_ADDR

    # register_agent successes
    with patch(
        "iwa.plugins.olas.service_manager.base.OLAS_CONTRACTS",
        {"gnosis": {"OLAS_SERVICE_REGISTRY_TOKEN_UTILITY": VALID_ADDR}},
    ):
        manager.registry.get_service.return_value = {
            "state": ServiceState.ACTIVE_REGISTRATION,
            "security_deposit": 50,
        }
        manager.registry.get_token.return_value = VALID_ADDR
        manager.wallet.transfer_service.approve_erc20.return_value = True
        manager.registry.extract_events.return_value = [{"name": "RegisterInstance"}]
        mock_erc20_cls.return_value.balance_of_wei.return_value = 1000
        assert manager.register_agent(VALID_ADDR, 100) is True

    # deploy successes
    manager.registry.get_service.return_value = {
        "state": ServiceState.FINISHED_REGISTRATION,
        "threshold": 1,
    }
    manager.registry.call.return_value = (None, [VALID_ADDR])
    manager.registry.extract_events.return_value = [
        {"name": "DeployService"},
        {"name": "CreateMultisigWithAgents", "args": {"multisig": VALID_ADDR}},
    ]
    assert manager.deploy() == VALID_ADDR


def test_service_manager_initialization_failures(mock_wallet):
    """Test ServiceManager failure branches during initialization and setup."""
    manager = setup_manager(mock_wallet)
    manager.service = Service(service_name="t", chain_name="gnosis", service_id=1, agent_ids=[1])

    # get_staking_status failures
    manager.service = None
    assert manager.get_staking_status() is None

    manager.service = Service(service_name="t", chain_name="gnosis", service_id=1, agent_ids=[1])
    # unbond status failure
    manager.registry.get_service.return_value = {"state": ServiceState.FINISHED_REGISTRATION}
    assert manager.unbond() is False

    # sign failure in send_mech_request
    mock_wallet.sign_and_send_transaction.return_value = (False, {})
    with patch("iwa.plugins.olas.service_manager.MechContract") as mock_mech_cls:
        mock_mech = mock_mech_cls.return_value
        mock_mech.get_price.return_value = 10**15
        mock_mech.prepare_request_tx.return_value = {"to": VALID_ADDR, "data": "0x"}
        assert manager.send_mech_request(b"test", use_marketplace=False) is None


def test_service_manager_config_edges(mock_wallet):
    """Test ServiceManager configuration and initialization edge cases."""
    with patch("iwa.plugins.olas.service_manager.Config") as mock_cfg_cls:
        mock_cfg = mock_cfg_cls.return_value
        mock_cfg.plugins = {"olas": MagicMock()}
        mock_cfg.plugins["olas"].get_service.return_value = Service(
            service_name="t", chain_name="gnosis", service_id=1, agent_ids=[1]
        )
        with patch("iwa.plugins.olas.service_manager.ChainInterfaces"):
            # hits 56
            with patch(
                "iwa.plugins.olas.service_manager.base.OLAS_CONTRACTS",
                {
                    "gnosis": {
                        "OLAS_SERVICE_REGISTRY": VALID_ADDR,
                        "OLAS_SERVICE_MANAGER": VALID_ADDR,
                    }
                },
            ):
                with patch("iwa.plugins.olas.service_manager.ServiceRegistryContract"):
                    with patch("iwa.plugins.olas.service_manager.ServiceManagerContract"):
                        manager = ServiceManager(mock_wallet, service_key="gnosis:1")
                        assert manager.service is not None

            # hits 78
            with patch("iwa.plugins.olas.service_manager.base.OLAS_CONTRACTS", {"gnosis": {}}):
                with pytest.raises(ValueError):
                    ServiceManager(mock_wallet)

    # test mech reference export
    assert "gnosis" in MECH_ECOSYSTEM

    # test mech contract failures/edge cases
    with patch.object(ContractInstance, "call") as mock_call:
        mock_call.side_effect = Exception("price fail")
        mech = MechContract(VALID_ADDR, chain_name="gnosis", use_new_abi=True)
        assert mech.get_price() == 10**16

    # test service registry token failure
    reg = ServiceRegistryContract(VALID_ADDR, chain_name="gnosis")
    with patch.object(ContractInstance, "call") as mock_call:
        mock_call.side_effect = RuntimeError("token fail")
        with pytest.raises(RuntimeError):
            reg.get_token(1)

    # test service manager deploy failure
    mgr_contract = ServiceManagerContract(VALID_ADDR, chain_name="gnosis")
    # Patch the chain_interface (which mgr_contract has) instead of ContractInstance
    with patch.object(mgr_contract.chain_interface, "get_contract_address", return_value=None):
        with pytest.raises(ValueError, match="Multisig implementation or fallback handler"):
            mgr_contract.prepare_deploy_tx(VALID_ADDR, 1)


def test_service_manager_operation_failures(mock_wallet):
    """Test various ServiceManager operation failure paths."""
    manager = setup_manager(mock_wallet)
    manager.service = Service(service_name="t", chain_name="gnosis", service_id=1, agent_ids=[1])

    # create failure - utility address missing
    with patch("iwa.plugins.olas.service_manager.base.OLAS_CONTRACTS", {"gnosis": {}}):
        manager.create("gnosis", "t")  # it logs error but we just want the hit

    # create failure - approve fails
    with patch(
        "iwa.plugins.olas.service_manager.base.OLAS_CONTRACTS",
        {"gnosis": {"OLAS_SERVICE_REGISTRY_TOKEN_UTILITY": VALID_ADDR}},
    ):
        mock_wallet.transfer_service.approve_erc20.return_value = False
        manager.create("gnosis", "t", token_address_or_tag=VALID_ADDR)

    # activate_registration - state mismatch
    manager.registry.get_service.return_value = {"state": ServiceState.DEPLOYED}
    assert manager.activate_registration() is False

    # unbond - state mismatch
    manager.registry.get_service.return_value = {"state": ServiceState.PRE_REGISTRATION}
    assert manager.unbond() is False

    # terminate - fail
    manager.registry.get_service.return_value = {"state": ServiceState.DEPLOYED}
    mock_wallet.sign_and_send_transaction.return_value = (False, {})
    assert manager.terminate() is False

    # unstake - service is None
    manager.service = None
    assert manager.unstake(VALID_ADDR) is False

    # get() - service is None
    assert manager.get() is None

    # All tests passed
