"""Tests for ServiceManager."""

from unittest.mock import MagicMock, patch

import pytest

from iwa.core.models import StoredAccount
from iwa.core.wallet import Wallet
from iwa.plugins.olas.contracts.service import ServiceState
from iwa.plugins.olas.contracts.staking import StakingState
from iwa.plugins.olas.models import OlasConfig, Service
from iwa.plugins.olas.service_manager import ServiceManager

# Valid test addresses (checksummed)
TEST_MULTISIG_ADDR = "0x5555555555555555555555555555555555555555"
TEST_STAKING_ADDR = "0x6666666666666666666666666666666666666666"
TEST_AGENT_ADDR = "0x7777777777777777777777777777777777777777"
TEST_EXISTING_AGENT_ADDR = "0x8888888888888888888888888888888888888888"


@pytest.fixture
def mock_service():
    """Create a mock Service object."""
    service = MagicMock(spec=Service)
    service.service_name = "test_service"
    service.chain_name = "gnosis"
    service.service_id = 1
    service.agent_ids = [25]  # Default TRADER agent
    service.service_owner_address = "0x1234567890123456789012345678901234567890"
    service.agent_address = None
    service.multisig_address = None
    service.staking_contract_address = None
    service.token_address = "0xcE11e14225575945b8E6Dc0D4F2dD4C570f79d9f"  # OLAS token
    service.security_deposit = 50000000000000000000  # 50 OLAS
    service.key = "gnosis:1"
    return service


@pytest.fixture
def mock_olas_config(mock_service):
    """Create a mock OlasConfig object."""
    olas_config = MagicMock(spec=OlasConfig)
    olas_config.services = {"gnosis:1": mock_service}
    olas_config.get_service.return_value = mock_service
    return olas_config


@pytest.fixture
def mock_config(mock_olas_config):
    """Mock configuration fixture."""
    with patch(
        "iwa.plugins.olas.service_manager.base.Config"
    ) as mock:  # Patch the class used in service_manager
        instance = mock.return_value
        instance.plugins = {"olas": mock_olas_config}
        instance.save_config = MagicMock()
        yield instance


@pytest.fixture
def mock_wallet():
    """Mock wallet fixture."""
    wallet = MagicMock(spec=Wallet)
    wallet.master_account = MagicMock(spec=StoredAccount)
    wallet.master_account.address = "0x1234567890123456789012345678901234567890"
    wallet.key_storage = MagicMock()
    wallet.key_storage.get_account.return_value = None  # Default
    # Mock create_account which returns a StoredAccount or similar
    new_acc = MagicMock()
    new_acc.address = "0x0987654321098765432109876543210987654321"
    wallet.key_storage.create_account.return_value = new_acc
    # Mock transfer_service
    wallet.transfer_service = MagicMock()
    wallet.transfer_service.approve_erc20.return_value = True
    return wallet


@pytest.fixture
def mock_registry():
    """Mock service registry fixture."""
    with patch("iwa.plugins.olas.service_manager.base.ServiceRegistryContract") as mock:
        yield mock


@pytest.fixture
def mock_manager_contract():
    """Mock service manager contract fixture."""
    with patch("iwa.plugins.olas.service_manager.base.ServiceManagerContract") as mock:
        yield mock


@pytest.fixture
def mock_chain_interfaces():
    """Mock chain interfaces fixture."""
    with patch("iwa.plugins.olas.service_manager.base.ChainInterfaces") as mock:
        chain = MagicMock()
        # Use valid token address
        chain.chain.get_token_address.return_value = "0x1111111111111111111111111111111111111111"
        mock.return_value.get.return_value = chain
        yield mock


@pytest.fixture
def mock_erc20_contract():
    """Mock ERC20 contract fixture."""
    with patch("iwa.plugins.olas.service_manager.staking.ERC20Contract") as mock:
        yield mock


@pytest.fixture
def service_manager(
    mock_config,
    mock_wallet,
    mock_registry,
    mock_manager_contract,
    mock_chain_interfaces,
    mock_erc20_contract,
    mock_olas_config,
    mock_service,
):
    """ServiceManager fixture with mocked dependencies."""
    with patch("iwa.plugins.olas.service_manager.base.Config") as local_mock_config:
        instance = local_mock_config.return_value
        instance.plugins = {"olas": mock_olas_config}
        instance.save_config = MagicMock()

        sm = ServiceManager(mock_wallet)
        # Ensure service is properly set
        sm.service = mock_service
        sm.olas_config = mock_olas_config
        sm.global_config = instance
        yield sm


def test_init(service_manager):
    """Test initialization."""
    assert service_manager.registry is not None
    assert service_manager.manager is not None
    assert service_manager.service is not None
    assert service_manager.olas_config is not None


def test_get(service_manager):
    """Test get service."""
    service_manager.get()
    service_manager.registry.get_service.assert_called_with(1)


def test_create_success(service_manager, mock_wallet):
    """Test successful service creation."""
    mock_wallet.sign_and_send_transaction.return_value = (True, {"raw": "receipt"})
    service_manager.registry.extract_events.return_value = [
        {"name": "CreateService", "args": {"serviceId": 123}}
    ]

    service_id = service_manager.create(
        token_address_or_tag="0x1111111111111111111111111111111111111111"
    )

    assert service_id == 123
    service_manager.manager.prepare_create_tx.assert_called()
    mock_wallet.sign_and_send_transaction.assert_called()


def test_create_fail_tx(service_manager, mock_wallet):
    """Test failure when transaction fails."""
    mock_wallet.sign_and_send_transaction.return_value = (False, {})
    res = service_manager.create()
    assert res is None


def test_create_no_event(service_manager, mock_wallet):
    """Test failure when no event is emitted."""
    mock_wallet.sign_and_send_transaction.return_value = (True, {})
    service_manager.registry.extract_events.return_value = []

    with patch("iwa.plugins.olas.service_manager.staking.ERC20Contract"):  # Mock ERC20
        res = service_manager.create(
            token_address_or_tag="0x1111111111111111111111111111111111111111"
        )
        # create() finds no ID, logs error, returns None for service_id.
        assert res is None


def test_activate_registration_success(service_manager, mock_wallet):
    """Test successful activation."""
    service_manager.registry.get_service.return_value = {
        "state": ServiceState.PRE_REGISTRATION,
        "security_deposit": 50000000000000000000,
    }
    mock_wallet.sign_and_send_transaction.return_value = (True, {})
    service_manager.registry.extract_events.return_value = [{"name": "ActivateRegistration"}]

    # Mock balance/allowance for the new check
    mock_wallet.balance_service = MagicMock()
    mock_wallet.balance_service.get_erc20_balance_wei.return_value = 10**18
    mock_wallet.transfer_service.get_erc20_allowance.return_value = 10**20

    assert service_manager.activate_registration() is True


def test_activate_registration_wrong_state(service_manager):
    """Test activation fails in wrong state."""
    service_manager.registry.get_service.return_value = {
        "state": ServiceState.DEPLOYED,
        "security_deposit": 50000000000000000000,
    }
    assert service_manager.activate_registration() is False


def test_register_agent_success(service_manager, mock_wallet):
    """Test successful agent registration."""
    service_manager.registry.get_service.return_value = {
        "state": ServiceState.ACTIVE_REGISTRATION,
        "security_deposit": 50000000000000000000,
    }

    # create_account is already mocked
    mock_wallet.send.return_value = "0xMockTxHash"  # wallet.send returns tx_hash
    mock_wallet.sign_and_send_transaction.return_value = (True, {})
    service_manager.registry.extract_events.return_value = [{"name": "RegisterInstance"}]

    assert service_manager.register_agent() is True
    assert service_manager.service.agent_address == "0x0987654321098765432109876543210987654321"


def test_deploy_success(service_manager, mock_wallet):
    """Test successful deployment."""
    service_manager.registry.get_service.return_value = {
        "state": ServiceState.FINISHED_REGISTRATION
    }
    mock_wallet.sign_and_send_transaction.return_value = (True, {})
    service_manager.registry.extract_events.return_value = [
        {"name": "DeployService"},
        {"name": "CreateMultisigWithAgents", "args": {"multisig": TEST_MULTISIG_ADDR}},
    ]

    assert service_manager.deploy() == TEST_MULTISIG_ADDR
    assert service_manager.service.multisig_address == TEST_MULTISIG_ADDR


def test_terminate_success(service_manager, mock_wallet):
    """Test successful termination."""
    service_manager.registry.get_service.return_value = {
        "state": ServiceState.DEPLOYED,
        "security_deposit": 50000000000000000000,
    }
    # Not staked
    service_manager.service.staking_contract_address = None

    mock_wallet.sign_and_send_transaction.return_value = (True, {})
    service_manager.registry.extract_events.return_value = [{"name": "TerminateService"}]

    assert service_manager.terminate() is True


def test_unbond_success(service_manager, mock_wallet):
    """Test successful unbonding."""
    service_manager.registry.get_service.return_value = {
        "state": ServiceState.TERMINATED_BONDED,
        "security_deposit": 50000000000000000000,
    }

    mock_wallet.sign_and_send_transaction.return_value = (True, {})
    service_manager.registry.extract_events.return_value = [{"name": "OperatorUnbond"}]

    assert service_manager.unbond() is True


def test_stake_success(service_manager, mock_wallet):
    """Test successful staking."""
    staking_contract = MagicMock()
    staking_contract.staking_token_address = "0xcE11e14225575945b8E6Dc0D4F2dD4C570f79d9f"
    staking_contract.get_service_ids.return_value = []
    staking_contract.max_num_services = 10
    staking_contract.min_staking_deposit = 100
    staking_contract.address = TEST_STAKING_ADDR
    staking_contract.get_requirements.return_value = {
        "staking_token": "0xcE11e14225575945b8E6Dc0D4F2dD4C570f79d9f",  # OLAS token
        "min_staking_deposit": 50000000000000000000,
        "num_agent_instances": 1,
        "required_agent_bond": 50000000000000000000,  # 50 OLAS
    }

    service_manager.registry.get_service.return_value = {
        "state": ServiceState.DEPLOYED,
        "security_deposit": 50000000000000000000,
    }

    with patch("iwa.plugins.olas.service_manager.staking.ERC20Contract") as mock_erc20:
        mock_erc20.return_value.balance_of_wei.return_value = 100000000000000000000  # 100 OLAS

        mock_wallet.sign_and_send_transaction.return_value = (True, {})
        staking_contract.extract_events.return_value = [{"name": "ServiceStaked"}]
        staking_contract.get_staking_state.return_value = StakingState.STAKED

        # We need to make sure prepare_approve_tx is mocked ON THE REGISTRY INSTANCE
        service_manager.registry.prepare_approve_tx.return_value = {"to": "0xApprove"}

        assert service_manager.stake(staking_contract) is True
        assert service_manager.service.staking_contract_address == TEST_STAKING_ADDR


def test_unstake_success(service_manager, mock_wallet):
    """Test successful unstaking."""
    staking_contract = MagicMock()
    staking_contract.get_staking_state.return_value = StakingState.STAKED

    mock_wallet.sign_and_send_transaction.return_value = (True, {})
    staking_contract.extract_events.return_value = [{"name": "ServiceUnstaked"}]

    assert service_manager.unstake(staking_contract) is True
    assert service_manager.service.staking_contract_address is None


# --- Tests for register_agent with existing address ---


def test_register_agent_with_existing_address(service_manager, mock_wallet):
    """Test registering an existing agent address (no new account creation)."""
    service_manager.registry.get_service.return_value = {
        "state": ServiceState.ACTIVE_REGISTRATION,
        "security_deposit": 50000000000000000000,
    }

    mock_wallet.sign_and_send_transaction.return_value = (True, {})
    service_manager.registry.extract_events.return_value = [{"name": "RegisterInstance"}]

    existing_agent = TEST_EXISTING_AGENT_ADDR
    assert service_manager.register_agent(agent_address=existing_agent) is True
    assert service_manager.service.agent_address == TEST_EXISTING_AGENT_ADDR
    # Should NOT create a new account
    mock_wallet.key_storage.create_account.assert_not_called()
    # Should NOT fund the agent (only for new accounts)
    mock_wallet.send.assert_not_called()


def test_register_agent_creates_new_if_none(service_manager, mock_wallet):
    """Test that register_agent creates and funds a new agent when no address provided."""
    service_manager.registry.get_service.return_value = {
        "state": ServiceState.ACTIVE_REGISTRATION,
        "security_deposit": 50000000000000000000,
    }

    mock_wallet.send.return_value = "0xMockTxHash"  # wallet.send returns tx_hash
    mock_wallet.sign_and_send_transaction.return_value = (True, {})
    service_manager.registry.extract_events.return_value = [{"name": "RegisterInstance"}]

    assert service_manager.register_agent() is True
    # Should create a new account
    mock_wallet.key_storage.create_account.assert_called()
    # Should fund the new agent
    mock_wallet.send.assert_called()


def test_register_agent_fund_fails(service_manager, mock_wallet):
    """Test that register_agent fails when funding new agent fails."""
    service_manager.registry.get_service.return_value = {
        "state": ServiceState.ACTIVE_REGISTRATION,
        "security_deposit": 50000000000000000000,
    }

    mock_wallet.send.return_value = None  # Funding fails (wallet.send returns None on failure)

    assert service_manager.register_agent() is False


# --- Tests for spin_up ---


def test_spin_up_from_pre_registration_success(service_manager, mock_wallet):
    """Test full spin_up path from PRE_REGISTRATION to DEPLOYED."""
    # Mock state transitions - need to match actual calls in spin_up
    # The state after activate_registration should be ACTIVE_REGISTRATION
    state_sequence = [
        {
            "state": ServiceState.PRE_REGISTRATION,
            "security_deposit": 50000000000000000000,
        },  # spin_up initial
        {
            "state": ServiceState.PRE_REGISTRATION,
            "security_deposit": 50000000000000000000,
        },  # activate_registration check
        {
            "state": ServiceState.PRE_REGISTRATION,
            "security_deposit": 50000000000000000000,
        },  # activate_registration internal (get security deposit)
        {
            "state": ServiceState.ACTIVE_REGISTRATION,
            "security_deposit": 50000000000000000000,
        },  # spin_up verify after activate
        {
            "state": ServiceState.ACTIVE_REGISTRATION,
            "security_deposit": 50000000000000000000,
        },  # register_agent check
        {
            "state": ServiceState.ACTIVE_REGISTRATION,
            "security_deposit": 50000000000000000000,
        },  # register_agent internal
        {
            "state": ServiceState.FINISHED_REGISTRATION,
            "security_deposit": 50000000000000000000,
        },  # spin_up verify after register
        {
            "state": ServiceState.FINISHED_REGISTRATION,
            "security_deposit": 50000000000000000000,
        },  # deploy check
        {
            "state": ServiceState.DEPLOYED,
            "security_deposit": 50000000000000000000,
        },  # spin_up verify after deploy
        {
            "state": ServiceState.DEPLOYED,
            "security_deposit": 50000000000000000000,
        },  # final verification
    ]
    service_manager.registry.get_service.side_effect = state_sequence

    mock_wallet.send.return_value = "0xMockTxHash"  # wallet.send returns tx_hash
    mock_wallet.sign_and_send_transaction.return_value = (True, {})

    # Mock balance/allowance for activate_registration internal call
    mock_wallet.balance_service = MagicMock()
    mock_wallet.balance_service.get_erc20_balance_wei.return_value = 10**18
    mock_wallet.transfer_service.get_erc20_allowance.return_value = 10**20
    service_manager.registry.extract_events.side_effect = [
        [{"name": "ActivateRegistration"}],
        [{"name": "RegisterInstance"}],
        [
            {"name": "DeployService"},
            {"name": "CreateMultisigWithAgents", "args": {"multisig": TEST_MULTISIG_ADDR}},
        ],
    ]

    assert service_manager.spin_up() is True


def test_spin_up_from_active_registration(service_manager, mock_wallet):
    """Test spin_up resume from ACTIVE_REGISTRATION state."""
    # Need extra states because register_agent makes additional get_service calls
    state_sequence = [
        {
            "state": ServiceState.ACTIVE_REGISTRATION,
            "security_deposit": 50000000000000000000,
        },  # spin_up initial
        {
            "state": ServiceState.ACTIVE_REGISTRATION,
            "security_deposit": 50000000000000000000,
        },  # register_agent check
        {
            "state": ServiceState.ACTIVE_REGISTRATION,
            "security_deposit": 50000000000000000000,
        },  # register_agent internal
        {
            "state": ServiceState.FINISHED_REGISTRATION,
            "security_deposit": 50000000000000000000,
        },  # spin_up verify after register
        {
            "state": ServiceState.FINISHED_REGISTRATION,
            "security_deposit": 50000000000000000000,
        },  # deploy check
        {
            "state": ServiceState.DEPLOYED,
            "security_deposit": 50000000000000000000,
        },  # spin_up verify after deploy
        {
            "state": ServiceState.DEPLOYED,
            "security_deposit": 50000000000000000000,
        },  # final verification
    ]
    service_manager.registry.get_service.side_effect = state_sequence

    mock_wallet.send.return_value = "0xMockTxHash"  # wallet.send returns tx_hash
    mock_wallet.sign_and_send_transaction.return_value = (True, {})
    service_manager.registry.extract_events.side_effect = [
        [{"name": "RegisterInstance"}],
        [
            {"name": "DeployService"},
            {"name": "CreateMultisigWithAgents", "args": {"multisig": TEST_MULTISIG_ADDR}},
        ],
    ]

    assert service_manager.spin_up() is True


def test_spin_up_from_finished_registration(service_manager, mock_wallet):
    """Test spin_up resume from FINISHED_REGISTRATION state."""
    state_sequence = [
        {
            "state": ServiceState.FINISHED_REGISTRATION,
            "security_deposit": 50000000000000000000,
        },  # spin_up initial
        {
            "state": ServiceState.FINISHED_REGISTRATION,
            "security_deposit": 50000000000000000000,
        },  # deploy check
        {
            "state": ServiceState.DEPLOYED,
            "security_deposit": 50000000000000000000,
        },  # spin_up verify after deploy
        {
            "state": ServiceState.DEPLOYED,
            "security_deposit": 50000000000000000000,
        },  # final verification
    ]
    service_manager.registry.get_service.side_effect = state_sequence

    mock_wallet.sign_and_send_transaction.return_value = (True, {})
    service_manager.registry.extract_events.return_value = [
        {"name": "DeployService"},
        {"name": "CreateMultisigWithAgents", "args": {"multisig": TEST_MULTISIG_ADDR}},
    ]

    assert service_manager.spin_up() is True


def test_spin_up_already_deployed(service_manager, mock_wallet):
    """Test spin_up when already DEPLOYED (idempotent)."""
    service_manager.registry.get_service.return_value = {
        "state": ServiceState.DEPLOYED,
        "security_deposit": 50000000000000000000,
    }

    # Should succeed without any transactions
    assert service_manager.spin_up() is True
    mock_wallet.sign_and_send_transaction.assert_not_called()


def test_spin_up_with_staking(service_manager, mock_wallet):
    """Test spin_up with staking after deployment."""
    state_sequence = [
        {
            "state": ServiceState.DEPLOYED,
            "security_deposit": 50000000000000000000,
        },  # spin_up initial
        {
            "state": ServiceState.DEPLOYED,
            "security_deposit": 50000000000000000000,
        },  # stake internal check
        {
            "state": ServiceState.DEPLOYED,
            "security_deposit": 50000000000000000000,
        },  # final verification
    ]
    service_manager.registry.get_service.side_effect = state_sequence

    staking_contract = MagicMock()
    staking_contract.staking_token_address = "0xcE11e14225575945b8E6Dc0D4F2dD4C570f79d9f"
    staking_contract.get_service_ids.return_value = []
    staking_contract.max_num_services = 10
    staking_contract.min_staking_deposit = 100
    staking_contract.address = TEST_STAKING_ADDR
    staking_contract.get_requirements.return_value = {
        "staking_token": "0xcE11e14225575945b8E6Dc0D4F2dD4C570f79d9f",
        "min_staking_deposit": 50000000000000000000,
        "num_agent_instances": 1,
        "required_agent_bond": 50000000000000000000,  # 50 OLAS
    }

    with patch("iwa.plugins.olas.service_manager.staking.ERC20Contract") as mock_erc20:
        mock_erc20.return_value.balance_of_wei.return_value = 100000000000000000000  # 100 OLAS
        mock_wallet.sign_and_send_transaction.return_value = (True, {})
        staking_contract.extract_events.return_value = [{"name": "ServiceStaked"}]
        staking_contract.get_staking_state.return_value = StakingState.STAKED
        service_manager.registry.prepare_approve_tx.return_value = {"to": "0xApprove"}

        assert service_manager.spin_up(staking_contract=staking_contract) is True


def test_spin_up_activate_fails(service_manager, mock_wallet):
    """Test spin_up fails when activate_registration fails."""
    state_sequence = [
        {
            "state": ServiceState.PRE_REGISTRATION,
            "security_deposit": 50000000000000000000,
        },  # spin_up initial
        {
            "state": ServiceState.PRE_REGISTRATION,
            "security_deposit": 50000000000000000000,
        },  # activate_registration check
        {
            "state": ServiceState.PRE_REGISTRATION,
            "security_deposit": 50000000000000000000,
        },  # activate_registration internal (get security deposit)
    ]
    service_manager.registry.get_service.side_effect = state_sequence

    # Mock balance/allowance for activate_registration behavior
    mock_wallet.balance_service = MagicMock()
    mock_wallet.balance_service.get_erc20_balance_wei.return_value = 10**18
    mock_wallet.transfer_service.get_erc20_allowance.return_value = 10**20

    mock_wallet.sign_and_send_transaction.return_value = (False, {})

    assert service_manager.spin_up() is False


def test_spin_up_register_fails(service_manager, mock_wallet):
    """Test spin_up fails when register_agent fails."""
    state_sequence = [
        {
            "state": ServiceState.ACTIVE_REGISTRATION,
            "security_deposit": 50000000000000000000,
        },  # spin_up initial
        {
            "state": ServiceState.ACTIVE_REGISTRATION,
            "security_deposit": 50000000000000000000,
        },  # register_agent check
    ]
    service_manager.registry.get_service.side_effect = state_sequence

    # Funding fails
    mock_wallet.send.return_value = None  # wallet.send returns None on failure

    assert service_manager.spin_up() is False


def test_spin_up_deploy_fails(service_manager, mock_wallet):
    """Test spin_up fails when deploy fails."""
    state_sequence = [
        {
            "state": ServiceState.FINISHED_REGISTRATION,
            "security_deposit": 50000000000000000000,
        },  # spin_up initial
        {
            "state": ServiceState.FINISHED_REGISTRATION,
            "security_deposit": 50000000000000000000,
        },  # deploy check
    ]
    service_manager.registry.get_service.side_effect = state_sequence

    mock_wallet.sign_and_send_transaction.return_value = (False, {})

    assert service_manager.spin_up() is False


def test_spin_up_with_existing_agent(service_manager, mock_wallet):
    """Test spin_up uses provided agent address."""
    # Need extra states for internal get_service calls
    state_sequence = [
        {
            "state": ServiceState.ACTIVE_REGISTRATION,
            "security_deposit": 50000000000000000000,
        },  # spin_up initial
        {
            "state": ServiceState.ACTIVE_REGISTRATION,
            "security_deposit": 50000000000000000000,
        },  # register_agent check
        {
            "state": ServiceState.ACTIVE_REGISTRATION,
            "security_deposit": 50000000000000000000,
        },  # register_agent internal
        {
            "state": ServiceState.FINISHED_REGISTRATION,
            "security_deposit": 50000000000000000000,
        },  # spin_up verify after register
        {
            "state": ServiceState.FINISHED_REGISTRATION,
            "security_deposit": 50000000000000000000,
        },  # deploy check
        {
            "state": ServiceState.DEPLOYED,
            "security_deposit": 50000000000000000000,
        },  # spin_up verify after deploy
        {
            "state": ServiceState.DEPLOYED,
            "security_deposit": 50000000000000000000,
        },  # final verification
    ]
    service_manager.registry.get_service.side_effect = state_sequence

    mock_wallet.sign_and_send_transaction.return_value = (True, {})
    service_manager.registry.extract_events.side_effect = [
        [{"name": "RegisterInstance"}],
        [
            {"name": "DeployService"},
            {"name": "CreateMultisigWithAgents", "args": {"multisig": TEST_MULTISIG_ADDR}},
        ],
    ]

    existing_agent = TEST_EXISTING_AGENT_ADDR
    assert service_manager.spin_up(agent_address=existing_agent) is True
    # Verify agent address was not newly created
    mock_wallet.key_storage.create_account.assert_not_called()


# --- Tests for wind_down ---


def test_wind_down_from_deployed_success(service_manager, mock_wallet):
    """Test full wind_down path from DEPLOYED to PRE_REGISTRATION."""
    # Mock state transitions - need to account for all get_service calls:
    # 1. wind_down initial check
    # 2. wind_down refresh after unstake check
    # 3. terminate internal check
    # 4. wind_down verify after terminate
    # 5. unbond internal check
    # 6. wind_down verify after unbond
    # 7. final verification
    state_sequence = [
        {
            "state": ServiceState.DEPLOYED,
            "security_deposit": 50000000000000000000,
        },  # wind_down initial
        {
            "state": ServiceState.DEPLOYED,
            "security_deposit": 50000000000000000000,
        },  # terminate internal check
        {
            "state": ServiceState.TERMINATED_BONDED,
            "security_deposit": 50000000000000000000,
        },  # wind_down verify after terminate
        {
            "state": ServiceState.TERMINATED_BONDED,
            "security_deposit": 50000000000000000000,
        },  # unbond internal check
        {
            "state": ServiceState.PRE_REGISTRATION,
            "security_deposit": 50000000000000000000,
        },  # wind_down verify after unbond
        {
            "state": ServiceState.PRE_REGISTRATION,
            "security_deposit": 50000000000000000000,
        },  # final verification
    ]
    service_manager.registry.get_service.side_effect = state_sequence
    service_manager.service.staking_contract_address = None

    mock_wallet.sign_and_send_transaction.return_value = (True, {})
    service_manager.registry.extract_events.side_effect = [
        [{"name": "TerminateService"}],
        [{"name": "OperatorUnbond"}],
    ]

    assert service_manager.wind_down() is True


def test_wind_down_from_staked(service_manager, mock_wallet):
    """Test wind_down handles unstaking first."""
    state_sequence = [
        {
            "state": ServiceState.DEPLOYED,
            "security_deposit": 50000000000000000000,
        },  # wind_down initial
        {
            "state": ServiceState.DEPLOYED,
            "security_deposit": 50000000000000000000,
        },  # terminate internal check
        {
            "state": ServiceState.TERMINATED_BONDED,
            "security_deposit": 50000000000000000000,
        },  # wind_down verify after terminate
        {
            "state": ServiceState.TERMINATED_BONDED,
            "security_deposit": 50000000000000000000,
        },  # unbond internal check
        {
            "state": ServiceState.PRE_REGISTRATION,
            "security_deposit": 50000000000000000000,
        },  # wind_down verify after unbond
        {
            "state": ServiceState.PRE_REGISTRATION,
            "security_deposit": 50000000000000000000,
        },  # final verification
    ]
    service_manager.registry.get_service.side_effect = state_sequence
    service_manager.service.staking_contract_address = TEST_STAKING_ADDR

    staking_contract = MagicMock()
    staking_contract.get_staking_state.return_value = StakingState.STAKED

    mock_wallet.sign_and_send_transaction.return_value = (True, {})
    staking_contract.extract_events.return_value = [{"name": "ServiceUnstaked"}]
    service_manager.registry.extract_events.side_effect = [
        [{"name": "TerminateService"}],
        [{"name": "OperatorUnbond"}],
    ]

    assert service_manager.wind_down(staking_contract=staking_contract) is True


def test_wind_down_from_terminated(service_manager, mock_wallet):
    """Test wind_down resume from TERMINATED_BONDED state."""
    # When starting from TERMINATED_BONDED:
    # 1. wind_down initial check (line 586)
    # 2. wind_down refresh after unstake block (line 607) - always called
    # 3. unbond internal check (line 323)
    # 4. wind_down verify after unbond (line 633)
    # 5. final verification (line 642)
    state_sequence = [
        {
            "state": ServiceState.TERMINATED_BONDED,
            "security_deposit": 50000000000000000000,
        },  # wind_down initial
        {
            "state": ServiceState.TERMINATED_BONDED,
            "security_deposit": 50000000000000000000,
        },  # unbond internal check
        {
            "state": ServiceState.PRE_REGISTRATION,
            "security_deposit": 50000000000000000000,
        },  # wind_down verify after unbond
        {
            "state": ServiceState.PRE_REGISTRATION,
            "security_deposit": 50000000000000000000,
        },  # final verification
    ]
    service_manager.registry.get_service.side_effect = state_sequence

    mock_wallet.sign_and_send_transaction.return_value = (True, {})
    service_manager.registry.extract_events.return_value = [{"name": "OperatorUnbond"}]

    assert service_manager.wind_down() is True


def test_wind_down_already_pre_registration(service_manager, mock_wallet):
    """Test wind_down when already PRE_REGISTRATION (idempotent)."""
    service_manager.registry.get_service.return_value = {
        "state": ServiceState.PRE_REGISTRATION,
        "security_deposit": 50000000000000000000,
    }

    # Should succeed without any transactions
    assert service_manager.wind_down() is True
    mock_wallet.sign_and_send_transaction.assert_not_called()


def test_wind_down_staked_no_contract_provided(service_manager, mock_wallet):
    """Test wind_down fails when staked but no staking contract provided."""
    service_manager.registry.get_service.return_value = {
        "state": ServiceState.DEPLOYED,
        "security_deposit": 50000000000000000000,
    }
    service_manager.service.staking_contract_address = TEST_STAKING_ADDR

    # No staking_contract provided
    assert service_manager.wind_down() is False


def test_wind_down_unstake_fails(service_manager, mock_wallet):
    """Test wind_down fails when unstake fails."""
    service_manager.registry.get_service.return_value = {
        "state": ServiceState.DEPLOYED,
        "security_deposit": 50000000000000000000,
    }
    service_manager.service.staking_contract_address = TEST_STAKING_ADDR

    staking_contract = MagicMock()
    staking_contract.get_staking_state.return_value = StakingState.STAKED

    mock_wallet.sign_and_send_transaction.return_value = (False, {})

    assert service_manager.wind_down(staking_contract=staking_contract) is False


def test_wind_down_terminate_fails(service_manager, mock_wallet):
    """Test wind_down fails when terminate fails."""
    state_sequence = [
        {
            "state": ServiceState.DEPLOYED,
            "security_deposit": 50000000000000000000,
        },  # wind_down initial
        {
            "state": ServiceState.DEPLOYED,
            "security_deposit": 50000000000000000000,
        },  # wind_down refresh after unstake check
        {
            "state": ServiceState.DEPLOYED,
            "security_deposit": 50000000000000000000,
        },  # terminate internal check
    ]
    service_manager.registry.get_service.side_effect = state_sequence
    service_manager.service.staking_contract_address = None

    mock_wallet.sign_and_send_transaction.return_value = (False, {})

    assert service_manager.wind_down() is False


def test_wind_down_unbond_fails(service_manager, mock_wallet):
    """Test wind_down fails when unbond fails."""
    # When starting from TERMINATED_BONDED and unbond fails:
    # 1. wind_down initial check (line 586)
    # 2. wind_down refresh after unstake block (line 607) - always called
    # 3. unbond internal check (line 323)
    state_sequence = [
        {
            "state": ServiceState.TERMINATED_BONDED,
            "security_deposit": 50000000000000000000,
        },  # wind_down initial
        {
            "state": ServiceState.TERMINATED_BONDED,
            "security_deposit": 50000000000000000000,
        },  # wind_down refresh
        {
            "state": ServiceState.TERMINATED_BONDED,
            "security_deposit": 50000000000000000000,
        },  # unbond internal check
    ]
    service_manager.registry.get_service.side_effect = state_sequence

    mock_wallet.sign_and_send_transaction.return_value = (False, {})

    assert service_manager.wind_down() is False


# --- REGRESSION TESTS for activate_registration (Dec 2025 bug fix) ---
# These tests ensure the value parameter is ALWAYS set to security_deposit
# and that the master account is used as signer, preventing the regression
# where value=0 was incorrectly sent for token-based services.


def test_activate_registration_token_service_sends_security_deposit_as_value(
    service_manager, mock_wallet
):
    """REGRESSION TEST: Token services MUST send security_deposit as msg.value.

    Bug context: A previous change incorrectly set value=0 for token-based services,
    but the ServiceManager contract REQUIRES msg.value == security_deposit even for
    token services (where security_deposit is typically 1 wei).
    """
    security_deposit = 1  # 1 wei for token services
    service_manager.service.token_address = "0xcE11e14225575945b8E6Dc0D4F2dD4C570f79d9f"  # OLAS

    service_manager.registry.get_service.return_value = {
        "state": ServiceState.PRE_REGISTRATION,
        "security_deposit": security_deposit,
    }
    mock_wallet.sign_and_send_transaction.return_value = (True, {})
    service_manager.registry.extract_events.return_value = [{"name": "ActivateRegistration"}]

    # Mock balance check to pass
    mock_wallet.balance_service = MagicMock()
    mock_wallet.balance_service.get_erc20_balance_wei.return_value = 10**18  # Plenty of balance

    # Mock allowance to pass check (return an int)
    mock_wallet.transfer_service.get_erc20_allowance.return_value = 10**20  # Plenty of allowance

    service_manager.activate_registration()

    # Verify the CRITICAL parameter - value MUST equal security_deposit
    call_args = service_manager.manager.prepare_activate_registration_tx.call_args
    assert call_args is not None, "prepare_activate_registration_tx was not called"
    assert call_args.kwargs.get("value") == security_deposit, (
        f"REGRESSION: value should be {security_deposit} (security_deposit), "
        f"got {call_args.kwargs.get('value')}"
    )


def test_activate_registration_native_service_sends_security_deposit_as_value(
    service_manager, mock_wallet
):
    """REGRESSION TEST: Native services MUST send security_deposit as msg.value."""
    security_deposit = 50000000000000000000  # 50 xDAI for native services
    service_manager.service.token_address = None  # Native service

    service_manager.registry.get_service.return_value = {
        "state": ServiceState.PRE_REGISTRATION,
        "security_deposit": security_deposit,
    }
    service_manager.registry.get_token.return_value = "0x0000000000000000000000000000000000000000"
    mock_wallet.sign_and_send_transaction.return_value = (True, {})
    service_manager.registry.extract_events.return_value = [{"name": "ActivateRegistration"}]

    # Mock balance/allowance
    mock_wallet.balance_service = MagicMock()
    mock_wallet.balance_service.get_erc20_balance_wei.return_value = 10**18
    mock_wallet.transfer_service.get_erc20_allowance.return_value = 10**20

    service_manager.activate_registration()

    # Verify the CRITICAL parameter - value MUST equal security_deposit
    call_args = service_manager.manager.prepare_activate_registration_tx.call_args
    assert call_args is not None, "prepare_activate_registration_tx was not called"
    assert call_args.kwargs.get("value") == security_deposit, (
        f"REGRESSION: value should be {security_deposit} (security_deposit), "
        f"got {call_args.kwargs.get('value')}"
    )


def test_activate_registration_uses_master_account_as_from_address(service_manager, mock_wallet):
    """REGRESSION TEST: activate_registration MUST use master_account.address as from_address.

    Bug context: A previous change used service_owner_address instead of master_account,
    which could fail if they differ or if master_account is the only funded account.
    """
    master_address = mock_wallet.master_account.address

    service_manager.registry.get_service.return_value = {
        "state": ServiceState.PRE_REGISTRATION,
        "security_deposit": 1,
    }
    mock_wallet.sign_and_send_transaction.return_value = (True, {})
    service_manager.registry.extract_events.return_value = [{"name": "ActivateRegistration"}]

    # Mock balance/allowance
    mock_wallet.balance_service = MagicMock()
    mock_wallet.transfer_service = MagicMock()
    mock_wallet.balance_service.get_erc20_balance_wei.return_value = 10**18
    mock_wallet.transfer_service.get_erc20_allowance.return_value = 10**20

    service_manager.activate_registration()

    # Verify master_account is used as from_address
    call_args = service_manager.manager.prepare_activate_registration_tx.call_args
    assert call_args is not None, "prepare_activate_registration_tx was not called"
    assert call_args.kwargs.get("from_address") == master_address, (
        f"REGRESSION: from_address should be master_account.address ({master_address}), "
        f"got {call_args.kwargs.get('from_address')}"
    )


def test_activate_registration_uses_master_account_as_signer(service_manager, mock_wallet):
    """REGRESSION TEST: activate_registration MUST use master_account.address as signer.

    Bug context: A previous change used service_owner_address as signer,
    which could fail transaction signing.
    """
    master_address = mock_wallet.master_account.address

    service_manager.registry.get_service.return_value = {
        "state": ServiceState.PRE_REGISTRATION,
        "security_deposit": 1,
    }
    mock_wallet.sign_and_send_transaction.return_value = (True, {})
    service_manager.registry.extract_events.return_value = [{"name": "ActivateRegistration"}]

    # Mock balance/allowance
    mock_wallet.balance_service = MagicMock()
    mock_wallet.transfer_service = MagicMock()
    mock_wallet.balance_service.get_erc20_balance_wei.return_value = 10**18
    mock_wallet.transfer_service.get_erc20_allowance.return_value = 10**20

    service_manager.activate_registration()

    # Verify master_account is used as signer
    call_args = mock_wallet.sign_and_send_transaction.call_args
    assert call_args is not None, "sign_and_send_transaction was not called"
    assert call_args.kwargs.get("signer_address_or_tag") == master_address, (
        f"REGRESSION: signer should be master_account.address ({master_address}), "
        f"got {call_args.kwargs.get('signer_address_or_tag')}"
    )


def test_activate_registration_token_service_approves_token_utility(service_manager, mock_wallet):
    """TEST: Token services should trigger TokenUtility approval when allowance is low."""
    service_manager.service.token_address = "0xcE11e14225575945b8E6Dc0D4F2dD4C570f79d9f"  # OLAS

    service_manager.registry.get_service.return_value = {
        "state": ServiceState.PRE_REGISTRATION,
        "security_deposit": 1,
    }
    mock_wallet.sign_and_send_transaction.return_value = (True, {})
    service_manager.registry.extract_events.return_value = [{"name": "ActivateRegistration"}]

    # Mock low allowance to trigger approval
    mock_wallet.balance_service = MagicMock()
    mock_wallet.balance_service.get_erc20_balance_wei.return_value = 10**18
    mock_wallet.transfer_service.get_erc20_allowance.return_value = 0  # Low allowance
    mock_wallet.transfer_service.approve_erc20.return_value = True

    service_manager.activate_registration()

    # Verify approval was called
    mock_wallet.transfer_service.approve_erc20.assert_called()
