"""Tests for staking rewards claim, withdraw, and checkpoint functionality."""

from unittest.mock import MagicMock, patch

import pytest

from iwa.plugins.olas.contracts.staking import StakingState
from iwa.plugins.olas.models import Service
from iwa.plugins.olas.service_manager import ServiceManager

VALID_ADDR = "0x1234567890123456789012345678901234567890"
WITHDRAWAL_ADDR = "0xABCDEFabcdefABCDEFabcdefABCDEFabcdefABCD"


@pytest.fixture
def mock_wallet():
    """Create a mock wallet for tests."""
    wallet = MagicMock()
    wallet.master_account.address = VALID_ADDR
    wallet.chain_interface.chain_name = "gnosis"
    wallet.sign_and_send_transaction.return_value = (True, {"transactionHash": b"\x00" * 32})
    wallet.send.return_value = "0xtxhash"
    return wallet


def setup_manager(mock_wallet):
    """Setup a ServiceManager with mocked dependencies."""
    with patch("iwa.plugins.olas.service_manager.base.Config") as mock_cfg_cls:
        mock_cfg = mock_cfg_cls.return_value
        mock_olas_config = MagicMock()
        mock_olas_config.get_service.return_value = None
        mock_olas_config.withdrawal_address = None
        mock_cfg.plugins = {"olas": mock_olas_config}
        with patch(
            "iwa.plugins.olas.service_manager.OLAS_CONTRACTS",
            {
                "gnosis": {
                    "OLAS_SERVICE_REGISTRY": VALID_ADDR,
                    "OLAS_SERVICE_MANAGER": VALID_ADDR,
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
                manager.olas_config = mock_olas_config
                manager.chain_name = "gnosis"
                return manager


def test_claim_rewards_no_service(mock_wallet):
    """Test claim_rewards fails when no service is loaded."""
    manager = setup_manager(mock_wallet)
    manager.service = None

    success, amount = manager.claim_rewards()

    assert success is False
    assert amount == 0


def test_claim_rewards_not_staked(mock_wallet):
    """Test claim_rewards fails when service is not staked."""
    manager = setup_manager(mock_wallet)
    manager.service = Service(service_name="test", chain_name="gnosis", service_id=1, agent_ids=[1])
    manager.service.staking_contract_address = None

    success, amount = manager.claim_rewards()

    assert success is False
    assert amount == 0


def test_claim_rewards_service_not_staked_state(mock_wallet):
    """Test claim_rewards fails when staking state is NOT_STAKED."""
    manager = setup_manager(mock_wallet)
    manager.service = Service(
        service_name="test",
        chain_name="gnosis",
        service_id=1,
        agent_ids=[1],
        staking_contract_address=VALID_ADDR,
    )

    mock_staking = MagicMock()
    mock_staking.get_staking_state.return_value = StakingState.NOT_STAKED

    success, amount = manager.claim_rewards(staking_contract=mock_staking)

    assert success is False
    assert amount == 0


def test_claim_rewards_no_accrued_rewards(mock_wallet):
    """Test claim_rewards fails when no rewards are accrued."""
    manager = setup_manager(mock_wallet)
    manager.service = Service(
        service_name="test",
        chain_name="gnosis",
        service_id=1,
        agent_ids=[1],
        staking_contract_address=VALID_ADDR,
    )

    mock_staking = MagicMock()
    mock_staking.get_staking_state.return_value = StakingState.STAKED
    mock_staking.get_accrued_rewards.return_value = 0

    success, amount = manager.claim_rewards(staking_contract=mock_staking)

    assert success is False
    assert amount == 0


def test_claim_rewards_success(mock_wallet):
    """Test claim_rewards succeeds with proper setup."""
    manager = setup_manager(mock_wallet)
    manager.service = Service(
        service_name="test",
        chain_name="gnosis",
        service_id=1,
        agent_ids=[1],
        staking_contract_address=VALID_ADDR,
    )

    mock_staking = MagicMock()
    mock_staking.get_staking_state.return_value = StakingState.STAKED
    mock_staking.get_accrued_rewards.return_value = 10 * 10**18  # 10 OLAS
    mock_staking.prepare_claim_tx.return_value = {"data": "0x"}
    mock_staking.extract_events.return_value = [{"name": "RewardClaimed"}]

    success, amount = manager.claim_rewards(staking_contract=mock_staking)

    assert success is True
    assert amount == 10 * 10**18


def test_claim_rewards_tx_fails(mock_wallet):
    """Test claim_rewards fails when transaction fails."""
    manager = setup_manager(mock_wallet)
    manager.service = Service(
        service_name="test",
        chain_name="gnosis",
        service_id=1,
        agent_ids=[1],
        staking_contract_address=VALID_ADDR,
    )

    mock_staking = MagicMock()
    mock_staking.get_staking_state.return_value = StakingState.STAKED
    mock_staking.get_accrued_rewards.return_value = 10 * 10**18
    mock_staking.prepare_claim_tx.return_value = {"data": "0x"}
    mock_wallet.sign_and_send_transaction.return_value = (False, {})

    success, amount = manager.claim_rewards(staking_contract=mock_staking)

    assert success is False
    assert amount == 0


def test_withdraw_rewards_no_service(mock_wallet):
    """Test withdraw_rewards fails when no service is loaded."""
    manager = setup_manager(mock_wallet)
    manager.service = None

    success, amount = manager.withdraw_rewards()

    assert success is False
    assert amount == 0


def test_withdraw_rewards_no_multisig(mock_wallet):
    """Test withdraw_rewards fails when service has no multisig."""
    manager = setup_manager(mock_wallet)
    manager.service = Service(service_name="test", chain_name="gnosis", service_id=1, agent_ids=[1])
    manager.service.multisig_address = None

    success, amount = manager.withdraw_rewards()

    assert success is False
    assert amount == 0


def test_withdraw_rewards_no_withdrawal_address(mock_wallet):
    """Test withdraw_rewards fails when no withdrawal address configured."""
    manager = setup_manager(mock_wallet)
    manager.service = Service(
        service_name="test",
        chain_name="gnosis",
        service_id=1,
        agent_ids=[1],
        multisig_address=VALID_ADDR,
    )
    manager.olas_config.withdrawal_address = None

    success, amount = manager.withdraw_rewards()

    assert success is False
    assert amount == 0


def test_withdraw_rewards_no_olas_balance(mock_wallet):
    """Test withdraw_rewards fails when Safe has no OLAS balance."""
    manager = setup_manager(mock_wallet)
    manager.service = Service(
        service_name="test",
        chain_name="gnosis",
        service_id=1,
        agent_ids=[1],
        multisig_address=VALID_ADDR,
    )
    manager.olas_config.withdrawal_address = WITHDRAWAL_ADDR

    with patch("iwa.plugins.olas.service_manager.drain.ERC20Contract") as mock_erc20_cls:
        mock_erc20 = mock_erc20_cls.return_value
        mock_erc20.balance_of_wei.return_value = 0

        success, amount = manager.withdraw_rewards()

    assert success is False
    assert amount == 0


def test_withdraw_rewards_success(mock_wallet):
    """Test withdraw_rewards succeeds with proper setup."""
    manager = setup_manager(mock_wallet)
    manager.service = Service(
        service_name="test",
        chain_name="gnosis",
        service_id=1,
        agent_ids=[1],
        multisig_address=VALID_ADDR,
    )
    manager.olas_config.withdrawal_address = WITHDRAWAL_ADDR

    with patch("iwa.plugins.olas.service_manager.drain.ERC20Contract") as mock_erc20_cls:
        mock_erc20 = mock_erc20_cls.return_value
        mock_erc20.balance_of_wei.return_value = 50 * 10**18  # 50 OLAS

        success, amount = manager.withdraw_rewards()

    assert success is True
    assert amount == 50.0
    mock_wallet.send.assert_called_once()


def test_withdraw_rewards_transfer_fails(mock_wallet):
    """Test withdraw_rewards fails when transfer fails."""
    manager = setup_manager(mock_wallet)
    manager.service = Service(
        service_name="test",
        chain_name="gnosis",
        service_id=1,
        agent_ids=[1],
        multisig_address=VALID_ADDR,
    )
    manager.olas_config.withdrawal_address = WITHDRAWAL_ADDR
    mock_wallet.send.return_value = None  # Transfer fails

    with patch("iwa.plugins.olas.service_manager.drain.ERC20Contract") as mock_erc20_cls:
        mock_erc20 = mock_erc20_cls.return_value
        mock_erc20.balance_of_wei.return_value = 50 * 10**18

        success, amount = manager.withdraw_rewards()

    assert success is False
    assert amount == 0


# ============================================================================
# Checkpoint Tests
# ============================================================================


def test_call_checkpoint_no_service(mock_wallet):
    """Test call_checkpoint fails when no service is loaded."""
    manager = setup_manager(mock_wallet)
    manager.service = None

    result = manager.call_checkpoint()

    assert result is False


def test_call_checkpoint_not_staked(mock_wallet):
    """Test call_checkpoint fails when service is not staked."""
    manager = setup_manager(mock_wallet)
    manager.service = Service(service_name="test", chain_name="gnosis", service_id=1, agent_ids=[1])
    manager.service.staking_contract_address = None

    result = manager.call_checkpoint()

    assert result is False


def test_call_checkpoint_not_needed(mock_wallet):
    """Test call_checkpoint returns False when checkpoint is not needed."""
    manager = setup_manager(mock_wallet)
    manager.service = Service(
        service_name="test",
        chain_name="gnosis",
        service_id=1,
        agent_ids=[1],
        staking_contract_address=VALID_ADDR,
    )

    mock_staking = MagicMock()
    mock_staking.is_checkpoint_needed.return_value = False
    mock_staking.get_next_epoch_start.return_value = MagicMock()

    result = manager.call_checkpoint(staking_contract=mock_staking)

    assert result is False


def test_call_checkpoint_success(mock_wallet):
    """Test call_checkpoint succeeds with proper setup."""
    manager = setup_manager(mock_wallet)
    manager.service = Service(
        service_name="test",
        chain_name="gnosis",
        service_id=1,
        agent_ids=[1],
        staking_contract_address=VALID_ADDR,
    )

    mock_staking = MagicMock()
    mock_staking.is_checkpoint_needed.return_value = True
    mock_staking.prepare_checkpoint_tx.return_value = {"data": "0x", "gas": 4_000_000}
    mock_staking.extract_events.return_value = [{"name": "Checkpoint"}]

    result = manager.call_checkpoint(staking_contract=mock_staking)

    assert result is True
    mock_staking.prepare_checkpoint_tx.assert_called_once()


def test_call_checkpoint_tx_fails(mock_wallet):
    """Test call_checkpoint fails when transaction fails."""
    manager = setup_manager(mock_wallet)
    manager.service = Service(
        service_name="test",
        chain_name="gnosis",
        service_id=1,
        agent_ids=[1],
        staking_contract_address=VALID_ADDR,
    )

    mock_staking = MagicMock()
    mock_staking.is_checkpoint_needed.return_value = True
    mock_staking.prepare_checkpoint_tx.return_value = {"data": "0x", "gas": 4_000_000}
    mock_wallet.sign_and_send_transaction.return_value = (False, {})

    result = manager.call_checkpoint(staking_contract=mock_staking)

    assert result is False
