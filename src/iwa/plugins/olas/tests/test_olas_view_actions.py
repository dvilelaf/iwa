"""Tests for Olas TUI View actions."""

from unittest.mock import MagicMock, patch

import pytest
from textual.app import App, ComposeResult

from iwa.plugins.olas.models import OlasConfig, Service, StakingStatus
from iwa.plugins.olas.tui.olas_view import OlasView

VALID_ADDR_1 = "0x78731D3Ca6b7E34aC0F824c42a7cC18A495cabaB"
VALID_ADDR_2 = "0x40A2aCCbd92BCA938b02010E17A5b8929b49130D"
VALID_ADDR_3 = "0x1111111111111111111111111111111111111111"


@pytest.fixture
def mock_wallet():
    """Mock wallet for testing."""
    wallet = MagicMock()
    wallet.balance_service = MagicMock()
    wallet.key_storage = MagicMock()
    wallet.get_native_balance_eth.return_value = 1.0
    wallet.balance_service.get_erc20_balance_wei.return_value = 10**18
    wallet.key_storage.find_stored_account.return_value = None
    wallet.master_account.address = VALID_ADDR_1
    return wallet


@pytest.fixture
def mock_olas_config():
    """Mock Olas configuration."""
    service = Service(
        service_id=1,
        service_name="Test Service",
        chain_name="gnosis",
        agent_address=VALID_ADDR_1,
        multisig_address=VALID_ADDR_2,
        service_owner_address=VALID_ADDR_3,
        staking_contract_address=VALID_ADDR_1,
    )
    config = OlasConfig(services={"gnosis:1": service})
    return config


class OlasTestApp(App):
    """Test app to host OlasView."""

    def __init__(self, wallet=None):
        """Initialize test app."""
        super().__init__()
        self.wallet = wallet

    def compose(self) -> ComposeResult:
        """Compose layout."""
        yield OlasView(self.wallet)


async def wait_for_workers(view, pilot):
    """Wait for all workers in OlasView to finish."""
    for _ in range(50):
        if not view.workers:
            break
        await pilot.pause(0.05)


@pytest.mark.asyncio
async def test_olas_view_actions_suite(mock_wallet, mock_olas_config):
    """Unified test for OlasView actions with robust mocking and synchronization."""
    with patch("iwa.core.models.Config") as mock_conf_cls:
        mock_conf = mock_conf_cls.return_value
        mock_conf.plugins = {"olas": mock_olas_config.model_dump()}

        # Patch both ServiceManager and StakingContract globally for the view
        with (
            patch("iwa.plugins.olas.service_manager.ServiceManager") as mock_sm_cls,
            patch("iwa.plugins.olas.contracts.staking.StakingContract"),
        ):
            mock_sm = mock_sm_cls.return_value
            # Default staking status to avoid TypeErrors during cards rendering
            mock_sm.get_staking_status.return_value = StakingStatus(
                is_staked=True,
                staking_state="STAKED",
                remaining_epoch_seconds=3600,
                accrued_reward_wei=10**18,
            )

            app = OlasTestApp(mock_wallet)
            async with app.run_test() as pilot:
                view = app.query_one(OlasView)
                await wait_for_workers(view, pilot)

                # 1. Claim Rewards
                mock_sm.claim_rewards.return_value = (True, 10**18)
                view.claim_rewards("gnosis:1")
                mock_sm.claim_rewards.assert_called_once()
                await wait_for_workers(view, pilot)  # success calls load_services

                # 2. Unstake
                mock_sm.unstake.return_value = True
                view.unstake_service("gnosis:1")
                mock_sm.unstake.assert_called_once()
                await wait_for_workers(view, pilot)

                # 3. Checkpoint
                mock_sm.call_checkpoint.return_value = True
                view.checkpoint_service("gnosis:1")
                mock_sm.call_checkpoint.assert_called_once()
                await wait_for_workers(view, pilot)

                # 4. Drain
                mock_sm.drain_service.return_value = {"safe": {"native": 1.0}}
                view.drain_service("gnosis:1")
                mock_sm.drain_service.assert_called_once()
                await wait_for_workers(view, pilot)

                # 5. Terminate (Wind Down)
                mock_sm.wind_down.return_value = True
                view.terminate_service("gnosis:1")
                mock_sm.wind_down.assert_called_once()
                await wait_for_workers(view, pilot)

                # 6. Stake (via modal simulation)
                from iwa.plugins.olas.constants import OLAS_TRADER_STAKING_CONTRACTS

                with patch.dict(
                    OLAS_TRADER_STAKING_CONTRACTS, {"gnosis": {"Contract": VALID_ADDR_1}}
                ):
                    with patch.object(app, "push_screen") as mock_push:
                        view.stake_service("gnosis:1")
                        assert mock_push.called

                        # Get callback from push_screen
                        callback = mock_push.call_args[0][1]  # modal, callback
                        mock_sm.stake.return_value = True
                        callback(VALID_ADDR_1)
                        mock_sm.stake.assert_called_once()
                        await wait_for_workers(view, pilot)
