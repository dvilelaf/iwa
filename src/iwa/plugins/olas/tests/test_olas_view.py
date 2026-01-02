"""Tests for Olas TUI View."""

from unittest.mock import patch

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Select

from iwa.plugins.olas.models import StakingStatus
from iwa.plugins.olas.tui.olas_view import OlasView
from iwa.tui.modals.base import CreateServiceModal, FundServiceModal

VALID_ADDR_1 = "0x78731D3Ca6b7E34aC0F824c42a7cC18A495cabaB"
VALID_ADDR_2 = "0x40A2aCCbd92BCA938b02010E17A5b8929b49130D"
VALID_ADDR_3 = "0x1111111111111111111111111111111111111111"


class OlasTestApp(App):
    """Test app to host OlasView."""

    def __init__(self, wallet=None):
        """Initialize test app."""
        super().__init__()
        self.wallet = wallet

    def compose(self) -> ComposeResult:
        """Compose layout."""
        yield OlasView(self.wallet)


@pytest.mark.asyncio
async def test_olas_view_initial_load(mock_wallet, mock_olas_config):
    """Test OlasView initial loading and rendering."""
    with patch("iwa.core.models.Config") as mock_config_cls:
        mock_config = mock_config_cls.return_value
        mock_config.plugins = {"olas": mock_olas_config.model_dump()}

        with (
            patch("iwa.plugins.olas.service_manager.ServiceManager") as mock_sm_cls,
            patch("iwa.core.pricing.PriceService") as mock_price_cls,
        ):
            mock_sm = mock_sm_cls.return_value
            # Default mock return value to avoid TypeErrors in background thread
            mock_sm.get_staking_status.return_value = StakingStatus(
                is_staked=False, staking_state="NOT_STAKED", remaining_epoch_seconds=3600
            )

            mock_sm.get_staking_status.return_value = StakingStatus(
                is_staked=True,
                staking_state="STAKED",
                staking_contract_address="0xStaking",
                staking_contract_name="Trader Staking",
                accrued_reward_wei=500000000000000000,
                liveness_ratio_passed=True,
                remaining_epoch_seconds=3600,
                epoch_number=1,
                unstake_available_at="2025-12-24T12:00:00Z",
            )
            mock_sm.get_service_state.return_value = "DEPLOYED"
            mock_price_cls.return_value.get_token_price.return_value = 1.23

            app = OlasTestApp(mock_wallet)
            async with app.run_test() as pilot:
                view = app.query_one(OlasView)
                assert view._chain == "gnosis"

                # Wait for loading worker
                await pilot.pause()

                # Verify service card exists
                assert bool(app.query("#card-gnosis_1"))
                # Label content check
                label = app.query_one(".service-title")
                assert "Test Service #1" in label.render().plain


@pytest.mark.asyncio
async def test_olas_view_chain_change(mock_wallet, mock_olas_config):
    """Test changing chain in OlasView."""
    with patch("iwa.core.models.Config") as mock_config_cls:
        mock_config = mock_config_cls.return_value
        mock_config.plugins = {"olas": mock_olas_config.model_dump()}

        with (
            patch("iwa.plugins.olas.service_manager.ServiceManager") as mock_sm_cls,
            patch("iwa.plugins.olas.constants.OLAS_TRADER_STAKING_CONTRACTS", {"ethereum": []}),
            patch("iwa.core.pricing.PriceService"),
        ):
            mock_sm = mock_sm_cls.return_value
            mock_sm.get_services_full.return_value = []
            mock_sm.get_staking_status.return_value = StakingStatus(
                is_staked=False, staking_state="NOT_STAKED", remaining_epoch_seconds=3600
            )
            mock_sm.get_service_state.return_value = "DEPLOYED"
            app = OlasTestApp(mock_wallet)
            async with app.run_test() as pilot:
                view = app.query_one(OlasView)

                # Wait for initial load to finish
                await pilot.pause(0.5)
                for _ in range(50):
                    if not any(w.name == "load_services" for w in view.workers):
                        break
                    await pilot.pause(0.1)

                # Change chain
                select = app.query_one("#olas-chain-select", Select)
                select.value = "ethereum"
                await pilot.pause()
                # Select.Changed will trigger load_services worker
                await pilot.pause()

                # Wait for worker to start and finish
                await pilot.pause(0.5)
                for _ in range(50):
                    if not any(w.name == "load_services" for w in view.workers):
                        break
                    await pilot.pause(0.1)

                # Ensure call_from_thread tasks are also finished
                await pilot.pause(0.5)

                assert view._chain == "ethereum"
                # Should show empty state since no eth services in mock
                assert len(view.query(".empty-state")) > 0


@pytest.mark.asyncio
async def test_olas_view_actions(mock_wallet, mock_olas_config):
    """Test button actions in OlasView."""
    with patch("iwa.core.models.Config") as mock_config_cls:
        mock_config = mock_config_cls.return_value
        mock_config.plugins = {"olas": mock_olas_config.model_dump()}

        with (
            patch("iwa.plugins.olas.service_manager.ServiceManager") as mock_sm_cls,
            patch("iwa.core.pricing.PriceService"),
        ):
            mock_sm = mock_sm_cls.return_value
            mock_sm.get_staking_status.return_value = StakingStatus(
                is_staked=True,
                staking_state="STAKED",
                accrued_reward_wei=10**18,
                remaining_epoch_seconds=0,  # Checkpoint pending
            )
            mock_sm.get_service_state.return_value = "DEPLOYED"

            app = OlasTestApp(mock_wallet)
            async with app.run_test() as pilot:
                await pilot.pause()

                # 1. Test Claim
                with patch.object(OlasView, "claim_rewards") as mock_claim:
                    await pilot.click("#claim-gnosis_1")
                    mock_claim.assert_called_with("gnosis:1")

                # 2. Test Unstake
                with patch.object(OlasView, "unstake_service") as mock_unstake:
                    await pilot.click("#unstake-gnosis_1")
                    mock_unstake.assert_called_with("gnosis:1")

                # 3. Test Checkpoint
                with patch.object(OlasView, "checkpoint_service") as mock_checkpoint:
                    await pilot.click("#checkpoint-gnosis_1")
                    mock_checkpoint.assert_called_with("gnosis:1")


@pytest.mark.asyncio
async def test_olas_view_create_service(mock_wallet, mock_olas_config):
    """Test clicking Create Service button."""
    with patch("iwa.core.models.Config") as mock_config_cls:
        mock_config = mock_config_cls.return_value
        mock_config.plugins = {"olas": mock_olas_config.model_dump()}

        with (
            patch("iwa.plugins.olas.service_manager.ServiceManager") as mock_sm_cls,
            patch("iwa.core.pricing.PriceService"),
        ):
            mock_sm = mock_sm_cls.return_value
            mock_sm.get_staking_status.return_value = StakingStatus(
                is_staked=False, staking_state="NOT_STAKED"
            )
            mock_sm.get_service_state.return_value = "DEPLOYED"

            app = OlasTestApp(mock_wallet)
            async with app.run_test() as pilot:
                # Wait for worker
                view = app.query_one(OlasView)
                for _ in range(10):
                    if not any(w.name == "load_services" for w in view.workers):
                        break
                    await pilot.pause(0.1)

                # Patch push_screen on the app instance
                with patch.object(app, "push_screen") as mock_push:
                    await pilot.click("#olas-create-service-btn")
                    await pilot.pause()

                    # Verify push_screen was called with a CreateServiceModal
                    assert mock_push.called
                    modal = mock_push.call_args[0][0]
                    assert isinstance(modal, CreateServiceModal)


@pytest.mark.asyncio
async def test_olas_view_fund_service(mock_wallet, mock_olas_config):
    """Test showing fund service modal."""
    with patch("iwa.core.models.Config") as mock_config_cls:
        mock_config = mock_config_cls.return_value
        mock_config.plugins = {"olas": mock_olas_config.model_dump()}

        with (
            patch("iwa.plugins.olas.service_manager.ServiceManager") as mock_sm_cls,
            patch("iwa.core.pricing.PriceService"),
        ):
            mock_sm = mock_sm_cls.return_value
            mock_sm.get_staking_status.return_value = StakingStatus(
                is_staked=False, staking_state="NOT_STAKED"
            )
            mock_sm.get_service_state.return_value = "DEPLOYED"

            app = OlasTestApp(mock_wallet)
            async with app.run_test() as pilot:
                # Wait for worker
                view = app.query_one(OlasView)
                for _ in range(10):
                    if not any(w.name == "load_services" for w in view.workers):
                        break
                    await pilot.pause(0.1)

                # Patch push_screen on the app instance
                with patch.object(app, "push_screen") as mock_push:
                    await pilot.click("#fund-gnosis_1")
                    await pilot.pause()

                    # Verify push_screen was called with a FundServiceModal
                    assert mock_push.called
                    modal = mock_push.call_args[0][0]
                    assert isinstance(modal, FundServiceModal)


@pytest.mark.asyncio
async def test_olas_view_error_states(mock_wallet):
    """Test OlasView error handling."""
    # 1. No wallet
    app = OlasTestApp(None)
    async with app.run_test():
        label = app.query_one(".empty-state")
        assert "Wallet not available" in label.render().plain

    # 2. No Olas configured
    with patch("iwa.core.models.Config") as mock_config_cls:
        mock_config = mock_config_cls.return_value
        mock_config.plugins = {}
        app = OlasTestApp(mock_wallet)
        async with app.run_test():
            label = app.query_one(".empty-state")
            assert "No Olas services configured" in label.render().plain
