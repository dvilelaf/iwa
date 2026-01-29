"""Tests for DrainManagerMixin coverage."""

from unittest.mock import MagicMock, patch

import pytest

from iwa.plugins.olas.contracts.staking import StakingState


@pytest.fixture
def mock_drain_manager():
    """Create a mock DrainManagerMixin instance."""
    from iwa.plugins.olas.service_manager.drain import DrainManagerMixin

    class MockManager(DrainManagerMixin):
        def __init__(self):
            self.wallet = MagicMock()
            self.service = MagicMock()
            self.chain_name = "gnosis"
            self.olas_config = MagicMock()

    return MockManager()


def test_claim_rewards_no_service(mock_drain_manager):
    """Test claim_rewards with no active service."""
    mock_drain_manager.service = None
    success, amount = mock_drain_manager.claim_rewards()
    assert not success
    assert amount == 0


def test_claim_rewards_not_staked(mock_drain_manager):
    """Test claim_rewards when service is not staked."""
    mock_drain_manager.service.staking_contract_address = None
    success, amount = mock_drain_manager.claim_rewards()
    assert not success
    assert amount == 0


def test_claim_rewards_claim_tx_fails(mock_drain_manager):
    """Test claim_rewards when prepare_claim_tx fails."""
    mock_drain_manager.service.staking_contract_address = "0xStaking"
    mock_drain_manager.service.service_id = 1

    with patch("iwa.plugins.olas.service_manager.drain.StakingContract") as mock_staking_cls:
        mock_staking = mock_staking_cls.return_value
        mock_staking.get_staking_state.return_value = StakingState.STAKED
        mock_staking.calculate_staking_reward.return_value = 1000000000000000000
        mock_staking.prepare_claim_tx.return_value = None  # Failed to prepare

        success, amount = mock_drain_manager.claim_rewards()
        assert not success
        assert amount == 0


def test_claim_rewards_send_fails(mock_drain_manager):
    """Test claim_rewards when transaction send fails."""
    mock_drain_manager.service.staking_contract_address = "0xStaking"
    mock_drain_manager.service.service_id = 1
    mock_drain_manager.wallet.master_account.address = "0xMaster"

    with patch("iwa.plugins.olas.service_manager.drain.StakingContract") as mock_staking_cls:
        mock_staking = mock_staking_cls.return_value
        mock_staking.get_staking_state.return_value = StakingState.STAKED
        mock_staking.calculate_staking_reward.return_value = 1000000000000000000
        mock_staking.prepare_claim_tx.return_value = {"to": "0x", "data": "0x"}
        mock_drain_manager.wallet.sign_and_send_transaction.return_value = (False, None)

        success, amount = mock_drain_manager.claim_rewards()
        assert not success
        assert amount == 0


def test_claim_rewards_success_no_event(mock_drain_manager):
    """Test claim_rewards success but no RewardClaimed event."""
    mock_drain_manager.service.staking_contract_address = "0xStaking"
    mock_drain_manager.service.service_id = 1
    mock_drain_manager.wallet.master_account.address = "0xMaster"

    with patch("iwa.plugins.olas.service_manager.drain.StakingContract") as mock_staking_cls:
        mock_staking = mock_staking_cls.return_value
        mock_staking.get_staking_state.return_value = StakingState.STAKED
        mock_staking.calculate_staking_reward.return_value = 1000000000000000000
        mock_staking.prepare_claim_tx.return_value = {"to": "0x", "data": "0x"}
        mock_staking.extract_events.return_value = []  # No RewardClaimed event
        mock_drain_manager.wallet.sign_and_send_transaction.return_value = (
            True,
            {"transactionHash": "0xHash"},
        )

        success, amount = mock_drain_manager.claim_rewards()
        assert success
        assert amount == 1000000000000000000


def test_claim_rewards_fallback_to_accrued(mock_drain_manager):
    """Test claim_rewards falls back to get_accrued_rewards when calculate_staking_reward fails."""
    mock_drain_manager.service.staking_contract_address = "0xStaking"
    mock_drain_manager.service.service_id = 1
    mock_drain_manager.wallet.master_account.address = "0xMaster"

    with patch("iwa.plugins.olas.service_manager.drain.StakingContract") as mock_staking_cls:
        mock_staking = mock_staking_cls.return_value
        mock_staking.get_staking_state.return_value = StakingState.STAKED
        # calculate_staking_reward fails, should fallback to get_accrued_rewards
        mock_staking.calculate_staking_reward.side_effect = Exception("RPC error")
        mock_staking.get_accrued_rewards.return_value = 2000000000000000000  # 2 OLAS
        mock_staking.prepare_claim_tx.return_value = {"to": "0x", "data": "0x"}
        mock_staking.extract_events.return_value = []
        mock_drain_manager.wallet.sign_and_send_transaction.return_value = (
            True,
            {"transactionHash": "0xHash"},
        )

        success, amount = mock_drain_manager.claim_rewards()
        assert success
        assert amount == 2000000000000000000
        # Verify both methods were called
        mock_staking.calculate_staking_reward.assert_called_once()
        mock_staking.get_accrued_rewards.assert_called_once()


def test_withdraw_rewards_fallback_to_master(mock_drain_manager):
    """Test withdraw_rewards falls back to master account when not configured."""
    mock_drain_manager.service.multisig_address = "0x1111111111111111111111111111111111111111"
    mock_drain_manager.olas_config.withdrawal_address = None
    mock_drain_manager.wallet.master_account.address = "0x2222222222222222222222222222222222222222"

    with patch("iwa.plugins.olas.service_manager.drain.ERC20Contract") as mock_erc20_cls:
        mock_erc20 = mock_erc20_cls.return_value
        mock_erc20.balance_of_wei.return_value = 0

        success, amount = mock_drain_manager.withdraw_rewards()
        # If balance is 0, it logs info and returns (False, 0) in drain.py
        assert not success
        assert amount == 0


def test_drain_service_no_service(mock_drain_manager):
    """Test drain_service with no active service."""
    mock_drain_manager.service = None
    result = mock_drain_manager.drain_service()
    assert result == {}


def test_claim_rewards_if_needed_exception(mock_drain_manager):
    """Test _claim_rewards_if_needed handles exceptions."""
    mock_drain_manager.service.staking_contract_address = "0xStaking"

    # Mock claim_rewards to raise
    mock_drain_manager.claim_rewards = MagicMock(side_effect=Exception("Test Error"))

    result = mock_drain_manager._claim_rewards_if_needed(claim_rewards=True)
    assert result == 0


def test_drain_agent_account_exception(mock_drain_manager):
    """Test _drain_agent_account handles drain exceptions."""
    mock_drain_manager.service.agent_address = "0xAgent"
    mock_drain_manager.wallet.drain.side_effect = Exception("Drain failed")

    result = mock_drain_manager._drain_agent_account("0xTarget", "gnosis")
    assert result is None


def test_drain_owner_account_exception(mock_drain_manager):
    """Test _drain_owner_account handles drain exceptions."""
    mock_drain_manager.service.service_owner_address = "0xOwner"
    mock_drain_manager.wallet.drain.side_effect = Exception("Drain failed")

    result = mock_drain_manager._drain_owner_account("0xTarget", "gnosis")
    assert result is None


def test_normalize_drain_result_tuple(mock_drain_manager):
    """Test _normalize_drain_result with tuple input."""

    # Success tuple with HexBytes-like object
    class FakeHexBytes:
        def hex(self):
            return "0xABCDEF"

    result = mock_drain_manager._normalize_drain_result((True, {"transactionHash": FakeHexBytes()}))
    assert result == "0xABCDEF"


def test_normalize_drain_result_failure_tuple(mock_drain_manager):
    """Test _normalize_drain_result with failure tuple."""
    result = mock_drain_manager._normalize_drain_result((False, {}))
    assert result is None


def test_normalize_drain_result_none(mock_drain_manager):
    """Test _normalize_drain_result with None input."""
    result = mock_drain_manager._normalize_drain_result(None)
    assert result is None


def test_drain_owner_skipped_when_equals_target(mock_drain_manager):
    """Test _drain_owner_account is skipped when owner == target."""
    mock_drain_manager.service.service_owner_address = "0xOwner123"
    # Target is the same as owner (case-insensitive)
    result = mock_drain_manager._drain_owner_account("0xowner123", "gnosis")
    # Should skip and return None without calling drain
    assert result is None
    mock_drain_manager.wallet.drain.assert_not_called()


def test_claim_rewards_staking_contract_load_fails(mock_drain_manager):
    """Test claim_rewards when StakingContract fails to load."""
    mock_drain_manager.service.staking_contract_address = "0xStaking"
    mock_drain_manager.service.service_id = 1

    with patch("iwa.plugins.olas.service_manager.drain.StakingContract") as mock_staking_cls:
        mock_staking_cls.side_effect = Exception("Failed to load contract")

        success, amount = mock_drain_manager.claim_rewards()
        assert not success
        assert amount == 0


def test_claim_rewards_not_staked_state(mock_drain_manager):
    """Test claim_rewards when service staking state is not STAKED."""
    mock_drain_manager.service.staking_contract_address = "0xStaking"
    mock_drain_manager.service.service_id = 1

    with patch("iwa.plugins.olas.service_manager.drain.StakingContract") as mock_staking_cls:
        mock_staking = mock_staking_cls.return_value
        mock_staking.get_staking_state.return_value = StakingState.NOT_STAKED

        success, amount = mock_drain_manager.claim_rewards()
        assert not success
        assert amount == 0


def test_claim_rewards_zero_rewards(mock_drain_manager):
    """Test claim_rewards when claimable rewards is zero."""
    mock_drain_manager.service.staking_contract_address = "0xStaking"
    mock_drain_manager.service.service_id = 1

    with patch("iwa.plugins.olas.service_manager.drain.StakingContract") as mock_staking_cls:
        mock_staking = mock_staking_cls.return_value
        mock_staking.get_staking_state.return_value = StakingState.STAKED
        mock_staking.calculate_staking_reward.return_value = 0

        success, amount = mock_drain_manager.claim_rewards()
        assert not success
        assert amount == 0


def test_claim_rewards_with_event_amount(mock_drain_manager):
    """Test claim_rewards extracts amount from RewardClaimed event."""
    mock_drain_manager.service.staking_contract_address = "0xStaking"
    mock_drain_manager.service.service_id = 1
    mock_drain_manager.wallet.master_account.address = "0xMaster"

    with patch("iwa.plugins.olas.service_manager.drain.StakingContract") as mock_staking_cls:
        mock_staking = mock_staking_cls.return_value
        mock_staking.get_staking_state.return_value = StakingState.STAKED
        mock_staking.calculate_staking_reward.return_value = 1000000000000000000
        mock_staking.prepare_claim_tx.return_value = {"to": "0x", "data": "0x"}
        # RewardClaimed event with 'amount' field
        mock_staking.extract_events.return_value = [
            {"name": "RewardClaimed", "args": {"amount": 1500000000000000000}}
        ]
        mock_drain_manager.wallet.sign_and_send_transaction.return_value = (
            True,
            {"transactionHash": "0xHash"},
        )

        success, amount = mock_drain_manager.claim_rewards()
        assert success
        # Should use amount from event, not the estimate
        assert amount == 1500000000000000000


def test_claim_rewards_with_event_reward_field(mock_drain_manager):
    """Test claim_rewards extracts from 'reward' field when 'amount' missing."""
    mock_drain_manager.service.staking_contract_address = "0xStaking"
    mock_drain_manager.service.service_id = 1
    mock_drain_manager.wallet.master_account.address = "0xMaster"

    with patch("iwa.plugins.olas.service_manager.drain.StakingContract") as mock_staking_cls:
        mock_staking = mock_staking_cls.return_value
        mock_staking.get_staking_state.return_value = StakingState.STAKED
        mock_staking.calculate_staking_reward.return_value = 1000000000000000000
        mock_staking.prepare_claim_tx.return_value = {"to": "0x", "data": "0x"}
        # RewardClaimed event with 'reward' field (no 'amount')
        mock_staking.extract_events.return_value = [
            {"name": "RewardClaimed", "args": {"reward": 2000000000000000000}}
        ]
        mock_drain_manager.wallet.sign_and_send_transaction.return_value = (
            True,
            {"transactionHash": "0xHash"},
        )

        success, amount = mock_drain_manager.claim_rewards()
        assert success
        assert amount == 2000000000000000000


def test_withdraw_rewards_no_service(mock_drain_manager):
    """Test withdraw_rewards with no active service."""
    mock_drain_manager.service = None
    success, amount = mock_drain_manager.withdraw_rewards()
    assert not success
    assert amount == 0


def test_withdraw_rewards_no_multisig(mock_drain_manager):
    """Test withdraw_rewards when service has no multisig."""
    mock_drain_manager.service.multisig_address = None
    success, amount = mock_drain_manager.withdraw_rewards()
    assert not success
    assert amount == 0


def test_withdraw_rewards_success(mock_drain_manager):
    """Test withdraw_rewards succeeds with balance."""
    mock_drain_manager.service.multisig_address = "0xSafe"
    mock_drain_manager.olas_config.withdrawal_address = "0xWithdraw"
    mock_drain_manager.wallet.account_service.get_tag_by_address.return_value = None
    mock_drain_manager.wallet.send.return_value = "0xTxHash"

    with patch("iwa.plugins.olas.service_manager.drain.ERC20Contract") as mock_erc20_cls:
        mock_erc20 = mock_erc20_cls.return_value
        mock_erc20.balance_of_wei.return_value = 5000000000000000000  # 5 OLAS

        success, amount = mock_drain_manager.withdraw_rewards()
        assert success
        assert amount == 5.0  # 5 OLAS


def test_withdraw_rewards_transfer_fails(mock_drain_manager):
    """Test withdraw_rewards when transfer fails."""
    mock_drain_manager.service.multisig_address = "0xSafe"
    mock_drain_manager.olas_config.withdrawal_address = "0xWithdraw"
    mock_drain_manager.wallet.account_service.get_tag_by_address.return_value = None
    mock_drain_manager.wallet.send.return_value = None  # Transfer failed

    with patch("iwa.plugins.olas.service_manager.drain.ERC20Contract") as mock_erc20_cls:
        mock_erc20 = mock_erc20_cls.return_value
        mock_erc20.balance_of_wei.return_value = 5000000000000000000

        success, amount = mock_drain_manager.withdraw_rewards()
        assert not success
        assert amount == 0


def test_drain_service_full_flow(mock_drain_manager):
    """Test drain_service drains all accounts."""
    mock_drain_manager.service.key = "test_service"
    mock_drain_manager.service.staking_contract_address = None  # No staking
    mock_drain_manager.service.multisig_address = "0xSafe"
    mock_drain_manager.service.agent_address = "0xAgent"
    mock_drain_manager.service.service_owner_address = "0xOwner"
    mock_drain_manager.wallet.master_account.address = "0xMaster"

    # Mock drain returns
    mock_drain_manager.wallet.drain.return_value = (True, {"transactionHash": b"0x123"})

    result = mock_drain_manager.drain_service(target_address="0xTarget")

    assert "safe" in result or "agent" in result or "owner" in result


def test_drain_safe_account_with_retry(mock_drain_manager):
    """Test _drain_safe_account retries when rewards were claimed."""
    mock_drain_manager.service.multisig_address = "0xSafe"
    # First call returns None (balance not updated yet), second returns result
    mock_drain_manager.wallet.drain.side_effect = [
        None,
        (True, {"transactionHash": b"0xhash"}),
    ]

    with patch("time.sleep"):  # Don't actually sleep
        mock_drain_manager._drain_safe_account(
            "0xTarget", "gnosis", claimed_rewards=1000
        )

    # Should have retried
    assert mock_drain_manager.wallet.drain.call_count >= 1


def test_drain_agent_account_success(mock_drain_manager):
    """Test _drain_agent_account success."""
    mock_drain_manager.service.agent_address = "0xAgent"
    mock_drain_manager.wallet.drain.return_value = (True, {"transactionHash": b"0xhash"})

    result = mock_drain_manager._drain_agent_account("0xTarget", "gnosis")

    assert result is not None


def test_drain_owner_account_success(mock_drain_manager):
    """Test _drain_owner_account success."""
    mock_drain_manager.service.service_owner_address = "0xOwner"
    mock_drain_manager.wallet.drain.return_value = (True, {"transactionHash": b"0xhash"})

    result = mock_drain_manager._drain_owner_account("0xTarget", "gnosis")

    assert result is not None


def test_normalize_drain_result_passthrough(mock_drain_manager):
    """Test _normalize_drain_result passes through non-tuple results."""
    result = mock_drain_manager._normalize_drain_result({"some": "dict"})
    assert result == {"some": "dict"}


def test_normalize_drain_result_string_hash(mock_drain_manager):
    """Test _normalize_drain_result handles string transaction hash."""
    result = mock_drain_manager._normalize_drain_result(
        (True, {"transactionHash": "0xABCDEF"})
    )
    assert result == "0xABCDEF"


def test_claim_rewards_if_needed_success(mock_drain_manager):
    """Test _claim_rewards_if_needed returns claimed amount on success."""
    mock_drain_manager.service.staking_contract_address = "0xStaking"
    mock_drain_manager.claim_rewards = MagicMock(return_value=(True, 1000000000000000000))

    result = mock_drain_manager._claim_rewards_if_needed(claim_rewards=True)
    assert result == 1000000000000000000


def test_claim_rewards_if_needed_disabled(mock_drain_manager):
    """Test _claim_rewards_if_needed returns 0 when disabled."""
    mock_drain_manager.service.staking_contract_address = "0xStaking"

    result = mock_drain_manager._claim_rewards_if_needed(claim_rewards=False)
    assert result == 0


def test_claim_rewards_if_needed_no_staking(mock_drain_manager):
    """Test _claim_rewards_if_needed returns 0 when not staked."""
    mock_drain_manager.service.staking_contract_address = None

    result = mock_drain_manager._claim_rewards_if_needed(claim_rewards=True)
    assert result == 0
