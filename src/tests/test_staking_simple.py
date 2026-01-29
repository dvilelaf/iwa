"""Tests for StakingContract."""

import time
from datetime import datetime, timezone
from unittest.mock import MagicMock, mock_open, patch

import pytest

from iwa.plugins.olas.contracts.staking import StakingContract, StakingState


@pytest.fixture
def mock_staking_contract():
    """Create a mocked StakingContract instance."""
    with (
        patch("iwa.core.contracts.contract.ChainInterfaces") as mock_chains,
        patch("iwa.plugins.olas.contracts.staking.ActivityCheckerContract"),
        patch("builtins.open", mock_open(read_data="[]")),
    ):
        mock_interface = MagicMock()
        mock_chains.return_value.get.return_value = mock_interface

        # Mock contract calls
        mock_interface.call_contract.side_effect = lambda method, *args: {
            "activityChecker": "0xChecker",
            "availableRewards": 100,
            "balance": 1000,
            "livenessPeriod": 3600,
            "rewardsPerSecond": 1,
            "maxNumServices": 10,
            "minStakingDeposit": 100,
            "minStakingDuration": 86400,
            "stakingToken": "0xToken",
            "epochCounter": 5,
            "getNextRewardCheckpointTimestamp": int(time.time()) + 3600,
            "getServiceIds": [1, 2, 3],
            "getStakingState": 1,  # STAKED
            "calculateStakingLastReward": 500,
            "calculateStakingReward": 600,
            "tsCheckpoint": int(time.time()) - 1000,
            "mapServiceInfo": ("0xMultisig", "0xOwner", (10, 5), 1000, 750, 0),
            "getServiceInfo": (
                "0xMultisig",
                "0xOwner",
                (10, 5),
                int(time.time()) - 1000,
                750,
                0,
            ),
        }.get(method, 0)

        contract = StakingContract(address="0x123")
        contract._interface = mock_interface
        yield contract


class TestStakingContractInit:
    """Test StakingContract initialization."""

    def test_basic_init(self):
        with (
            patch("iwa.core.contracts.contract.ChainInterfaces") as mock_chains,
            patch("iwa.plugins.olas.contracts.staking.ActivityCheckerContract"),
            patch("builtins.open", mock_open(read_data="[]")),
        ):
            mock_interface = MagicMock()
            mock_chains.return_value.get.return_value = mock_interface
            mock_interface.call_contract.return_value = 0

            contract = StakingContract(address="0x123")
            assert contract.address == "0x123"
            assert contract.chain_name == "gnosis"


class TestStakingState:
    """Test StakingState enum."""

    def test_not_staked(self):
        assert StakingState.NOT_STAKED.value == 0

    def test_staked(self):
        assert StakingState.STAKED.value == 1

    def test_evicted(self):
        assert StakingState.EVICTED.value == 2


class TestGetRequirements:
    """Test get_requirements method."""

    def test_returns_dict_with_required_fields(self, mock_staking_contract):
        # Use cache to set property values
        mock_staking_contract._contract_params_cache = {
            "stakingToken": "0xOLAS",
            "minStakingDeposit": 50,
        }

        result = mock_staking_contract.get_requirements()

        assert "staking_token" in result
        assert "min_staking_deposit" in result
        assert "required_agent_bond" in result
        assert result["staking_token"] == "0xOLAS"
        assert result["min_staking_deposit"] == 50
        assert result["required_agent_bond"] == 50


class TestCalculationMethods:
    """Test reward calculation methods."""

    def test_calculate_accrued_staking_reward(self, mock_staking_contract):
        mock_staking_contract.call = MagicMock(return_value=500)
        result = mock_staking_contract.calculate_accrued_staking_reward(1)
        assert result == 500
        mock_staking_contract.call.assert_called_with("calculateStakingLastReward", 1)

    def test_calculate_staking_reward(self, mock_staking_contract):
        mock_staking_contract.call = MagicMock(return_value=600)
        result = mock_staking_contract.calculate_staking_reward(1)
        assert result == 600
        mock_staking_contract.call.assert_called_with("calculateStakingReward", 1)

    def test_get_epoch_counter(self, mock_staking_contract):
        mock_staking_contract.call = MagicMock(return_value=5)
        result = mock_staking_contract.get_epoch_counter()
        assert result == 5
        mock_staking_contract.call.assert_called_with("epochCounter")

    def test_get_service_ids(self, mock_staking_contract):
        mock_staking_contract.call = MagicMock(return_value=[1, 2, 3])
        result = mock_staking_contract.get_service_ids()
        assert result == [1, 2, 3]


class TestGetNextEpochStart:
    """Test get_next_epoch_start method."""

    def test_returns_datetime(self, mock_staking_contract):
        future_ts = int(time.time()) + 3600
        mock_staking_contract.call = MagicMock(return_value=future_ts)
        result = mock_staking_contract.get_next_epoch_start()
        assert isinstance(result, datetime)
        assert result.tzinfo == timezone.utc


class TestGetStakingState:
    """Test get_staking_state method."""

    def test_returns_staked(self, mock_staking_contract):
        mock_staking_contract.call = MagicMock(return_value=1)
        result = mock_staking_contract.get_staking_state(1)
        assert result == StakingState.STAKED

    def test_returns_not_staked(self, mock_staking_contract):
        mock_staking_contract.call = MagicMock(return_value=0)
        result = mock_staking_contract.get_staking_state(1)
        assert result == StakingState.NOT_STAKED

    def test_returns_evicted(self, mock_staking_contract):
        mock_staking_contract.call = MagicMock(return_value=2)
        result = mock_staking_contract.get_staking_state(1)
        assert result == StakingState.EVICTED


class TestTsCheckpoint:
    """Test ts_checkpoint caching."""

    def test_caches_value(self, mock_staking_contract):
        ts = int(time.time()) - 100
        mock_staking_contract.call = MagicMock(return_value=ts)
        mock_staking_contract._contract_params_cache = {"livenessPeriod": 3600}

        # First call fetches
        result1 = mock_staking_contract.ts_checkpoint()
        assert result1 == ts
        assert mock_staking_contract.call.call_count == 1

        # Second call uses cache (within liveness_period)
        result2 = mock_staking_contract.ts_checkpoint()
        assert result2 == ts
        # Should still be 1 call (cached)
        assert mock_staking_contract.call.call_count == 1

    def test_clear_epoch_cache(self, mock_staking_contract):
        mock_staking_contract._contract_params_cache = {
            "ts_checkpoint": 1000,
            "ts_checkpoint_last_checked": 900,
            "other_key": "value",
        }

        mock_staking_contract.clear_epoch_cache()

        assert "ts_checkpoint" not in mock_staking_contract._contract_params_cache
        assert "ts_checkpoint_last_checked" not in mock_staking_contract._contract_params_cache
        assert "other_key" in mock_staking_contract._contract_params_cache


class TestGetRequiredRequests:
    """Test get_required_requests method."""

    def test_with_liveness_period(self, mock_staking_contract):
        mock_staking_contract._contract_params_cache = {"livenessPeriod": 86400}
        mock_activity_checker = MagicMock()
        mock_activity_checker.liveness_ratio = 1e18  # 1 request per second
        mock_staking_contract._activity_checker = mock_activity_checker

        result = mock_staking_contract.get_required_requests(use_liveness_period=True)

        # Should be ceiling of (86400 * 1e18 / 1e18) + 1 = 86401
        assert result == 86401


class TestProperties:
    """Test cached properties."""

    def test_available_rewards(self, mock_staking_contract):
        mock_staking_contract.call = MagicMock(return_value=1000)
        mock_staking_contract._contract_params_cache = {}

        result = mock_staking_contract.available_rewards
        assert result == 1000
        mock_staking_contract.call.assert_called_with("availableRewards")

    def test_balance(self, mock_staking_contract):
        mock_staking_contract.call = MagicMock(return_value=5000)
        mock_staking_contract._contract_params_cache = {}

        result = mock_staking_contract.balance
        assert result == 5000

    def test_liveness_period(self, mock_staking_contract):
        mock_staking_contract.call = MagicMock(return_value=86400)
        mock_staking_contract._contract_params_cache = {}

        result = mock_staking_contract.liveness_period
        assert result == 86400

    def test_rewards_per_second(self, mock_staking_contract):
        mock_staking_contract.call = MagicMock(return_value=100)
        mock_staking_contract._contract_params_cache = {}

        result = mock_staking_contract.rewards_per_second
        assert result == 100

    def test_max_num_services(self, mock_staking_contract):
        mock_staking_contract.call = MagicMock(return_value=50)
        mock_staking_contract._contract_params_cache = {}

        result = mock_staking_contract.max_num_services
        assert result == 50

    def test_min_staking_deposit(self, mock_staking_contract):
        mock_staking_contract.call = MagicMock(return_value=100)
        mock_staking_contract._contract_params_cache = {}

        result = mock_staking_contract.min_staking_deposit
        assert result == 100

    def test_min_staking_duration_hours(self, mock_staking_contract):
        mock_staking_contract._contract_params_cache = {"minStakingDuration": 7200}
        result = mock_staking_contract.min_staking_duration_hours
        assert result == 2.0  # 7200 / 3600

    def test_staking_token_address(self, mock_staking_contract):
        mock_staking_contract.call = MagicMock(return_value="0xOLAS")
        mock_staking_contract._contract_params_cache = {}

        result = mock_staking_contract.staking_token_address
        assert result == "0xOLAS"

    def test_min_staking_duration(self, mock_staking_contract):
        mock_staking_contract.call = MagicMock(return_value=86400)
        mock_staking_contract._contract_params_cache = {}

        result = mock_staking_contract.min_staking_duration
        assert result == 86400


class TestActivityChecker:
    """Test activity checker related methods."""

    def test_activity_checker_address_value(self, mock_staking_contract):
        mock_staking_contract.call = MagicMock(return_value="0xChecker")
        mock_staking_contract._activity_checker_address = None

        result = mock_staking_contract.activity_checker_address_value
        assert result == "0xChecker"

    def test_activity_checker_address_backwards_compat(self, mock_staking_contract):
        mock_staking_contract._activity_checker_address = "0xChecker"
        result = mock_staking_contract.activity_checker_address
        assert result == "0xChecker"

    def test_activity_checker_lazy_load(self, mock_staking_contract):
        mock_staking_contract._activity_checker = None
        mock_staking_contract._activity_checker_address = "0xChecker"

        with patch(
            "iwa.plugins.olas.contracts.staking.ActivityCheckerContract"
        ) as mock_ac_cls:
            mock_ac = MagicMock()
            mock_ac_cls.return_value = mock_ac

            result = mock_staking_contract.activity_checker
            assert result == mock_ac
            mock_ac_cls.assert_called_with("0xChecker", chain_name="gnosis")


class TestIsLivenessRatioPassed:
    """Test is_liveness_ratio_passed method."""

    def test_returns_false_for_zero_time_diff(self, mock_staking_contract):
        current_nonces = (10, 5)
        last_nonces = (8, 3)
        # ts_start in future = negative time diff
        ts_start = int(time.time()) + 100

        result = mock_staking_contract.is_liveness_ratio_passed(
            current_nonces, last_nonces, ts_start
        )
        assert result is False

    def test_calls_activity_checker(self, mock_staking_contract):
        mock_ac = MagicMock()
        mock_ac.is_ratio_pass.return_value = True
        mock_staking_contract._activity_checker = mock_ac

        current_nonces = (10, 5)
        last_nonces = (8, 3)
        ts_start = int(time.time()) - 1000

        result = mock_staking_contract.is_liveness_ratio_passed(
            current_nonces, last_nonces, ts_start
        )

        assert result is True
        mock_ac.is_ratio_pass.assert_called_once()


class TestPrepareTxMethods:
    """Test transaction preparation methods."""

    def test_prepare_stake_tx(self, mock_staking_contract):
        mock_staking_contract.prepare_transaction = MagicMock(return_value={"to": "0x"})

        result = mock_staking_contract.prepare_stake_tx("0xOwner", 1)

        assert result == {"to": "0x"}
        mock_staking_contract.prepare_transaction.assert_called_with(
            method_name="stake",
            method_kwargs={"serviceId": 1},
            tx_params={"from": "0xOwner"},
        )

    def test_prepare_unstake_tx(self, mock_staking_contract):
        mock_staking_contract.prepare_transaction = MagicMock(return_value={"to": "0x"})

        result = mock_staking_contract.prepare_unstake_tx("0xOwner", 1)

        assert result == {"to": "0x"}
        mock_staking_contract.prepare_transaction.assert_called_with(
            method_name="unstake",
            method_kwargs={"serviceId": 1},
            tx_params={"from": "0xOwner"},
        )

    def test_prepare_claim_tx(self, mock_staking_contract):
        mock_staking_contract.prepare_transaction = MagicMock(return_value={"to": "0x"})

        result = mock_staking_contract.prepare_claim_tx("0xOwner", 1)

        assert result == {"to": "0x"}
        mock_staking_contract.prepare_transaction.assert_called_with(
            method_name="claim",
            method_kwargs={"serviceId": 1},
            tx_params={"from": "0xOwner"},
        )

    def test_prepare_checkpoint_tx(self, mock_staking_contract):
        mock_staking_contract.prepare_transaction = MagicMock(return_value={"to": "0x"})

        result = mock_staking_contract.prepare_checkpoint_tx("0xCaller")

        assert result == {"to": "0x"}
        mock_staking_contract.prepare_transaction.assert_called_with(
            method_name="checkpoint",
            method_kwargs={},
            tx_params={"from": "0xCaller"},
        )


class TestGetAccruedRewards:
    """Test get_accrued_rewards method."""

    def test_extracts_reward_from_service_info(self, mock_staking_contract):
        # mapServiceInfo returns (multisig, owner, nonces, tsStart, reward, inactivity)
        mock_staking_contract.call = MagicMock(
            return_value=("0xMultisig", "0xOwner", (10, 5), 1000, 750, 0)
        )

        result = mock_staking_contract.get_accrued_rewards(1)

        assert result == 750

    def test_returns_zero_for_short_response(self, mock_staking_contract):
        mock_staking_contract.call = MagicMock(return_value=(1, 2, 3))

        result = mock_staking_contract.get_accrued_rewards(1)

        assert result == 0


class TestIsCheckpointNeeded:
    """Test is_checkpoint_needed method."""

    def test_returns_false_before_epoch_end(self, mock_staking_contract):
        future_time = datetime.now(timezone.utc).replace(microsecond=0)
        future_time = future_time.replace(hour=future_time.hour + 1)

        with patch.object(mock_staking_contract, "get_next_epoch_start", return_value=future_time):
            result = mock_staking_contract.is_checkpoint_needed()
            assert result is False

    def test_returns_false_within_grace_period(self, mock_staking_contract):
        # Epoch ended 5 minutes ago (300 seconds), grace period is 600 seconds
        past_time = datetime.now(timezone.utc).replace(microsecond=0)
        from datetime import timedelta
        past_time = past_time - timedelta(seconds=300)

        with patch.object(mock_staking_contract, "get_next_epoch_start", return_value=past_time):
            result = mock_staking_contract.is_checkpoint_needed(grace_period_seconds=600)
            assert result is False

    def test_returns_true_after_grace_period(self, mock_staking_contract):
        # Epoch ended 20 minutes ago (1200 seconds)
        from datetime import timedelta
        past_time = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(seconds=1200)

        with patch.object(mock_staking_contract, "get_next_epoch_start", return_value=past_time):
            result = mock_staking_contract.is_checkpoint_needed(grace_period_seconds=600)
            assert result is True


class TestGetServiceInfo:
    """Test get_service_info method."""

    def test_parses_service_info(self, mock_staking_contract):
        ts_now = int(time.time())
        ts_start = ts_now - 1000
        ts_checkpoint_val = ts_now - 500

        mock_staking_contract.call = MagicMock(
            return_value=("0xMultisig", "0xOwner", (10, 5), ts_start, 750, 0)
        )

        mock_activity_checker = MagicMock()
        mock_activity_checker.get_multisig_nonces.return_value = (15, 8)
        mock_activity_checker.liveness_ratio = 1e15  # Low ratio for easy testing
        mock_activity_checker.is_ratio_pass.return_value = True
        mock_staking_contract._activity_checker = mock_activity_checker

        with patch.object(mock_staking_contract, "ts_checkpoint", return_value=ts_checkpoint_val):
            with patch.object(mock_staking_contract, "get_required_requests", return_value=5):
                with patch.object(
                    mock_staking_contract,
                    "get_next_epoch_start",
                    return_value=datetime.fromtimestamp(ts_now + 3600, tz=timezone.utc),
                ):
                    result = mock_staking_contract.get_service_info(1)

        assert result["multisig_address"] == "0xMultisig"
        assert result["owner_address"] == "0xOwner"
        assert result["current_safe_nonce"] == 15
        assert result["current_mech_requests"] == 8
        assert result["last_checkpoint_safe_nonce"] == 10
        assert result["last_checkpoint_mech_requests"] == 5
        assert result["mech_requests_this_epoch"] == 3  # 8 - 5
        assert result["accrued_reward_wei"] == 750

    def test_handles_nested_tuple_response(self, mock_staking_contract):
        """Test handling of nested tuple response from web3."""
        ts_now = int(time.time())
        ts_start = ts_now - 1000

        # Response wrapped in extra tuple (as sometimes returned by web3)
        nested_response = [("0xMultisig", "0xOwner", (10, 5), ts_start, 750, 0)]
        mock_staking_contract.call = MagicMock(return_value=nested_response)

        mock_activity_checker = MagicMock()
        mock_activity_checker.get_multisig_nonces.return_value = (15, 8)
        mock_activity_checker.is_ratio_pass.return_value = True
        mock_staking_contract._activity_checker = mock_activity_checker

        with patch.object(mock_staking_contract, "ts_checkpoint", return_value=ts_now - 500):
            with patch.object(mock_staking_contract, "get_required_requests", return_value=5):
                with patch.object(
                    mock_staking_contract,
                    "get_next_epoch_start",
                    return_value=datetime.fromtimestamp(ts_now + 3600, tz=timezone.utc),
                ):
                    result = mock_staking_contract.get_service_info(1)

        assert result["multisig_address"] == "0xMultisig"
