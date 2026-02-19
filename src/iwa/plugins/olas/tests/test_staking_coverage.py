"""Tests to improve coverage for staking.py (StakingManagerMixin).

Targets uncovered lines:
- 81-103: _get_label()
- 163: _fetch_staking_status_impl() not-staked branch
- 221: _identify_staking_contract_name() match found
- 237-239: _calculate_unstake_time() min_staking_duration exception
- 253-257: _calculate_unstake_time() calc error + ts_start==0 branch
- 396-413: _check_stake_requirements() agent bond checks
- 530: _execute_stake_transaction() tx reverted with status 0
- 586-588: unstake() exception getting staking state
- 601-605: unstake() min staking duration not met
- 623-625: unstake() prepare unstake tx exception
- 643-644: unstake() ServiceUnstaked event not found
- 697-699: call_checkpoint() failed to load staking contract
- 733-734: call_checkpoint() Checkpoint event not found
- 751-752: call_checkpoint() inactivity warnings
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from iwa.plugins.olas.contracts.service import ServiceState
from iwa.plugins.olas.contracts.staking import StakingState
from iwa.plugins.olas.models import Service
from iwa.plugins.olas.service_manager import ServiceManager
from iwa.plugins.olas.service_manager.staking import StakingManagerMixin

VALID_ADDR = "0x78731D3Ca6b7E34aC0F824c42a7cC18A495cabaB"
VALID_ADDR_2 = "0x1111111111111111111111111111111111111111"
VALID_ADDR_3 = "0x2222222222222222222222222222222222222222"


@pytest.fixture
def mock_wallet():
    """Mock wallet for ServiceManager."""
    w = MagicMock()
    w.master_account.address = VALID_ADDR
    w.sign_and_send_transaction.return_value = (True, {"status": 1, "transactionHash": "0xabc"})
    w.key_storage = MagicMock()
    w.key_storage._password = "pass"
    w.balance_service = MagicMock()
    w.drain.return_value = {"tx": "0x123"}
    w.account_service = MagicMock()
    return w


def _make_sm(mock_wallet, **service_kwargs):
    """Helper to create a ServiceManager with a mocked service."""
    defaults = {"service_name": "t", "chain_name": "gnosis", "service_id": 1}
    defaults.update(service_kwargs)
    with (
        patch("iwa.core.models.Config"),
        patch("iwa.plugins.olas.service_manager.base.ContractCache") as mock_cache,
        patch("iwa.plugins.olas.service_manager.staking.ContractCache", mock_cache),
    ):
        mock_cache.return_value.get_contract.side_effect = lambda cls, *a, **k: cls(*a, **k)
        sm = ServiceManager(mock_wallet)
        sm.service = Service(**defaults)
        return sm


# ============================================================================
# _get_label() tests — lines 81-103
# ============================================================================


class TestGetLabel:
    """Tests for StakingManagerMixin._get_label method (staking.py lines 79-103).

    Note: ServiceManager MRO resolves _get_label to LifecycleManagerMixin first,
    so we call StakingManagerMixin._get_label explicitly to test staking.py coverage.
    """

    def test_get_label_empty_address(self, mock_wallet):
        """Cover line 82: empty address returns 'None'."""
        sm = _make_sm(mock_wallet)
        assert StakingManagerMixin._get_label(sm, "") == "None"
        assert StakingManagerMixin._get_label(sm, None) == "None"

    def test_get_label_returns_tag(self, mock_wallet):
        """Cover lines 86-88: tag found via account_service."""
        sm = _make_sm(mock_wallet)
        sm.wallet.account_service.get_tag_by_address.return_value = "my-wallet"
        assert StakingManagerMixin._get_label(sm, VALID_ADDR) == "my-wallet"

    def test_get_label_tag_none_falls_through(self, mock_wallet):
        """Cover line 88 (tag is None) -> falls through to token name."""
        sm = _make_sm(mock_wallet)
        sm.wallet.account_service.get_tag_by_address.return_value = None

        with patch("iwa.core.chain.ChainInterfaces") as mock_ci:
            mock_chain = MagicMock()
            mock_ci.return_value.get.return_value = mock_chain
            mock_chain.chain.get_token_name.return_value = "OLAS"
            assert StakingManagerMixin._get_label(sm, VALID_ADDR) == "OLAS"

    def test_get_label_attribute_error_on_account_service(self, mock_wallet):
        """Cover lines 89-90: AttributeError on account_service."""
        sm = _make_sm(mock_wallet)
        sm.wallet.account_service.get_tag_by_address.side_effect = AttributeError

        with patch("iwa.core.chain.ChainInterfaces") as mock_ci:
            mock_chain = MagicMock()
            mock_ci.return_value.get.return_value = mock_chain
            mock_chain.chain.get_token_name.return_value = "WXDAI"
            assert StakingManagerMixin._get_label(sm, VALID_ADDR) == "WXDAI"

    def test_get_label_token_name_none(self, mock_wallet):
        """Cover line 99: token_name is None, falls through to return address."""
        sm = _make_sm(mock_wallet)
        sm.wallet.account_service.get_tag_by_address.return_value = None

        with patch("iwa.core.chain.ChainInterfaces") as mock_ci:
            mock_chain = MagicMock()
            mock_ci.return_value.get.return_value = mock_chain
            mock_chain.chain.get_token_name.return_value = None
            assert StakingManagerMixin._get_label(sm, VALID_ADDR) == VALID_ADDR

    def test_get_label_chain_interfaces_exception(self, mock_wallet):
        """Cover lines 100-101: exception in ChainInterfaces."""
        sm = _make_sm(mock_wallet)
        sm.wallet.account_service.get_tag_by_address.return_value = None

        with patch(
            "iwa.core.chain.ChainInterfaces",
            side_effect=Exception("no chain"),
        ):
            assert StakingManagerMixin._get_label(sm, VALID_ADDR) == VALID_ADDR


# ============================================================================
# _fetch_staking_status_impl() — line 163 (not staked branch)
# ============================================================================


class TestFetchStakingStatusNotStaked:
    """Tests for _fetch_staking_status_impl when service is not staked."""

    def test_status_not_staked_state(self, mock_wallet):
        """Cover line 163: staking_state is NOT_STAKED returns status with details."""
        sm = _make_sm(mock_wallet, staking_contract_address=VALID_ADDR)

        mock_staking = MagicMock()
        mock_staking.get_staking_state.return_value = StakingState.EVICTED
        mock_staking.activity_checker_address = VALID_ADDR_2
        mock_staking.activity_checker.liveness_ratio = 500

        with patch(
            "iwa.plugins.olas.service_manager.staking.ContractCache"
        ) as mock_cc:
            mock_cc.return_value.get_contract.return_value = mock_staking
            status = sm._fetch_staking_status_impl()

        assert status.is_staked is False
        assert status.staking_state == "EVICTED"
        assert status.activity_checker_address == VALID_ADDR_2
        assert status.liveness_ratio == 500


# ============================================================================
# _identify_staking_contract_name() — line 221
# ============================================================================


class TestIdentifyStakingContractName:
    """Tests for _identify_staking_contract_name."""

    def test_name_found(self, mock_wallet):
        """Cover line 221: matching address returns name."""
        sm = _make_sm(mock_wallet)

        with patch(
            "iwa.plugins.olas.constants.OLAS_TRADER_STAKING_CONTRACTS",
            {"gnosis": {"Expert 1": VALID_ADDR}},
        ):
            assert sm._identify_staking_contract_name(VALID_ADDR) == "Expert 1"

    def test_name_not_found(self, mock_wallet):
        """Cover line 222: no match returns None."""
        sm = _make_sm(mock_wallet)

        with patch(
            "iwa.plugins.olas.constants.OLAS_TRADER_STAKING_CONTRACTS",
            {"gnosis": {"Expert 1": VALID_ADDR_2}},
        ):
            assert sm._identify_staking_contract_name(VALID_ADDR_3) is None


# ============================================================================
# _calculate_unstake_time() — lines 237-239, 253-257
# ============================================================================


class TestCalculateUnstakeTime:
    """Tests for _calculate_unstake_time."""

    def test_min_staking_duration_exception(self, mock_wallet):
        """Cover lines 237-239: exception getting min_staking_duration."""
        sm = _make_sm(mock_wallet)

        mock_staking = MagicMock()
        type(mock_staking).min_staking_duration = PropertyMock(
            side_effect=Exception("contract error")
        )

        info = {"ts_start": 1000}
        unstake_at, ts_start, min_duration = sm._calculate_unstake_time(mock_staking, info)
        assert min_duration == 0
        assert ts_start == 1000
        # With min_duration=0, unstake_at = datetime(1000)
        assert unstake_at is not None

    def test_ts_start_zero(self, mock_wallet):
        """Cover lines 256-257: ts_start is 0 branch."""
        sm = _make_sm(mock_wallet)

        mock_staking = MagicMock()
        mock_staking.min_staking_duration = 86400

        info = {"ts_start": 0}
        unstake_at, ts_start, min_duration = sm._calculate_unstake_time(mock_staking, info)
        assert unstake_at is None
        assert ts_start == 0
        assert min_duration == 86400

    def test_calc_exception(self, mock_wallet):
        """Cover lines 253-255: exception in datetime calculation."""
        sm = _make_sm(mock_wallet)

        mock_staking = MagicMock()
        mock_staking.min_staking_duration = 86400

        # Use a value that would cause overflow in fromtimestamp
        info = {"ts_start": 99999999999999999}
        unstake_at, ts_start, min_duration = sm._calculate_unstake_time(mock_staking, info)
        # Exception caught, unstake_at stays None
        assert unstake_at is None
        assert ts_start == 99999999999999999


# ============================================================================
# _check_stake_requirements() — lines 396-413 (agent bond checks)
# ============================================================================


class TestCheckStakeRequirementsAgentBond:
    """Tests for agent bond verification in _check_stake_requirements."""

    def _make_staking_contract(self, bond_required=1000):
        """Helper to create a mock staking contract with requirements."""
        mock_staking = MagicMock()
        mock_staking.get_requirements.return_value = {
            "min_staking_deposit": 5000,
            "required_agent_bond": bond_required,
            "staking_token": VALID_ADDR_2,
        }
        mock_staking.get_service_ids.return_value = [1, 2]
        mock_staking.max_num_services = 10
        return mock_staking

    def test_no_agent_ids(self, mock_wallet):
        """Cover lines 396-398: no agent IDs found."""
        sm = _make_sm(mock_wallet, token_address=VALID_ADDR_2)

        mock_staking = self._make_staking_contract()
        mock_reg = MagicMock()
        mock_reg.get_service.return_value = {
            "state": ServiceState.DEPLOYED,
            "agent_ids": [],  # No agent IDs
        }
        sm.registry = mock_reg

        result = sm._check_stake_requirements(mock_staking)
        assert result is None

    def test_agent_bond_sufficient(self, mock_wallet):
        """Cover lines 400-413: agent bond >= required (OK path)."""
        sm = _make_sm(mock_wallet, token_address=VALID_ADDR_2)

        mock_staking = self._make_staking_contract(bond_required=1000)
        mock_reg = MagicMock()
        mock_reg.get_service.return_value = {
            "state": ServiceState.DEPLOYED,
            "agent_ids": [1],
        }
        mock_reg.get_agent_params.return_value = [{"bond": 2000}]
        sm.registry = mock_reg

        result = sm._check_stake_requirements(mock_staking)
        assert result is not None
        assert result["min_deposit"] == 5000

    def test_agent_bond_less_than_required(self, mock_wallet):
        """Cover lines 407-411: agent bond < required (warning but proceed)."""
        sm = _make_sm(mock_wallet, token_address=VALID_ADDR_2)

        mock_staking = self._make_staking_contract(bond_required=5000)
        mock_reg = MagicMock()
        mock_reg.get_service.return_value = {
            "state": ServiceState.DEPLOYED,
            "agent_ids": [1],
        }
        mock_reg.get_agent_params.return_value = [{"bond": 1}]
        sm.registry = mock_reg

        # Should succeed with warning (bond check is soft)
        result = sm._check_stake_requirements(mock_staking)
        assert result is not None

    def test_agent_bond_exception(self, mock_wallet):
        """Cover line 414-415: exception getting agent params."""
        sm = _make_sm(mock_wallet, token_address=VALID_ADDR_2)

        mock_staking = self._make_staking_contract(bond_required=1000)
        mock_reg = MagicMock()
        mock_reg.get_service.return_value = {
            "state": ServiceState.DEPLOYED,
            "agent_ids": [1],
        }
        mock_reg.get_agent_params.side_effect = Exception("RPC error")
        sm.registry = mock_reg

        # Should succeed despite exception (bond check is soft)
        result = sm._check_stake_requirements(mock_staking)
        assert result is not None


# ============================================================================
# _execute_stake_transaction() — line 530 (tx reverted with status 0)
# ============================================================================


class TestExecuteStakeTransactionReverted:
    """Tests for _execute_stake_transaction tx revert."""

    def test_tx_reverted_status_zero(self, mock_wallet):
        """Cover line 530: tx fails with receipt status 0."""
        sm = _make_sm(mock_wallet, multisig_address=VALID_ADDR)

        mock_staking = MagicMock()
        mock_staking.prepare_stake_tx.return_value = {"to": VALID_ADDR}
        mock_staking.address = VALID_ADDR

        # Transaction fails with status 0 in receipt
        mock_wallet.sign_and_send_transaction.return_value = (
            False,
            {"status": 0, "transactionHash": "0xfail"},
        )

        result = sm._execute_stake_transaction(mock_staking)
        assert result is False


# ============================================================================
# unstake() — lines 586-588, 601-605, 623-625, 643-644
# ============================================================================


class TestUnstakeEdgeCases:
    """Tests for unstake edge cases."""

    def test_unstake_get_staking_state_exception(self, mock_wallet):
        """Cover lines 586-588: exception getting staking state."""
        sm = _make_sm(mock_wallet, multisig_address=VALID_ADDR)

        mock_staking = MagicMock()
        mock_staking.get_staking_state.side_effect = Exception("RPC timeout")
        mock_staking.address = VALID_ADDR

        result = sm.unstake(mock_staking)
        assert result is False

    def test_unstake_min_duration_not_met(self, mock_wallet):
        """Cover lines 601-605: min staking duration not met."""
        sm = _make_sm(mock_wallet, multisig_address=VALID_ADDR)

        mock_staking = MagicMock()
        mock_staking.get_staking_state.return_value = StakingState.STAKED
        mock_staking.address = VALID_ADDR
        # Set ts_start in the far future so unlock_ts is always > now
        far_future_ts = int(datetime.now(timezone.utc).timestamp()) + 1000000
        mock_staking.get_service_info.return_value = {"ts_start": far_future_ts}
        mock_staking.min_staking_duration = 1000000

        result = sm.unstake(mock_staking)
        assert result is False

    def test_unstake_prepare_tx_exception(self, mock_wallet):
        """Cover lines 623-625: exception preparing unstake tx."""
        sm = _make_sm(mock_wallet, multisig_address=VALID_ADDR)

        mock_staking = MagicMock()
        mock_staking.get_staking_state.return_value = StakingState.STAKED
        mock_staking.address = VALID_ADDR
        mock_staking.get_service_info.return_value = {"ts_start": 1}
        mock_staking.min_staking_duration = 0
        mock_staking.prepare_unstake_tx.side_effect = Exception("encoding error")

        result = sm.unstake(mock_staking)
        assert result is False

    def test_unstake_no_service_unstaked_event(self, mock_wallet):
        """Cover lines 643-644: ServiceUnstaked event not found."""
        sm = _make_sm(mock_wallet, multisig_address=VALID_ADDR)

        mock_staking = MagicMock()
        mock_staking.get_staking_state.return_value = StakingState.STAKED
        mock_staking.address = VALID_ADDR
        mock_staking.get_service_info.return_value = {"ts_start": 1}
        mock_staking.min_staking_duration = 0
        mock_staking.prepare_unstake_tx.return_value = {"to": VALID_ADDR}
        # Events don't include ServiceUnstaked
        mock_staking.extract_events.return_value = [{"name": "Transfer"}]

        mock_wallet.sign_and_send_transaction.return_value = (
            True,
            {"status": 1, "transactionHash": "0xabc"},
        )

        result = sm.unstake(mock_staking)
        assert result is False


# ============================================================================
# call_checkpoint() — lines 697-699, 733-734, 751-752
# ============================================================================


class TestCallCheckpointEdgeCases:
    """Tests for call_checkpoint edge cases."""

    def test_checkpoint_load_contract_fails(self, mock_wallet):
        """Cover lines 697-699: failed to load staking contract."""
        sm = _make_sm(mock_wallet, staking_contract_address=VALID_ADDR)

        with patch(
            "iwa.plugins.olas.service_manager.staking.ContractCache"
        ) as mock_cc:
            mock_cc.return_value.get_contract.side_effect = Exception("load failed")
            result = sm.call_checkpoint()  # No staking_contract passed

        assert result is False

    def test_checkpoint_event_not_found(self, mock_wallet):
        """Cover lines 733-734: Checkpoint event not found in events."""
        sm = _make_sm(mock_wallet, staking_contract_address=VALID_ADDR)

        mock_staking = MagicMock()
        mock_staking.is_checkpoint_needed.return_value = True
        mock_staking.prepare_checkpoint_tx.return_value = {"to": VALID_ADDR}
        # Events don't include Checkpoint
        mock_staking.extract_events.return_value = [{"name": "Transfer"}]

        mock_wallet.sign_and_send_transaction.return_value = (
            True,
            {"status": 1, "transactionHash": "0xabc"},
        )

        result = sm.call_checkpoint(staking_contract=mock_staking)
        assert result is False

    def test_checkpoint_with_inactivity_warnings(self, mock_wallet):
        """Cover lines 751-752: checkpoint with inactivity warnings."""
        sm = _make_sm(mock_wallet, staking_contract_address=VALID_ADDR)

        mock_staking = MagicMock()
        mock_staking.is_checkpoint_needed.return_value = True
        mock_staking.prepare_checkpoint_tx.return_value = {"to": VALID_ADDR}
        # Events include Checkpoint AND inactivity warnings
        mock_staking.extract_events.return_value = [
            {
                "name": "Checkpoint",
                "args": {"epoch": 10, "availableRewards": 5000000000000000000},
            },
            {"name": "ServiceInactivityWarning", "args": {"serviceId": 101}},
            {"name": "ServiceInactivityWarning", "args": {"serviceId": 102}},
        ]

        mock_wallet.sign_and_send_transaction.return_value = (
            True,
            {"status": 1, "transactionHash": "0xabc"},
        )

        result = sm.call_checkpoint(staking_contract=mock_staking)
        assert result is True
