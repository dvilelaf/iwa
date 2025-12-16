"""Tests for ServiceManager."""

from unittest.mock import MagicMock, patch

import pytest

from iwa.core.models import StoredAccount
from iwa.core.wallet import Wallet
from iwa.plugins.olas.contracts.service import ServiceState
from iwa.plugins.olas.contracts.staking import StakingState
from iwa.plugins.olas.service_manager import ServiceManager


@pytest.fixture
def mock_config():
    """Mock configuration fixture."""
    with patch(
        "iwa.plugins.olas.service_manager.Config"
    ) as mock:  # Patch the class used in service_manager
        # Since service_manager calls Config(), and Config is singleton
        instance = mock.return_value

        # Mock OlasConfig structure as expected by service_manager.py
        olas_config = MagicMock()
        # Ensure services is a MagicMock but attributes are values
        services_mock = MagicMock()
        services_mock.service_id = 1
        olas_config.services = services_mock

        olas_config.chain_name = "gnosis"
        olas_config.service_id = 1
        olas_config.agent_address = None
        olas_config.multisig_address = None
        olas_config.staking_contract_address = None

        instance.plugins = {"olas": olas_config}

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
    return wallet


@pytest.fixture
def mock_registry():
    """Mock service registry fixture."""
    with patch("iwa.plugins.olas.service_manager.ServiceRegistryContract") as mock:
        yield mock


@pytest.fixture
def mock_manager_contract():
    """Mock service manager contract fixture."""
    with patch("iwa.plugins.olas.service_manager.ServiceManagerContract") as mock:
        yield mock


@pytest.fixture
def mock_chain_interfaces():
    """Mock chain interfaces fixture."""
    with patch("iwa.plugins.olas.service_manager.ChainInterfaces") as mock:
        chain = MagicMock()
        # Use valid token address
        chain.chain.get_token_address.return_value = "0x1111111111111111111111111111111111111111"
        mock.return_value.get.return_value = chain
        yield mock


@pytest.fixture
def mock_erc20_contract():
    """Mock ERC20 contract fixture."""
    with patch("iwa.plugins.olas.service_manager.ERC20Contract") as mock:
        yield mock


@pytest.fixture
def service_manager(
    mock_config,
    mock_wallet,
    mock_registry,
    mock_manager_contract,
    mock_chain_interfaces,
    mock_erc20_contract,
):
    """ServiceManager fixture with mocked dependencies."""
    # Ensure Config() returns our mock
    # Config is imported in service_manager.
    # We patched iwa.core.models.Config but service_manager imports it.
    # Because of how imports work, if service_manager did `from iwa.core.models import Config`,
    # we need to patch specifically where it is used OR patch before import if generic.
    # But pytest patch usually handles `target` as where it is looked up.
    # Since we patched `iwa.core.models.Config`, and `service_manager.py` imports `Config` from there,
    # `sys.modules["iwa.core.models"].Config` is the mock.
    # However, if `service_manager` was already imported, it holds a reference to the old Config class.
    # We might need to patch `iwa.plugins.olas.service_manager.Config`.

    with patch("iwa.plugins.olas.service_manager.Config") as local_mock_config:
        # replicate structure
        instance = local_mock_config.return_value
        instance.plugins = {"olas": mock_config.return_value.plugins["olas"]}

        sm = ServiceManager(mock_wallet)
        yield sm


def test_init(service_manager):
    """Test initialization."""
    assert service_manager.registry is not None
    assert service_manager.manager is not None
    assert service_manager.config is not None


def test_get(service_manager):
    """Test get service."""
    # Explicitly configure the mock for this test to avoid fixture complexity issues
    services_mock = MagicMock()
    services_mock.service_id = 1
    service_manager.services = services_mock

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

    with patch("iwa.plugins.olas.service_manager.ERC20Contract"):  # Mock ERC20
        res = service_manager.create(
            token_address_or_tag="0x1111111111111111111111111111111111111111"
        )
        # create() finds no ID, logs error, returns None for service_id.
        assert res is None


def test_activate_registration_success(service_manager, mock_wallet):
    """Test successful activation."""
    service_manager.registry.get_service.return_value = {"state": ServiceState.PRE_REGISTRATION}
    mock_wallet.sign_and_send_transaction.return_value = (True, {})
    service_manager.registry.extract_events.return_value = [{"name": "ActivateRegistration"}]

    assert service_manager.activate_registration() is True


def test_activate_registration_wrong_state(service_manager):
    """Test activation fails in wrong state."""
    service_manager.registry.get_service.return_value = {"state": ServiceState.DEPLOYED}
    assert service_manager.activate_registration() is False


def test_register_agent_success(service_manager, mock_wallet):
    """Test successful agent registration."""
    service_manager.registry.get_service.return_value = {"state": ServiceState.ACTIVE_REGISTRATION}

    # create_account is already mocked
    mock_wallet.send.return_value = (True, {})
    mock_wallet.sign_and_send_transaction.return_value = (True, {})
    service_manager.registry.extract_events.return_value = [{"name": "RegisterInstance"}]

    assert service_manager.register_agent() is True
    assert service_manager.config.agent_address == "0x0987654321098765432109876543210987654321"


def test_deploy_success(service_manager, mock_wallet):
    """Test successful deployment."""
    service_manager.registry.get_service.return_value = {
        "state": ServiceState.FINISHED_REGISTRATION
    }
    mock_wallet.sign_and_send_transaction.return_value = (True, {})
    service_manager.registry.extract_events.return_value = [
        {"name": "DeployService"},
        {"name": "CreateMultisigWithAgents", "args": {"multisig": "0xMultisig"}},
    ]

    assert service_manager.deploy() == "0xMultisig"
    assert service_manager.config.multisig_address == "0xMultisig"


def test_terminate_success(service_manager, mock_wallet):
    """Test successful termination."""
    service_manager.registry.get_service.return_value = {"state": ServiceState.DEPLOYED}
    # Not staked
    service_manager.config.staking_contract_address = None

    mock_wallet.sign_and_send_transaction.return_value = (True, {})
    service_manager.registry.extract_events.return_value = [{"name": "TerminateService"}]

    assert service_manager.terminate() is True


def test_unbond_success(service_manager, mock_wallet):
    """Test successful unbonding."""
    service_manager.registry.get_service.return_value = {"state": ServiceState.TERMINATED_BONDED}

    mock_wallet.sign_and_send_transaction.return_value = (True, {})
    service_manager.registry.extract_events.return_value = [{"name": "OperatorUnbond"}]

    assert service_manager.unbond() is True


def test_stake_success(service_manager, mock_wallet):
    """Test successful staking."""
    staking_contract = MagicMock()
    staking_contract.staking_token_address = "0xToken"
    staking_contract.get_service_ids.return_value = 0
    staking_contract.max_num_services = 10
    staking_contract.min_staking_deposit = 100
    staking_contract.address = "0xStaking"

    service_manager.registry.get_service.return_value = {"state": ServiceState.DEPLOYED}

    with patch("iwa.plugins.olas.service_manager.ERC20Contract") as mock_erc20:
        mock_erc20.return_value.balance_of_wei.return_value = 200

        mock_wallet.sign_and_send_transaction.return_value = (True, {})
        staking_contract.extract_events.return_value = [{"name": "ServiceStaked"}]
        staking_contract.get_staking_state.return_value = StakingState.STAKED

        # We need to make sure prepare_approve_tx is mocked ON THE REGISTRY INSTANCE
        service_manager.registry.prepare_approve_tx.return_value = {"to": "0xApprove"}

        assert service_manager.stake(staking_contract) is True
        assert service_manager.config.staking_contract_address == "0xStaking"


def test_unstake_success(service_manager, mock_wallet):
    """Test successful unstaking."""
    staking_contract = MagicMock()
    staking_contract.get_staking_state.return_value = StakingState.STAKED

    mock_wallet.sign_and_send_transaction.return_value = (True, {})
    staking_contract.extract_events.return_value = [{"name": "ServiceUnstaked"}]

    assert service_manager.unstake(staking_contract) is True
    assert service_manager.config.staking_contract_address is None
