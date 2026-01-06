"""Tests for Olas service staking and unstaking functionality."""

from unittest.mock import MagicMock, patch

import pytest
from textual.app import App, ComposeResult
from textual.containers import VerticalScroll

from iwa.plugins.olas.contracts.service import ServiceState
from iwa.plugins.olas.contracts.staking import StakingState
from iwa.plugins.olas.models import Service, StakingStatus
from iwa.plugins.olas.service_manager import ServiceManager
from iwa.plugins.olas.tui.olas_view import OlasView

VALID_ADDR = "0x78731D3Ca6b7E34aC0F824c42a7cC18A495cabaB"


@pytest.fixture
def mock_wallet():
    """Mock wallet."""
    w = MagicMock()
    w.master_account.address = VALID_ADDR
    w.sign_and_send_transaction.return_value = (True, {"status": 1})
    w.key_storage = MagicMock()
    w.key_storage._password = "pass"
    w.balance_service = MagicMock()
    w.drain.return_value = {"tx": "0x123"}
    return w


# === SERVICE MANAGER STAKE/UNSTAKE SIMPLE FAILURES ===


def test_sm_unstake_not_staked(mock_wallet):
    """Cover unstake when not staked (lines 736-738)."""
    with patch("iwa.core.models.Config"):
        sm = ServiceManager(mock_wallet)
        sm.service = Service(
            service_name="t", chain_name="gnosis", service_id=1, multisig_address=VALID_ADDR
        )

        mock_staking = MagicMock()
        mock_staking.get_staking_state.return_value = StakingState.NOT_STAKED

        result = sm.unstake(mock_staking)
        assert result is False


def test_sm_unstake_tx_fails(mock_wallet):
    """Cover unstake transaction failure (lines 766-768)."""
    with patch("iwa.core.models.Config"):
        sm = ServiceManager(mock_wallet)
        sm.service = Service(
            service_name="t", chain_name="gnosis", service_id=1, multisig_address=VALID_ADDR
        )

        mock_staking = MagicMock()
        mock_staking.get_staking_state.return_value = StakingState.STAKED
        mock_staking.get_service_info.return_value = {"ts_start": 1}
        mock_staking.min_staking_duration = 0
        mock_staking.prepare_unstake_tx.return_value = {"to": VALID_ADDR}

        mock_wallet.sign_and_send_transaction.return_value = (False, None)

        result = sm.unstake(mock_staking)
        assert result is False


# === SERVICE MANAGER STAKING STATUS EDGE CASES (lines 843-891) ===


def test_sm_get_staking_status_no_staking_address(mock_wallet):
    """Cover get_staking_status with no staking address (lines 831)."""
    with patch("iwa.core.models.Config"):
        sm = ServiceManager(mock_wallet)
        sm.service = Service(
            service_name="t", chain_name="gnosis", service_id=1, staking_contract_address=VALID_ADDR
        )

        # Contract load fails
        with patch(
            "iwa.plugins.olas.service_manager.staking.StakingContract",
            side_effect=Exception("fail"),
        ):
            status = sm.get_staking_status()
            assert status.staking_state == "ERROR"


def test_sm_get_staking_status_with_full_info(mock_wallet):
    """Cover get_staking_status with complete info (lines 866-891)."""
    with patch("iwa.core.models.Config"):
        sm = ServiceManager(mock_wallet)
        sm.service = Service(
            service_name="t", chain_name="gnosis", service_id=1, staking_contract_address=VALID_ADDR
        )

        mock_staking = MagicMock()
        mock_staking.get_staking_state.return_value = StakingState.STAKED
        mock_staking.activity_checker_address = VALID_ADDR
        mock_staking.activity_checker.liveness_ratio = 10
        mock_staking.get_epoch_counter.return_value = 5
        mock_staking.min_staking_duration = 86400
        mock_staking.get_service_info.return_value = {
            "ts_start": 1000,
            "mech_requests_this_epoch": 3,
            "required_mech_requests": 5,
            "remaining_mech_requests": 2,
            "has_enough_requests": False,
            "liveness_ratio_passed": True,
            "accrued_reward_wei": 1000000,
            "epoch_end_utc": None,
            "remaining_epoch_seconds": 3600,
        }

        with (
            patch(
                "iwa.plugins.olas.service_manager.staking.StakingContract",
                return_value=mock_staking,
            ),
            patch("iwa.plugins.olas.service_manager.staking.Web3") as mock_web3,
        ):
            mock_web3.from_wei.return_value = 0.001
            status = sm.get_staking_status()
            assert status.is_staked is True
            assert status.epoch_number == 5


# === SERVICE MANAGER CLAIM/WITHDRAW (lines 936-979) ===


def test_sm_claim_rewards_no_service(mock_wallet):
    """Cover claim_rewards with no service (lines 936-938)."""
    with patch("iwa.core.models.Config"):
        sm = ServiceManager(mock_wallet)
        sm.service = None

        success, amount = sm.claim_rewards()
        assert success is False
        assert amount == 0


def test_sm_claim_rewards_no_staking_address(mock_wallet):
    """Cover claim_rewards with no staking address (lines 939-943)."""
    with patch("iwa.core.models.Config"):
        sm = ServiceManager(mock_wallet)
        sm.service = Service(
            service_name="t", chain_name="gnosis", service_id=1, staking_contract_address=None
        )

        success, amount = sm.claim_rewards()
        assert success is False


def test_sm_claim_rewards_tx_fails(mock_wallet):
    """Cover claim_rewards transaction failure (lines 967-968)."""
    with patch("iwa.core.models.Config"):
        sm = ServiceManager(mock_wallet)
        sm.service = Service(
            service_name="t",
            chain_name="gnosis",
            service_id=1,
            staking_contract_address=VALID_ADDR,
            multisig_address=VALID_ADDR,
        )

        mock_staking = MagicMock()
        mock_staking.prepare_claim_tx.return_value = {"to": VALID_ADDR}

        mock_wallet.sign_and_send_transaction.return_value = (False, None)

        with patch("iwa.plugins.olas.service_manager.StakingContract", return_value=mock_staking):
            success, amount = sm.claim_rewards()
            assert success is False


# === SERVICE MANAGER SPIN_UP STATE TRANSITIONS (lines 1188-1241) ===


def test_sm_spin_up_state_mismatch_after_activation(mock_wallet):
    """Cover spin_up state mismatch after activation (lines 1188-1191)."""
    with patch("iwa.core.models.Config"):
        sm = ServiceManager(mock_wallet)
        sm.service = Service(service_name="t", chain_name="gnosis", service_id=1)

        mock_reg = MagicMock()
        # First call: PRE_REGISTRATION, second call: still PRE_REGISTRATION (mismatch)
        mock_reg.get_service.side_effect = [
            {"state": ServiceState.PRE_REGISTRATION},
            {"state": ServiceState.PRE_REGISTRATION},
        ]

        with (
            patch.object(sm, "registry", mock_reg),
            patch.object(sm, "activate_registration", return_value=True),
        ):
            result = sm.spin_up()
            assert result is False


def test_sm_spin_up_registration_fails(mock_wallet):
    """Cover spin_up registration failure (lines 1199-1201)."""
    with patch("iwa.core.models.Config"):
        sm = ServiceManager(mock_wallet)
        sm.service = Service(service_name="t", chain_name="gnosis", service_id=1)

        mock_reg = MagicMock()
        mock_reg.get_service.return_value = {"state": ServiceState.ACTIVE_REGISTRATION}

        with (
            patch.object(sm, "registry", mock_reg),
            patch.object(sm, "register_agent", return_value=False),
        ):
            result = sm.spin_up()
            assert result is False


def test_sm_spin_up_deploy_fails(mock_wallet):
    """Cover spin_up deploy failure (lines 1216-1218)."""
    with patch("iwa.core.models.Config"):
        sm = ServiceManager(mock_wallet)
        sm.service = Service(service_name="t", chain_name="gnosis", service_id=1)

        mock_reg = MagicMock()
        mock_reg.get_service.return_value = {"state": ServiceState.FINISHED_REGISTRATION}

        with patch.object(sm, "registry", mock_reg), patch.object(sm, "deploy", return_value=None):
            result = sm.spin_up()
            assert result is False


# === SERVICE MANAGER WIND DOWN TRANSITIONS (lines 1306-1334) ===


def test_sm_wind_down_terminate_fails(mock_wallet):
    """Cover wind_down terminate failure (lines 1299-1301)."""
    with patch("iwa.core.models.Config"):
        sm = ServiceManager(mock_wallet)
        sm.service = Service(service_name="t", chain_name="gnosis", service_id=1)

        mock_reg = MagicMock()
        mock_reg.get_service.return_value = {"state": ServiceState.DEPLOYED}

        with (
            patch.object(sm, "registry", mock_reg),
            patch.object(sm, "terminate", return_value=False),
        ):
            result = sm.wind_down()
            assert result is False


def test_sm_wind_down_unbond_fails(mock_wallet):
    """Cover wind_down unbond failure (lines 1315-1317)."""
    with patch("iwa.core.models.Config"):
        sm = ServiceManager(mock_wallet)
        sm.service = Service(service_name="t", chain_name="gnosis", service_id=1)

        mock_reg = MagicMock()
        mock_reg.get_service.return_value = {"state": ServiceState.TERMINATED_BONDED}

        with patch.object(sm, "registry", mock_reg), patch.object(sm, "unbond", return_value=False):
            result = sm.wind_down()
            assert result is False


# === OLAS VIEW EDGE CASES (lines 233-257, 319-323) ===


class OlasTestApp(App):
    """Test App for OlasView."""

    def __init__(self, wallet=None):
        """Initialize test app."""
        super().__init__()
        self.wallet = wallet

    def compose(self) -> ComposeResult:
        """Compose layout."""
        yield VerticalScroll(OlasView(self.wallet), id="root")


@pytest.mark.asyncio
async def test_view_render_exception(mock_wallet):
    """Cover _render_services exception handling (lines 233-235)."""
    with patch("iwa.core.models.Config"):
        app = OlasTestApp(mock_wallet)
        async with app.run_test():
            view = app.query_one(OlasView)

            # Force exception by passing invalid data
            with patch.object(view, "query_one", side_effect=Exception("test")):
                # Should not raise, just logs
                await view._render_services([("k", MagicMock(), None)])


@pytest.mark.asyncio
async def test_view_mount_cards_exception(mock_wallet):
    """Cover _mount_cards exception handling (lines 239-247)."""
    with patch("iwa.core.models.Config"):
        app = OlasTestApp(mock_wallet)
        async with app.run_test():
            view = app.query_one(OlasView)

            with patch.object(view, "query_one", side_effect=Exception("test")):
                # Should not raise
                view._mount_cards([MagicMock()])


@pytest.mark.asyncio
async def test_view_mount_error_exception(mock_wallet):
    """Cover _mount_error exception handling (lines 255-257)."""
    with patch("iwa.core.models.Config"):
        app = OlasTestApp(mock_wallet)
        async with app.run_test():
            view = app.query_one(OlasView)

            with patch.object(view, "query_one", side_effect=Exception("test")):
                # Should not raise
                view._mount_error("test error")


@pytest.mark.asyncio
async def test_view_create_service_card_variants(mock_wallet):
    """Cover _create_service_card with various inputs (lines 319-323)."""
    with patch("iwa.core.models.Config"):
        app = OlasTestApp(mock_wallet)
        async with app.run_test():
            view = app.query_one(OlasView)

            service = Service(
                service_name="test", chain_name="gnosis", service_id=1, multisig_address=VALID_ADDR
            )

            # With staking status
            status = StakingStatus(
                is_staked=True, staking_state="STAKED", accrued_reward_wei=1000000
            )
            card = view._create_service_card("gnosis:1", service, status)
            assert card is not None

            # Without staking status
            card2 = view._create_service_card("gnosis:2", service, None)
            assert card2 is not None
