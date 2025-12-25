"""Tests for StakingContract functionality and validation."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from iwa.plugins.olas.contracts.staking import StakingContract


@pytest.fixture
def mock_staking():
    """Mock staking contract."""
    with (
        patch("iwa.plugins.olas.contracts.staking.ActivityCheckerContract"),
        patch("iwa.core.contracts.contract.ChainInterfaces") as mock_ci,
    ):
        mock_ci.get_instance.return_value.web3.eth.contract.return_value = MagicMock()
        contract = StakingContract("0x78731D3Ca6b7E34aC0F824c42a7cC18A495cabaB", "gnosis")
        # Mocking all initial calls in __init__
        contract.call = MagicMock()
        return contract


def test_staking_get_service_info_nested_tuple(mock_staking):
    """Test get_service_info with nested tuple result from web3."""
    nested_result = (("0xMultisig", "0xOwner", (1, 2), 1000, 500, 0),)
    mock_staking.call.side_effect = [
        "0x1",  # activityChecker
        100,  # availableRewards
        200,  # balance
        3600,  # livenessPeriod
        10,  # rewardsPerSecond
        10,  # maxNumServices
        50,  # minStakingDeposit
        7200,  # minStakingDuration
        "0xToken",  # stakingToken
        nested_result,  # getServiceInfo
        2000,  # getNextRewardCheckpointTimestamp
    ]
    # Re-init to trigger calls
    with (
        patch("iwa.plugins.olas.contracts.staking.ActivityCheckerContract"),
        patch("iwa.core.contracts.contract.ChainInterfaces") as mock_ci,
    ):
        mock_ci.get_instance.return_value.web3.eth.contract.return_value = MagicMock()
        staking = StakingContract("0x78731D3Ca6b7E34aC0F824c42a7cC18A495cabaB", "gnosis")
        staking.call = MagicMock(side_effect=[nested_result, 2000])
        staking.activity_checker.get_multisig_nonces.return_value = (1, 3)
        staking.get_required_requests = MagicMock(return_value=5)

        info = staking.get_service_info(1)
        assert info["multisig_address"] == "0xMultisig"
        assert info["mech_requests_this_epoch"] == 1  # 3 - 2


def test_staking_get_service_info_unpack_error(mock_staking):
    """Test get_service_info with invalid result length."""
    invalid_result = ("0x1", "0x2")  # Too short
    mock_staking.call.return_value = invalid_result
    with pytest.raises(ValueError):
        mock_staking.get_service_info(1)


def test_staking_min_staking_duration_cache(mock_staking):
    """Test caching of minStakingDuration."""
    mock_staking.call.return_value = 1234
    assert mock_staking.min_staking_duration == 1234
    assert mock_staking.call.call_count == 1
    # Second call should use cache
    assert mock_staking.min_staking_duration == 1234
    assert mock_staking.call.call_count == 1


def test_staking_checkpoint_needed(mock_staking):
    """Test is_checkpoint_needed logic."""
    epoch_end = datetime.now(timezone.utc) - timedelta(seconds=1000)
    mock_staking.get_next_epoch_start = MagicMock(return_value=epoch_end)

    # 1. Grace period not passed
    assert mock_staking.is_checkpoint_needed(grace_period_seconds=2000) is False

    # 2. Grace period passed
    assert mock_staking.is_checkpoint_needed(grace_period_seconds=500) is True

    # 3. Epoch not ended
    mock_staking.get_next_epoch_start.return_value = datetime.now(timezone.utc) + timedelta(
        seconds=1000
    )
    assert mock_staking.is_checkpoint_needed() is False


def test_staking_prepare_transactions(mock_staking):
    """Test preparation of various transactions."""
    mock_staking.prepare_transaction = MagicMock(return_value={"data": "0x1"})

    # Claim
    assert mock_staking.prepare_claim_tx("0xOwner", 1) == {"data": "0x1"}
    # Checkpoint
    assert mock_staking.prepare_checkpoint_tx("0xCaller") == {"data": "0x1"}


def test_staking_get_accrued_rewards(mock_staking):
    """Test get_accrued_rewards from mapServiceInfo."""
    mock_staking.call.return_value = ("0x1", "0x2", (1, 2), 1000, 999, 0)
    assert mock_staking.get_accrued_rewards(1) == 999

    mock_staking.call.return_value = ("0x1",)  # Too short
    assert mock_staking.get_accrued_rewards(2) == 0
