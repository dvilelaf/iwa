"""Tests for Olas ServiceManager validation and failure handling."""

from unittest.mock import MagicMock, patch

import pytest

from iwa.plugins.olas.contracts.service import ServiceState
from iwa.plugins.olas.models import Service
from iwa.plugins.olas.service_manager import ServiceManager

VALID_ADDR_1 = "0x78731D3Ca6b7E34aC0F824c42a7cC18A495cabaB"
VALID_ADDR_2 = "0x40A2aCCbd92BCA938b02010E17A5b8929b49130D"


@pytest.fixture
def mock_wallet():
    """Mock wallet."""
    wallet = MagicMock()
    wallet.master_account.address = VALID_ADDR_1
    wallet.transfer_service = MagicMock()
    return wallet


@pytest.fixture
def sm(mock_wallet):
    """ServiceManager fixture."""
    with patch("iwa.core.models.Config"):
        manager = ServiceManager(mock_wallet)
        # Mock service
        manager.service = Service(
            service_id=1,
            service_name="Test",
            chain_name="gnosis",
            agent_address=VALID_ADDR_1,
            multisig_address=VALID_ADDR_2,
            staking_contract_address=VALID_ADDR_1,
        )
        return manager


def test_drain_service_partial_failures(sm, mock_wallet):
    """Test drain_service handles partial failures across accounts."""
    # Setup:
    # 1. Claim success
    # 2. Safe drain failure
    # 3. Agent drain success

    with patch.object(sm, "claim_rewards", return_value=(True, 10**18)):
        # Wallet.drain is called for Safe and Agent
        def mock_drain(from_address_or_tag=None, to_address_or_tag=None, chain_name=None):
            if from_address_or_tag == VALID_ADDR_2:  # Safe
                raise Exception("Safe drain failed")
            return {"native": 0.5}

        mock_wallet.drain.side_effect = mock_drain

        result = sm.drain_service()

        assert "safe" not in result
        assert "agent" in result
        assert result["agent"]["native"] == 0.5
        # Verify it continued after Safe failure


def test_unstake_failed_event_extraction(sm):
    """Test unstake when transaction succeeds but event extraction fails."""
    staking_mock = MagicMock()
    sm.wallet.sign_and_send_transaction.return_value = (True, {"tx_hash": "0x123"})
    staking_mock.extract_events.return_value = []  # No Unstaked event

    success = sm.unstake(staking_mock)
    assert success is False  # Should return False if event missing


def test_call_checkpoint_grace_period(sm):
    """Test call_checkpoint respect for grace period."""
    staking_mock = MagicMock()
    # Mock status where epoch ended very recently (within grace period)
    staking_mock.get_staking_status.return_value = {
        "remaining_epoch_seconds": -50  # Ended 50s ago
    }
    # Mock is_checkpoint_needed to return False based on grace period
    staking_mock.is_checkpoint_needed.return_value = False
    staking_mock.get_next_epoch_start.return_value = MagicMock()

    # grace_period_seconds defaults to 600
    success = sm.call_checkpoint(staking_mock, grace_period_seconds=600)

    # Should skip checkpoint and return False (matching SM logic)
    assert success is False
    sm.wallet.sign_and_send_transaction.assert_not_called()


def test_call_checkpoint_success(sm):
    """Test successful call_checkpoint."""
    staking_mock = MagicMock()
    staking_mock.is_checkpoint_needed.return_value = True
    staking_mock.prepare_checkpoint_tx.return_value = {"to": "0x123", "data": "0x"}
    sm.wallet.sign_and_send_transaction.return_value = (True, {"tx_hash": "0x123", "logs": []})
    staking_mock.extract_events.return_value = [
        {"name": "Checkpoint", "args": {"epoch": 1, "availableRewards": 10**18}}
    ]

    success = sm.call_checkpoint(staking_mock)
    assert success is True
    sm.wallet.sign_and_send_transaction.assert_called_once()


def test_spin_up_intermediate_failure(sm):
    """Test spin_up stops at first failure."""
    # Mock sequential calls using ServiceState enum on the registry mock
    with patch.object(
        sm.registry,
        "get_service",
        side_effect=[
            {"state": ServiceState.PRE_REGISTRATION},
            {"state": ServiceState.ACTIVE_REGISTRATION},
            {"state": ServiceState.ACTIVE_REGISTRATION},  # Verification after activate
            {"state": ServiceState.ACTIVE_REGISTRATION},  # Final verification (if it reached there)
            {"state": ServiceState.ACTIVE_REGISTRATION},  # One more just in case
        ],
    ):
        with (
            patch.object(sm, "activate_registration", return_value=True) as m1,
            patch.object(sm, "register_agent", return_value=False) as m2,
            patch.object(sm, "deploy") as m3,
        ):
            success = sm.spin_up()

            assert success is False
            m1.assert_called_once()
            m2.assert_called_once()
            m3.assert_not_called()


def test_service_manager_no_service_error_handling(mock_wallet):
    """Test methods return gracefully when no service is selected."""
    with patch("iwa.core.models.Config"):
        manager = ServiceManager(mock_wallet)
        manager.service = None

        assert manager.get() is None
        assert manager.drain_service() == {}
        assert manager.get_staking_status() is None
        assert manager.claim_rewards() == (False, 0)
