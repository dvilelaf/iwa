"""Error handling tests for Olas ServiceManager."""

from unittest.mock import MagicMock, patch

import pytest

from iwa.plugins.olas.contracts.staking import StakingState
from iwa.plugins.olas.models import Service
from iwa.plugins.olas.service_manager import ServiceManager, ServiceState

VALID_ADDR = "0x1234567890123456789012345678901234567890"


@pytest.fixture
def mock_wallet():
    """Create a mock wallet for tests."""
    wallet = MagicMock()
    wallet.master_account.address = VALID_ADDR
    wallet.chain_interface.chain_name = "gnosis"
    wallet.sign_and_send_transaction.return_value = (True, {"transactionHash": b"\x00" * 32})
    wallet.key_storage.create_account.return_value.address = VALID_ADDR
    wallet.key_storage.get_account.return_value.address = VALID_ADDR
    return wallet


def setup_manager(mock_wallet):
    """Setup a ServiceManager with mocked dependencies."""
    with patch("iwa.plugins.olas.service_manager.base.Config") as mock_cfg_cls:
        mock_cfg = mock_cfg_cls.return_value
        mock_cfg.plugins = {"olas": MagicMock()}
        mock_cfg.plugins["olas"].get_service.return_value = None
        with patch(
            "iwa.plugins.olas.service_manager.OLAS_CONTRACTS",
            {
                "gnosis": {
                    "OLAS_SERVICE_REGISTRY": VALID_ADDR,
                    "OLAS_SERVICE_MANAGER": VALID_ADDR,
                    "OLAS_MECH": VALID_ADDR,
                }
            },
        ):
            with patch("iwa.plugins.olas.service_manager.base.ChainInterfaces") as mock_if_cls:
                mock_if = mock_if_cls.return_value
                mock_if.get.return_value.chain.name.lower.return_value = "gnosis"
                mock_if.get.return_value.get_contract_address.return_value = VALID_ADDR
                manager = ServiceManager(mock_wallet)
                manager.registry = MagicMock()
                manager.manager_contract = MagicMock()
                manager.olas_config = mock_cfg.plugins["olas"]
                manager.chain_name = "gnosis"
                manager.registry.chain_interface.get_contract_address.return_value = VALID_ADDR
                return manager


def test_service_manager_mech_requests_failures(mock_wallet):
    """Test failure paths in mech requests."""
    manager = setup_manager(mock_wallet)

    # Service missing
    manager.service = None
    assert manager.send_mech_request(b"data") is None

    manager.service = Service(
        service_name="t",
        chain_name="gnosis",
        service_id=1,
        agent_ids=[1],
        multisig_address=VALID_ADDR,
    )

    # Marketplace failures
    with patch("iwa.plugins.olas.service_manager.mech.MechMarketplaceContract") as mock_mkt_cls:
        mock_mkt = mock_mkt_cls.return_value

        # No marketplace address
        with patch("iwa.plugins.olas.service_manager.OLAS_CONTRACTS", {"gnosis": {}}):
            assert manager.send_mech_request(b"data", use_marketplace=True) is None

        # No priority_mech
        assert manager.send_mech_request(b"data", use_marketplace=True, priority_mech=None) is None

        # Invalid priority mech factory
        mock_mkt.call.return_value = "0x0000000000000000000000000000000000000000"
        assert (
            manager.send_mech_request(b"data", use_marketplace=True, priority_mech=VALID_ADDR)
            is None
        )

        # No priority mech factory multisig
        mock_mkt.call.side_effect = ["0x1234", "0x0000000000000000000000000000000000000000"]
        assert (
            manager.send_mech_request(b"data", use_marketplace=True, priority_mech=VALID_ADDR)
            is None
        )

    # Legacy failures
    # Legacy mech address missing
    with patch("iwa.plugins.olas.service_manager.OLAS_CONTRACTS", {"gnosis": {}}):
        assert manager.send_mech_request(b"data", use_marketplace=False) is None


def test_service_manager_lifecycle_failures(mock_wallet):
    """Test failure paths in lifecycle methods."""
    manager = setup_manager(mock_wallet)
    manager.service = Service(service_name="t", chain_name="gnosis", service_id=1, agent_ids=[1])

    # register_agent failures
    # Initial state mismatch for agent registration
    manager.registry.get_service.return_value = {"state": ServiceState.PRE_REGISTRATION}
    assert manager.register_agent() is False

    # stake failures
    # Initial state mismatch for staking
    manager.service.staking_contract_address = VALID_ADDR
    manager.registry.get_service.return_value = {"state": ServiceState.PRE_REGISTRATION}
    mock_staking = MagicMock()
    mock_staking.staking_token_address = VALID_ADDR
    mock_staking.get_requirements.return_value = {
        "staking_token": VALID_ADDR,
        "min_staking_deposit": 50000000000000000000,
        "num_agent_instances": 1,
        "required_agent_bond": 50000000000000000000,
    }
    with patch("iwa.plugins.olas.service_manager.staking.ERC20Contract"):
        assert manager.stake(mock_staking) is False

    # unstake failures
    # Service not staked
    manager.service.staking_contract_address = None
    mock_staking = MagicMock()
    mock_staking.get_staking_state.return_value = StakingState.NOT_STAKED
    assert manager.unstake(mock_staking) is False

    # unbond failures
    # Event missing in unbond
    manager.registry.get_service.return_value = {"state": ServiceState.TERMINATED_BONDED}
    mock_wallet.sign_and_send_transaction.return_value = (True, {"transactionHash": b"hex"})
    manager.registry.extract_events.return_value = []
    # manager.manager is what is used in unbond (line 523)
    manager.manager = MagicMock()
    assert manager.unbond() is False

    # spin_up/wind_down failure log lines
    manager.registry.get_service.return_value = {"state": ServiceState.DEPLOYED}
    assert manager.spin_up() is True

    manager.registry.get_service.return_value = {"state": ServiceState.PRE_REGISTRATION}
    assert manager.wind_down() is True


def test_service_manager_staking_status_failures(mock_wallet):
    """Test failure paths in get_staking_status."""
    manager = setup_manager(mock_wallet)

    # Service missing
    manager.service = None
    assert manager.get_staking_status() is None

    manager.service = Service(service_name="t", chain_name="gnosis", service_id=1, agent_ids=[1])
    # Staking contract missing
    manager.service.staking_contract_address = None
    status = manager.get_staking_status()
    assert status.is_staked is False

    # Exception in contract loading
    manager.service.staking_contract_address = VALID_ADDR
    with patch("iwa.plugins.olas.service_manager.staking.StakingContract") as mock_staking_cls:
        mock_staking_cls.side_effect = Exception("fail")
        status = manager.get_staking_status()
        assert status.staking_state == "ERROR"

        # Exception in get_service_info
        mock_staking_cls.side_effect = None
        mock_staking = mock_staking_cls.return_value
        mock_staking.get_staking_state.return_value = StakingState.STAKED
        mock_staking.get_service_info.side_effect = Exception("fail")
        status = manager.get_staking_status()
        assert status.is_staked is True
        assert status.mech_requests_this_epoch == 0


def test_service_manager_verify_event_exception(mock_wallet):
    """Test exception path in _execute_mech_tx."""
    manager = setup_manager(mock_wallet)
    manager.service = Service(
        service_name="t",
        chain_name="gnosis",
        service_id=1,
        agent_ids=[1],
        multisig_address=VALID_ADDR,
    )

    # EOA path

    with patch.object(manager.wallet.account_service, "resolve_account") as mock_resolve:
        mock_resolve.return_value = MagicMock()
        mock_resolve.return_value.__class__ = object

        # Exception in extract_events
        with patch.object(
            manager.registry.chain_interface.web3.eth, "wait_for_transaction_receipt"
        ) as mock_wait:
            mock_wait.return_value = {"logs": []}
            manager.registry.extract_events.side_effect = Exception("fail")
            assert (
                manager._execute_mech_tx({"data": "0x"}, VALID_ADDR, manager.registry, "Event")
                is None
            )
