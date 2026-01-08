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
        mock_staking.get_accrued_rewards.return_value = 1000000000000000000
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
        mock_staking.get_accrued_rewards.return_value = 1000000000000000000
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
        mock_staking.get_accrued_rewards.return_value = 1000000000000000000
        mock_staking.prepare_claim_tx.return_value = {"to": "0x", "data": "0x"}
        mock_staking.extract_events.return_value = []  # No RewardClaimed event
        mock_drain_manager.wallet.sign_and_send_transaction.return_value = (
            True,
            {"transactionHash": "0xHash"},
        )

        success, amount = mock_drain_manager.claim_rewards()
        assert success
        assert amount == 1000000000000000000


def test_withdraw_rewards_no_withdrawal_address(mock_drain_manager):
    """Test withdraw_rewards with no withdrawal address configured."""
    mock_drain_manager.service.multisig_address = "0xSafe"
    mock_drain_manager.olas_config.withdrawal_address = None

    success, amount = mock_drain_manager.withdraw_rewards()
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
