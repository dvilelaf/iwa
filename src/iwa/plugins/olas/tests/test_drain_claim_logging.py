"""Tests for claim_rewards logging with EUR pricing."""

from unittest.mock import MagicMock, patch

import pytest


ADDR_STAKING = "0x1111111111111111111111111111111111111111"
ADDR_MULTISIG = "0x2222222222222222222222222222222222222222"
ADDR_OWNER = "0x3333333333333333333333333333333333333333"


@pytest.fixture
def drain_mixin():
    """Create a DrainManagerMixin instance with mocked dependencies."""
    from iwa.plugins.olas.service_manager.drain import DrainManagerMixin

    mixin = DrainManagerMixin()

    # Mock service
    service = MagicMock()
    service.service_id = 1
    service.staking_contract_address = ADDR_STAKING
    service.multisig_address = ADDR_MULTISIG
    service.service_owner_address = ADDR_OWNER
    service.service_name = "test_trader"
    service.key = "gnosis:1"
    mixin.service = service
    mixin.chain_name = "gnosis"

    # Mock wallet
    wallet = MagicMock()
    wallet.master_account.address = ADDR_OWNER
    mixin.wallet = wallet

    return mixin


def test_claim_rewards_logs_with_price(drain_mixin):
    """Verify that a successful claim calls log_transaction with OLAS price."""
    claimed_amount_wei = 10_000_000_000_000_000_000  # 10 OLAS

    mock_staking = MagicMock()
    from iwa.plugins.olas.contracts.staking import StakingState

    mock_staking.get_staking_state.return_value = StakingState.STAKED
    mock_staking.calculate_staking_reward.return_value = claimed_amount_wei
    mock_staking.prepare_claim_tx.return_value = {"to": ADDR_STAKING, "data": b"claim"}
    mock_staking.extract_events.return_value = [
        {"name": "RewardClaimed", "args": {"amount": claimed_amount_wei}}
    ]

    mock_receipt = {"transactionHash": MagicMock(hex=lambda: "0xabc123")}
    drain_mixin.wallet.sign_and_send_transaction.return_value = (True, mock_receipt)

    with (
        patch("iwa.plugins.olas.service_manager.drain.response_cache"),
        patch("iwa.core.db.log_transaction") as mock_log_tx,
        patch("iwa.core.pricing.PriceService") as mock_price_cls,
    ):
        mock_price_cls.return_value.get_token_price.return_value = 1.50

        success, amount = drain_mixin.claim_rewards(staking_contract=mock_staking)

        assert success is True
        assert amount == claimed_amount_wei

        # Verify log_transaction was called with correct pricing
        mock_log_tx.assert_called_once()
        call_kwargs = mock_log_tx.call_args[1]
        assert call_kwargs["token"] == "OLAS"
        assert call_kwargs["amount_wei"] == claimed_amount_wei
        assert call_kwargs["price_eur"] == 1.50
        assert call_kwargs["value_eur"] == 15.0  # 10 OLAS * 1.50
        assert "olas_claim_rewards" in call_kwargs["tags"]
        assert "staking_reward" in call_kwargs["tags"]
        assert call_kwargs["tx_hash"] == "0xabc123"
        assert call_kwargs["chain"] == "gnosis"


def test_claim_rewards_logs_without_price_on_failure(drain_mixin):
    """Verify that claim still works even if price service fails."""
    claimed_amount_wei = 5_000_000_000_000_000_000  # 5 OLAS

    mock_staking = MagicMock()
    from iwa.plugins.olas.contracts.staking import StakingState

    mock_staking.get_staking_state.return_value = StakingState.STAKED
    mock_staking.calculate_staking_reward.return_value = claimed_amount_wei
    mock_staking.prepare_claim_tx.return_value = {"to": ADDR_STAKING, "data": b"claim"}
    mock_staking.extract_events.return_value = [
        {"name": "RewardClaimed", "args": {"amount": claimed_amount_wei}}
    ]

    mock_receipt = {"transactionHash": MagicMock(hex=lambda: "0xdef456")}
    drain_mixin.wallet.sign_and_send_transaction.return_value = (True, mock_receipt)

    with (
        patch("iwa.plugins.olas.service_manager.drain.response_cache"),
        patch("iwa.core.db.log_transaction") as mock_log_tx,
        patch("iwa.core.pricing.PriceService") as mock_price_cls,
    ):
        mock_price_cls.return_value.get_token_price.return_value = None

        success, amount = drain_mixin.claim_rewards(staking_contract=mock_staking)

        assert success is True
        assert amount == claimed_amount_wei

        # log_transaction still called, but value_eur is None
        mock_log_tx.assert_called_once()
        call_kwargs = mock_log_tx.call_args[1]
        assert call_kwargs["price_eur"] is None
        assert call_kwargs["value_eur"] is None
        assert call_kwargs["token"] == "OLAS"
