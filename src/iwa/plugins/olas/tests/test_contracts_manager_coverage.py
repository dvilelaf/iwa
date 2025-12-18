"""Coverage tests for Olas Service Manager."""

from unittest.mock import MagicMock, patch

import pytest

from iwa.plugins.olas.contracts.service import ServiceState
from iwa.plugins.olas.contracts.staking import StakingState
from iwa.plugins.olas.service_manager import ServiceManager


@pytest.fixture
def mock_wallet():
    """Mock wallet for testing."""
    wallet = MagicMock()
    wallet.master_account.address = "0xMaster"
    wallet.key_storage.get_account.return_value.address = "0xOwner"
    wallet.sign_and_send_transaction.return_value = (True, {"status": 1})
    wallet.send.return_value = (True, {"status": 1})
    return wallet


@pytest.fixture
def mock_config():
    """Mock config for testing."""
    config = MagicMock()
    config.plugins = {"olas": MagicMock()}
    config.plugins["olas"].services.service_id = 1
    config.plugins["olas"].chain_name = "gnosis"
    return config


@patch("iwa.plugins.olas.service_manager.Config")
@patch("iwa.plugins.olas.service_manager.ServiceRegistryContract")
@patch("iwa.plugins.olas.service_manager.ServiceManagerContract")
@patch("iwa.plugins.olas.service_manager.ERC20Contract")
def test_create_service_success(
    mock_erc20, mock_sm_contract, mock_registry_contract, mock_config_cls, mock_wallet
):
    """Test successful service creation."""
    # Setup Config
    mock_config_inst = mock_config_cls.return_value
    mock_config_inst.plugins = {"olas": MagicMock()}
    mock_olas_config = mock_config_inst.plugins["olas"]
    mock_olas_config.chain_name = "gnosis"

    # Setup Registry to return event
    mock_registry_inst = mock_registry_contract.return_value
    mock_registry_inst.extract_events.return_value = [
        {"name": "CreateService", "args": {"serviceId": 123}}
    ]

    # Setup Manager
    manager = ServiceManager(mock_wallet)

    # Patch ChainInterfaces
    with patch("iwa.plugins.olas.service_manager.ChainInterfaces") as mock_chains:
        mock_chains.return_value.get.return_value.chain.get_token_address.return_value = "0xToken"

        # Call create
        service_id = manager.create(bond_amount=10)

        assert service_id == 123
        assert mock_olas_config.service_id == 123


@patch("iwa.plugins.olas.service_manager.Config")
@patch("iwa.plugins.olas.service_manager.ServiceRegistryContract")
@patch("iwa.plugins.olas.service_manager.ServiceManagerContract")
@patch("iwa.plugins.olas.service_manager.ERC20Contract")
def test_create_service_failures(
    mock_erc20, mock_sm_contract, mock_registry_contract, mock_config_cls, mock_wallet
):
    """Test service creation failure modes."""
    mock_config_inst = mock_config_cls.return_value
    mock_config_inst.plugins = {"olas": MagicMock()}

    manager = ServiceManager(mock_wallet)

    # 1. Transaction fails
    mock_wallet.sign_and_send_transaction.return_value = (False, {})
    with patch("iwa.plugins.olas.service_manager.ChainInterfaces"):
        res = manager.create()
        assert res is None

    # Reset wallet
    mock_wallet.sign_and_send_transaction.return_value = (True, {})

    # 2. Event missing
    mock_registry_contract.return_value.extract_events.return_value = []
    with patch("iwa.plugins.olas.service_manager.ChainInterfaces"):
        res = manager.create()
        # Should effectively return None/False depending on implementation,
        # code says "if service_id is None: logger.error..." but proceeds to assign None
        # and returns service_id which is None.
        assert res is None

    # 3. Approval fails
    mock_registry_contract.return_value.extract_events.return_value = [
        {"name": "CreateService", "args": {"serviceId": 123}}
    ]
    # First tx (create) success, Second tx (approve) fails
    mock_wallet.sign_and_send_transaction.side_effect = [(True, {}), (False, {})]

    with patch("iwa.plugins.olas.service_manager.ChainInterfaces"):
        res = manager.create(token_address_or_tag="0xToken")
        assert res is False


@patch("iwa.plugins.olas.service_manager.Config")
@patch("iwa.plugins.olas.service_manager.ServiceRegistryContract")
@patch("iwa.plugins.olas.service_manager.ServiceManagerContract")
@patch("iwa.plugins.olas.service_manager.ERC20Contract")
def test_create_service_with_approval(
    mock_erc20, mock_sm_contract, mock_registry_contract, mock_config_cls, mock_wallet
):
    """Test service creation with token approval."""
    mock_config_inst = mock_config_cls.return_value
    mock_config_inst.plugins = {"olas": MagicMock()}

    mock_registry_inst = mock_registry_contract.return_value
    mock_registry_inst.extract_events.return_value = [
        {"name": "CreateService", "args": {"serviceId": 123}}
    ]

    manager = ServiceManager(mock_wallet)

    with patch("iwa.plugins.olas.service_manager.ChainInterfaces"):
        manager.create(token_address_or_tag="0xToken")

        mock_erc20.assert_called()
        mock_erc20.return_value.prepare_approve_tx.assert_called()
        assert mock_wallet.sign_and_send_transaction.call_count == 2


@patch("iwa.plugins.olas.service_manager.Config")
@patch("iwa.plugins.olas.service_manager.ServiceRegistryContract")
@patch("iwa.plugins.olas.service_manager.ServiceManagerContract")
def test_activate_registration(
    mock_sm_contract, mock_registry_contract, mock_config_cls, mock_wallet
):
    """Test service registration activation."""
    mock_config_inst = mock_config_cls.return_value
    mock_olas_config = MagicMock()
    mock_olas_config.service_id = 123
    mock_config_inst.plugins = {"olas": mock_olas_config}

    mock_registry_inst = mock_registry_contract.return_value
    mock_registry_inst.get_service.return_value = {"state": ServiceState.PRE_REGISTRATION}
    mock_registry_inst.extract_events.return_value = [{"name": "ActivateRegistration"}]

    manager = ServiceManager(mock_wallet)

    success = manager.activate_registration()
    assert success is True

    # Failures
    # 1. Wrong state
    mock_registry_inst.get_service.return_value = {"state": ServiceState.DEPLOYED}
    assert manager.activate_registration() is False

    # 2. Tx fail
    mock_registry_inst.get_service.return_value = {"state": ServiceState.PRE_REGISTRATION}
    mock_wallet.sign_and_send_transaction.return_value = (False, {})
    assert manager.activate_registration() is False

    # 3. Event missing
    mock_wallet.sign_and_send_transaction.return_value = (True, {})
    mock_registry_inst.extract_events.return_value = []
    assert manager.activate_registration() is False


@patch("iwa.plugins.olas.service_manager.Config")
@patch("iwa.plugins.olas.service_manager.ServiceRegistryContract")
@patch("iwa.plugins.olas.service_manager.ServiceManagerContract")
def test_register_agent(mock_sm_contract, mock_registry_contract, mock_config_cls, mock_wallet):
    """Test agent registration flow."""
    mock_config_inst = mock_config_cls.return_value
    mock_olas_config = MagicMock()
    mock_olas_config.service_id = 123
    mock_config_inst.plugins = {"olas": mock_olas_config}

    mock_registry_inst = mock_registry_contract.return_value
    mock_registry_inst.get_service.return_value = {"state": ServiceState.ACTIVE_REGISTRATION}
    mock_registry_inst.extract_events.return_value = [{"name": "RegisterInstance"}]

    manager = ServiceManager(mock_wallet)

    success = manager.register_agent()
    assert success is True
    assert mock_olas_config.agent_address is not None

    # Failures
    # 1. Wrong state
    mock_registry_inst.get_service.return_value = {"state": ServiceState.PRE_REGISTRATION}
    assert manager.register_agent() is False

    # 2. Tx fail
    mock_registry_inst.get_service.return_value = {"state": ServiceState.ACTIVE_REGISTRATION}
    mock_wallet.sign_and_send_transaction.return_value = (False, {})
    assert manager.register_agent() is False

    # 3. Event missing
    mock_wallet.sign_and_send_transaction.return_value = (True, {})
    mock_registry_inst.extract_events.return_value = []
    assert manager.register_agent() is False


@patch("iwa.plugins.olas.service_manager.Config")
@patch("iwa.plugins.olas.service_manager.ServiceRegistryContract")
@patch("iwa.plugins.olas.service_manager.ServiceManagerContract")
def test_deploy(mock_sm_contract, mock_registry_contract, mock_config_cls, mock_wallet):
    """Test service deployment."""
    mock_config_inst = mock_config_cls.return_value
    mock_olas_config = MagicMock()
    mock_olas_config.service_id = 123
    mock_config_inst.plugins = {"olas": mock_olas_config}

    mock_registry_inst = mock_registry_contract.return_value
    mock_registry_inst.get_service.return_value = {"state": ServiceState.FINISHED_REGISTRATION}
    mock_registry_inst.extract_events.return_value = [
        {"name": "DeployService"},
        {"name": "CreateMultisigWithAgents", "args": {"multisig": "0xMultisig"}},
    ]

    manager = ServiceManager(mock_wallet)

    multisig = manager.deploy()
    assert multisig == "0xMultisig"
    assert mock_olas_config.multisig_address == "0xMultisig"

    # Failures
    # 1. Wrong state
    mock_registry_inst.get_service.return_value = {"state": ServiceState.PRE_REGISTRATION}
    assert manager.deploy() is False  # returns False or None? Code says False if state wrong

    # 2. Tx fail
    mock_registry_inst.get_service.return_value = {"state": ServiceState.FINISHED_REGISTRATION}
    mock_wallet.sign_and_send_transaction.return_value = (False, {})
    assert manager.deploy() is None

    # 3. Event missing (DeployService)
    mock_wallet.sign_and_send_transaction.return_value = (True, {})
    mock_registry_inst.extract_events.return_value = []
    assert manager.deploy() is None

    # 4. Multisig Missing
    mock_registry_inst.extract_events.return_value = [{"name": "DeployService"}]
    assert manager.deploy() is None


@patch("iwa.plugins.olas.service_manager.Config")
@patch("iwa.plugins.olas.service_manager.ServiceRegistryContract")
@patch("iwa.plugins.olas.service_manager.ServiceManagerContract")
def test_terminate(mock_sm_contract, mock_registry_contract, mock_config_cls, mock_wallet):
    """Test service termination."""
    mock_config_inst = mock_config_cls.return_value
    mock_olas_config = MagicMock()
    mock_olas_config.service_id = 123
    mock_olas_config.staking_contract_address = None  # Not staked
    mock_config_inst.plugins = {"olas": mock_olas_config}

    mock_registry_inst = mock_registry_contract.return_value
    mock_registry_inst.get_service.return_value = {"state": ServiceState.DEPLOYED}
    mock_registry_inst.extract_events.return_value = [{"name": "TerminateService"}]

    manager = ServiceManager(mock_wallet)

    success = manager.terminate()
    assert success is True

    # Failures
    # 1. Wrong state
    mock_registry_inst.get_service.return_value = {"state": ServiceState.PRE_REGISTRATION}
    assert manager.terminate() is False

    # 2. Staked
    mock_registry_inst.get_service.return_value = {"state": ServiceState.DEPLOYED}
    mock_olas_config.staking_contract_address = "0xStaked"
    assert manager.terminate() is False
    mock_olas_config.staking_contract_address = None

    # 3. Tx fail
    mock_wallet.sign_and_send_transaction.return_value = (False, {})
    assert manager.terminate() is False

    # 4. No event
    mock_wallet.sign_and_send_transaction.return_value = (True, {})
    mock_registry_inst.extract_events.return_value = []
    assert manager.terminate() is False


@patch("iwa.plugins.olas.service_manager.Config")
@patch("iwa.plugins.olas.service_manager.ServiceRegistryContract")
@patch("iwa.plugins.olas.service_manager.ServiceManagerContract")  # MUST mock specifically here
@patch("iwa.plugins.olas.service_manager.ERC20Contract")  # For checking balance
def test_stake(mock_erc20, mock_sm_contract, mock_registry_contract, mock_config_cls, mock_wallet):
    """Test service staking."""
    mock_config_inst = mock_config_cls.return_value
    mock_olas_config = MagicMock()
    mock_olas_config.service_id = 123
    mock_olas_config.chain_name = "gnosis"
    mock_config_inst.plugins = {"olas": mock_olas_config}

    mock_registry_inst = mock_registry_contract.return_value
    mock_registry_inst.get_service.return_value = {"state": ServiceState.DEPLOYED}

    manager = ServiceManager(mock_wallet)

    # Mock Staking Contract
    mock_staking = MagicMock()
    mock_staking.staking_token_address = "0xToken"
    mock_staking.address = "0xStaking"
    mock_staking.get_service_ids.return_value = 0  # Not full
    mock_staking.max_num_services = 10
    mock_staking.min_staking_deposit = 100
    mock_staking.extract_events.return_value = [{"name": "ServiceStaked"}]
    mock_staking.get_staking_state.return_value = StakingState.STAKED

    # Mock ERC20 balance check
    mock_erc20_inst = mock_erc20.return_value
    mock_erc20_inst.balance_of_wei.return_value = 200  # Enough balance

    success = manager.stake(mock_staking)
    assert success is True
    assert mock_olas_config.staking_contract_address == "0xStaking"

    # Failures
    # 1. State not deployed
    mock_registry_inst.get_service.return_value = {"state": ServiceState.PRE_REGISTRATION}
    assert manager.stake(mock_staking) is False

    # 2. Full
    mock_registry_inst.get_service.return_value = {"state": ServiceState.DEPLOYED}
    mock_staking.get_service_ids.return_value = 10
    assert manager.stake(mock_staking) is False
    mock_staking.get_service_ids.return_value = 0

    # 3. Not enough funds
    mock_erc20_inst.balance_of_wei.return_value = 50
    assert manager.stake(mock_staking) is False
    mock_erc20_inst.balance_of_wei.return_value = 200

    # 4. Approve fail
    mock_wallet.sign_and_send_transaction.return_value = (False, {})
    assert manager.stake(mock_staking) is False

    # 5. Stake fail
    # First tx (approve) success, second (stake) fail
    mock_wallet.sign_and_send_transaction.side_effect = [(True, {}), (False, {})]
    assert manager.stake(mock_staking) is False

    # 6. Event missing
    mock_wallet.sign_and_send_transaction.side_effect = [(True, {}), (True, {})]
    mock_staking.extract_events.return_value = []
    assert manager.stake(mock_staking) is False

    # 7. State check fail
    mock_wallet.sign_and_send_transaction.side_effect = [(True, {}), (True, {})]
    mock_staking.extract_events.return_value = [{"name": "ServiceStaked"}]
    mock_staking.get_staking_state.return_value = StakingState.NOT_STAKED
    assert manager.stake(mock_staking) is False
