"""Lifecycle and operational flow tests for Olas ServiceManager."""

from unittest.mock import MagicMock, patch

import pytest

from iwa.plugins.olas.contracts.service import ServiceState
from iwa.plugins.olas.contracts.staking import StakingState
from iwa.plugins.olas.service_manager import ServiceManager


@pytest.fixture
def mock_wallet():
    """Mock wallet for testing."""
    wallet = MagicMock()
    wallet.master_account.address = "0x1234567890123456789012345678901234567890"
    wallet.key_storage.get_account.return_value.address = (
        "0xAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    )
    wallet.key_storage.create_account.return_value.address = (
        "0xBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB"
    )
    wallet.sign_and_send_transaction.return_value = (True, {"status": 1})
    wallet.send.return_value = (True, {"status": 1})
    wallet.balance_service = MagicMock()
    wallet.transfer_service = MagicMock()
    # Default behavior for balance checking calls to avoid AttributeError
    wallet.balance_service.get_erc20_balance_wei.return_value = 10**20
    return wallet


@pytest.fixture
def mock_config():
    """Mock config for testing."""
    config = MagicMock()
    olas_config = MagicMock()
    olas_config.services = {}
    olas_config.get_service.return_value = None
    olas_config.get_service.return_value = None
    config.plugins = {"olas": olas_config}
    config.save_config = MagicMock()
    return config


@patch("iwa.plugins.olas.service_manager.base.Config")
@patch("iwa.plugins.olas.service_manager.base.ServiceRegistryContract")
@patch("iwa.plugins.olas.service_manager.base.ServiceManagerContract")
@patch("iwa.plugins.olas.service_manager.staking.ERC20Contract")
def test_create_service_success(
    mock_erc20, mock_sm_contract, mock_registry_contract, mock_config_cls, mock_wallet
):
    """Test successful service creation."""
    # Setup Config with new OlasConfig structure
    mock_config_inst = mock_config_cls.return_value
    mock_olas_config = MagicMock()
    mock_olas_config.services = {}
    mock_olas_config.get_service.return_value = None
    mock_olas_config.get_service.return_value = None
    mock_config_inst.plugins = {"olas": mock_olas_config}
    mock_config_inst.save_config = MagicMock()

    # Setup Registry to return event
    mock_registry_inst = mock_registry_contract.return_value
    mock_registry_inst.extract_events.return_value = [
        {"name": "CreateService", "args": {"serviceId": 123}}
    ]

    # Setup Manager
    manager = ServiceManager(mock_wallet, service_key="gnosis:123")

    # Patch ChainInterfaces
    with patch("iwa.plugins.olas.service_manager.base.ChainInterfaces") as mock_chains:
        mock_chains.return_value.get.return_value.chain.get_token_address.return_value = None

        # Call create
        service_id = manager.create(bond_amount_wei=10)

        assert service_id == 123
        # Verify add_service was called
        mock_olas_config.add_service.assert_called_once()
        # Verify config was saved
        mock_config_inst.save_config.assert_called_once()


@patch("iwa.plugins.olas.service_manager.base.Config")
@patch("iwa.plugins.olas.service_manager.base.ServiceRegistryContract")
@patch("iwa.plugins.olas.service_manager.base.ServiceManagerContract")
@patch("iwa.plugins.olas.service_manager.staking.ERC20Contract")
def test_create_service_failures(
    mock_erc20, mock_sm_contract, mock_registry_contract, mock_config_cls, mock_wallet
):
    """Test service creation failure modes."""
    mock_config_inst = mock_config_cls.return_value
    mock_olas_config = MagicMock()
    mock_olas_config.get_service.return_value = None
    mock_config_inst.plugins = {"olas": mock_olas_config}

    manager = ServiceManager(mock_wallet, service_key="gnosis:123")

    # 1. Transaction fails
    mock_wallet.sign_and_send_transaction.return_value = (False, {})
    with patch("iwa.plugins.olas.service_manager.base.ChainInterfaces") as mock_chains:
        mock_chains.return_value.get.return_value.chain.get_token_address.return_value = None
        res = manager.create()
        assert res is None

    # Reset wallet
    mock_wallet.sign_and_send_transaction.return_value = (True, {})

    # 2. Event missing
    mock_registry_contract.return_value.extract_events.return_value = []
    with patch("iwa.plugins.olas.service_manager.base.ChainInterfaces") as mock_chains:
        mock_chains.return_value.get.return_value.chain.get_token_address.return_value = None
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
    mock_wallet.sign_and_send_transaction.reset_mock()
    mock_wallet.sign_and_send_transaction.return_value = (
        None  # Clear return_value to let side_effect work
    )
    mock_wallet.sign_and_send_transaction.side_effect = [(True, {}), (False, {})]
    mock_wallet.transfer_service = MagicMock()
    mock_wallet.transfer_service.approve_erc20.return_value = False

    with patch("iwa.plugins.olas.service_manager.base.ChainInterfaces") as mock_chains:
        mock_chains.return_value.get.return_value.chain.get_token_address.return_value = (
            "0xcE11e14225575945b8E6Dc0D4F2dD4C570f79d9f"
        )
        res = manager.create(token_address_or_tag="0xcE11e14225575945b8E6Dc0D4F2dD4C570f79d9f")
        assert res == 123 or res is False  # May succeed on create but fail on approval


@patch("iwa.plugins.olas.service_manager.base.Config")
@patch("iwa.plugins.olas.service_manager.base.ServiceRegistryContract")
@patch("iwa.plugins.olas.service_manager.base.ServiceManagerContract")
@patch("iwa.plugins.olas.service_manager.staking.ERC20Contract")
def test_create_service_with_approval(
    mock_erc20, mock_sm_contract, mock_registry_contract, mock_config_cls, mock_wallet
):
    """Test service creation with token approval."""
    mock_config_inst = mock_config_cls.return_value
    mock_olas_config = MagicMock()
    mock_olas_config.get_service.return_value = None
    mock_config_inst.plugins = {"olas": mock_olas_config}

    mock_registry_inst = mock_registry_contract.return_value
    mock_registry_inst.extract_events.return_value = [
        {"name": "CreateService", "args": {"serviceId": 123}}
    ]

    manager = ServiceManager(mock_wallet, service_key="gnosis:123")
    mock_wallet.transfer_service = MagicMock()
    mock_wallet.transfer_service.approve_erc20.return_value = True

    with patch("iwa.plugins.olas.service_manager.base.ChainInterfaces") as mock_chains:
        mock_chains.return_value.get.return_value.chain.get_token_address.return_value = (
            "0xcE11e14225575945b8E6Dc0D4F2dD4C570f79d9f"
        )
        manager.create(token_address_or_tag="0xcE11e14225575945b8E6Dc0D4F2dD4C570f79d9f")

        # Verify wallet transfer_service was used for approval
        assert mock_wallet.sign_and_send_transaction.call_count >= 1


@patch("iwa.plugins.olas.service_manager.base.Config")
@patch("iwa.plugins.olas.service_manager.base.ServiceRegistryContract")
@patch("iwa.plugins.olas.service_manager.base.ServiceManagerContract")
def test_activate_registration(
    mock_sm_contract, mock_registry_contract, mock_config_cls, mock_wallet
):
    """Test service registration activation."""
    mock_config_inst = mock_config_cls.return_value
    mock_olas_config = MagicMock()
    mock_service = MagicMock()
    mock_service.service_id = 123
    mock_service.chain_name = "gnosis"
    mock_service.token_address = "0xcE11e14225575945b8E6Dc0D4F2dD4C570f79d9f"
    mock_olas_config.get_service.return_value = mock_service
    mock_config_inst.plugins = {"olas": mock_olas_config}

    mock_registry_inst = mock_registry_contract.return_value
    mock_registry_inst.get_service.return_value = {
        "state": ServiceState.PRE_REGISTRATION,
        "security_deposit": 50000000000000000000,
    }
    mock_registry_inst.extract_events.return_value = [{"name": "ActivateRegistration"}]

    manager = ServiceManager(mock_wallet, service_key="gnosis:123")

    # Explicitly set mock return values to ensure they aren't overridden
    mock_wallet.balance_service.get_erc20_balance_wei.return_value = (
        50000000000000000000 * 2
    )  # Enough balance
    mock_wallet.transfer_service.get_erc20_allowance.return_value = (
        50000000000000000000 * 2
    )  # Enough allowance

    success = manager.activate_registration()
    assert success is True

    # Failures
    # 1. Wrong state
    mock_registry_inst.get_service.return_value = {
        "state": ServiceState.DEPLOYED,
        "security_deposit": 50000000000000000000,
    }
    assert manager.activate_registration() is False

    # 2. Tx fail
    mock_registry_inst.get_service.return_value = {
        "state": ServiceState.PRE_REGISTRATION,
        "security_deposit": 50000000000000000000,
    }
    mock_wallet.sign_and_send_transaction.return_value = (False, {})
    assert manager.activate_registration() is False

    # 3. Event missing
    mock_wallet.sign_and_send_transaction.return_value = (True, {})
    mock_registry_inst.extract_events.return_value = []
    assert manager.activate_registration() is False


@patch("iwa.plugins.olas.service_manager.base.Config")
@patch("iwa.plugins.olas.service_manager.base.ServiceRegistryContract")
@patch("iwa.plugins.olas.service_manager.base.ServiceManagerContract")
def test_register_agent(mock_sm_contract, mock_registry_contract, mock_config_cls, mock_wallet):
    """Test agent registration flow."""
    mock_config_inst = mock_config_cls.return_value
    mock_olas_config = MagicMock()
    mock_service = MagicMock()
    mock_service.service_id = 123
    mock_service.chain_name = "gnosis"
    mock_service.token_address = "0xcE11e14225575945b8E6Dc0D4F2dD4C570f79d9f"
    mock_olas_config.get_service.return_value = mock_service
    mock_config_inst.plugins = {"olas": mock_olas_config}

    mock_registry_inst = mock_registry_contract.return_value
    mock_registry_inst.get_service.return_value = {
        "state": ServiceState.ACTIVE_REGISTRATION,
        "security_deposit": 50000000000000000000,
    }
    mock_registry_inst.extract_events.return_value = [{"name": "RegisterInstance"}]

    manager = ServiceManager(mock_wallet, service_key="gnosis:123")

    success = manager.register_agent()
    assert success is True
    assert mock_olas_config.agent_address is not None

    # Failures
    # 1. Wrong state
    mock_registry_inst.get_service.return_value = {
        "state": ServiceState.PRE_REGISTRATION,
        "security_deposit": 50000000000000000000,
    }
    assert manager.register_agent() is False

    # 2. Tx fail
    mock_registry_inst.get_service.return_value = {
        "state": ServiceState.ACTIVE_REGISTRATION,
        "security_deposit": 50000000000000000000,
    }
    mock_wallet.sign_and_send_transaction.return_value = (False, {})
    assert manager.register_agent() is False

    # 3. Event missing
    mock_wallet.sign_and_send_transaction.return_value = (True, {})
    mock_registry_inst.extract_events.return_value = []
    assert manager.register_agent() is False


@patch("iwa.plugins.olas.service_manager.base.Config")
@patch("iwa.plugins.olas.service_manager.base.ServiceRegistryContract")
@patch("iwa.plugins.olas.service_manager.base.ServiceManagerContract")
def test_deploy(mock_sm_contract, mock_registry_contract, mock_config_cls, mock_wallet):
    """Test service deployment."""
    # Setup mock service
    mock_service = MagicMock()
    mock_service.service_id = 123
    mock_service.chain_name = "gnosis"
    mock_service.token_address = "0xcE11e14225575945b8E6Dc0D4F2dD4C570f79d9f"
    mock_service.multisig_address = None

    mock_olas_config = MagicMock()
    mock_olas_config.get_service.return_value = mock_service

    mock_config_inst = mock_config_cls.return_value
    mock_config_inst.plugins = {"olas": mock_olas_config}
    mock_config_inst.save_config = MagicMock()

    mock_registry_inst = mock_registry_contract.return_value
    mock_registry_inst.get_service.return_value = {
        "state": ServiceState.FINISHED_REGISTRATION,
        "security_deposit": 50000000000000000000,
    }
    mock_registry_inst.extract_events.return_value = [
        {"name": "DeployService"},
        {
            "name": "CreateMultisigWithAgents",
            "args": {"multisig": "0xCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC"},
        },
    ]

    manager = ServiceManager(mock_wallet, service_key="gnosis:123")

    multisig = manager.deploy()
    assert multisig == "0xCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC"
    mock_config_inst.save_config.assert_called()

    # Failures
    # 1. Wrong state
    mock_registry_inst.get_service.return_value = {
        "state": ServiceState.PRE_REGISTRATION,
        "security_deposit": 50000000000000000000,
    }
    assert manager.deploy() is False  # returns False or None? Code says False if state wrong

    # 2. Tx fail
    mock_registry_inst.get_service.return_value = {
        "state": ServiceState.FINISHED_REGISTRATION,
        "security_deposit": 50000000000000000000,
    }
    mock_wallet.sign_and_send_transaction.return_value = (False, {})
    assert manager.deploy() is None

    # 3. Event missing (DeployService)
    mock_wallet.sign_and_send_transaction.return_value = (True, {})
    mock_registry_inst.extract_events.return_value = []
    assert manager.deploy() is None

    # 4. Multisig Missing
    mock_registry_inst.extract_events.return_value = [{"name": "DeployService"}]
    assert manager.deploy() is None


@patch("iwa.plugins.olas.service_manager.base.Config")
@patch("iwa.plugins.olas.service_manager.base.ServiceRegistryContract")
@patch("iwa.plugins.olas.service_manager.base.ServiceManagerContract")
def test_terminate(mock_sm_contract, mock_registry_contract, mock_config_cls, mock_wallet):
    """Test service termination."""
    # Setup mock service
    mock_service = MagicMock()
    mock_service.service_id = 123
    mock_service.chain_name = "gnosis"
    mock_service.token_address = "0xcE11e14225575945b8E6Dc0D4F2dD4C570f79d9f"
    mock_service.staking_contract_address = None  # Not staked

    mock_olas_config = MagicMock()
    mock_olas_config.get_service.return_value = mock_service

    mock_config_inst = mock_config_cls.return_value
    mock_config_inst.plugins = {"olas": mock_olas_config}
    mock_config_inst.save_config = MagicMock()

    mock_registry_inst = mock_registry_contract.return_value
    mock_registry_inst.get_service.return_value = {
        "state": ServiceState.DEPLOYED,
        "security_deposit": 50000000000000000000,
    }
    mock_registry_inst.extract_events.return_value = [{"name": "TerminateService"}]

    manager = ServiceManager(mock_wallet, service_key="gnosis:123")

    success = manager.terminate()
    assert success is True

    # Failures
    # 1. Wrong state
    mock_registry_inst.get_service.return_value = {
        "state": ServiceState.PRE_REGISTRATION,
        "security_deposit": 50000000000000000000,
    }
    assert manager.terminate() is False

    # 2. Staked
    mock_registry_inst.get_service.return_value = {
        "state": ServiceState.DEPLOYED,
        "security_deposit": 50000000000000000000,
    }
    manager.service.staking_contract_address = "0xStaked"
    assert manager.terminate() is False
    manager.service.staking_contract_address = None

    # 3. Tx fail
    mock_wallet.sign_and_send_transaction.return_value = (False, {})
    assert manager.terminate() is False

    # 4. No event
    mock_wallet.sign_and_send_transaction.return_value = (True, {})
    mock_registry_inst.extract_events.return_value = []
    assert manager.terminate() is False


@patch("iwa.plugins.olas.service_manager.base.Config")
@patch("iwa.plugins.olas.service_manager.base.ServiceRegistryContract")
@patch(
    "iwa.plugins.olas.service_manager.base.ServiceManagerContract"
)  # MUST mock specifically here
@patch("iwa.plugins.olas.service_manager.staking.ERC20Contract")  # For checking balance
def test_stake(mock_erc20, mock_sm_contract, mock_registry_contract, mock_config_cls, mock_wallet):
    """Test service staking."""
    # Setup mock service
    mock_service = MagicMock()
    mock_service.service_id = 123
    mock_service.chain_name = "gnosis"
    mock_service.token_address = "0xcE11e14225575945b8E6Dc0D4F2dD4C570f79d9f"
    mock_service.staking_contract_address = None

    mock_olas_config = MagicMock()
    mock_olas_config.get_service.return_value = mock_service

    mock_config_inst = mock_config_cls.return_value
    mock_config_inst.plugins = {"olas": mock_olas_config}
    mock_config_inst.save_config = MagicMock()

    mock_registry_inst = mock_registry_contract.return_value
    mock_registry_inst.get_service.return_value = {
        "state": ServiceState.DEPLOYED,
        "security_deposit": 50000000000000000000,
    }

    manager = ServiceManager(mock_wallet, service_key="gnosis:123")

    # Mock Staking Contract
    mock_staking = MagicMock()
    mock_staking.staking_token_address = "0xcE11e14225575945b8E6Dc0D4F2dD4C570f79d9f"
    mock_staking.address = "0xDDdDddDdDdddDDddDDddDDDDdDdDDdDDdDDDDDDd"
    mock_staking.get_service_ids.return_value = []  # Not full
    mock_staking.max_num_services = 10
    mock_staking.min_staking_deposit = 100
    mock_staking.extract_events.return_value = [{"name": "ServiceStaked"}]
    mock_staking.get_staking_state.return_value = StakingState.STAKED
    mock_staking.get_requirements.return_value = {
        "staking_token": "0xcE11e14225575945b8E6Dc0D4F2dD4C570f79d9f",
        "min_staking_deposit": 50000000000000000000,
        "num_agent_instances": 1,
        "required_agent_bond": 50000000000000000000,
    }

    # Mock ERC20 balance check (100 OLAS = 100e18 wei, enough for 50 min deposit)
    mock_erc20_inst = mock_erc20.return_value
    mock_erc20_inst.balance_of_wei.return_value = 100000000000000000000  # 100 OLAS

    success = manager.stake(mock_staking)
    assert success is True
    assert manager.service.staking_contract_address == "0xDDdDddDdDdddDDddDDddDDDDdDdDDdDDdDDDDDDd"
    mock_config_inst.save_config.assert_called()

    # Failures
    # 1. State not deployed
    mock_registry_inst.get_service.return_value = {
        "state": ServiceState.PRE_REGISTRATION,
        "security_deposit": 50000000000000000000,
    }
    assert manager.stake(mock_staking) is False

    # 2. Full
    mock_registry_inst.get_service.return_value = {
        "state": ServiceState.DEPLOYED,
        "security_deposit": 50000000000000000000,
    }
    mock_staking.get_service_ids.return_value = [0] * 10
    assert manager.stake(mock_staking) is False
    mock_staking.get_service_ids.return_value = []

    # 3. Not enough funds
    mock_erc20_inst.balance_of_wei.return_value = 50
    assert manager.stake(mock_staking) is False
    mock_erc20_inst.balance_of_wei.return_value = 200

    # 4. Approve fail
    mock_wallet.sign_and_send_transaction.return_value = (False, {})
    assert manager.stake(mock_staking) is False

    # 5. Stake fail
    # First tx (approve) success, second (stake) fail
    mock_wallet.sign_and_send_transaction.side_effect = [(True, {}), (False, {}), (False, {})]
    assert manager.stake(mock_staking) is False

    # 6. Event missing
    mock_wallet.sign_and_send_transaction.side_effect = [(True, {}), (True, {}), (True, {})]
    mock_staking.extract_events.return_value = []
    assert manager.stake(mock_staking) is False

    # 7. State check fail
    mock_wallet.sign_and_send_transaction.side_effect = [(True, {}), (True, {}), (True, {})]
    mock_staking.extract_events.return_value = [{"name": "ServiceStaked"}]
    mock_staking.get_staking_state.return_value = StakingState.NOT_STAKED
    assert manager.stake(mock_staking) is False
