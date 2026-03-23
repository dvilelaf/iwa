"""Tests for SwapMixin gap coverage: _prepare_swap_amount, balance tolerance, _ensure_allowance, execution failure."""

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from iwa.core.services.transfer.swap import OrderType, SwapMixin


class MockTransferService(SwapMixin):
    """Dummy class to test SwapMixin methods."""

    def __init__(self):
        self.balance_service = MagicMock()
        self.account_service = MagicMock()
        self.key_storage = MagicMock()
        self.get_erc20_allowance = MagicMock()
        self.approve_erc20 = MagicMock()
        self._get_token_price_info = MagicMock(return_value=(1.0, 1.0))


@pytest.fixture
def svc():
    return MockTransferService()


# ---- _prepare_swap_amount tests ----


class TestPrepareSwapAmount:
    def test_buy_order_without_amount_raises(self, svc):
        """BUY orders must specify an amount."""
        with pytest.raises(ValueError, match="Amount must be specified for buy orders"):
            svc._prepare_swap_amount("user", None, "olas", "wxdai", "gnosis", OrderType.BUY)

    def test_sell_order_without_amount_returns_full_balance(self, svc):
        """SELL order with amount_eth=None returns the entire token balance."""
        svc.balance_service.get_erc20_balance_wei.return_value = 5 * 10**18
        result = svc._prepare_swap_amount("user", None, "olas", "wxdai", "gnosis", OrderType.SELL)
        assert result == 5 * 10**18
        svc.balance_service.get_erc20_balance_wei.assert_called_once_with("user", "olas", "gnosis")

    @patch("iwa.core.services.transfer.swap.ChainInterfaces")
    @patch("iwa.core.services.transfer.swap.ERC20Contract")
    def test_sell_order_with_amount_converts_correctly(self, mock_erc20, mock_ci, svc):
        """SELL order with explicit amount converts using token decimals."""
        mock_chain_interface = MagicMock()
        mock_chain_interface.chain.get_token_address.return_value = "0xTokenAddr"
        mock_ci.return_value.get.return_value = mock_chain_interface
        mock_erc20.return_value.decimals = 6  # USDC-like

        result = svc._prepare_swap_amount("user", 10.5, "usdc", "wxdai", "gnosis", OrderType.SELL)
        assert result == int(Decimal("10.5") * Decimal(10**6))

    @patch("iwa.core.services.transfer.swap.ChainInterfaces")
    @patch("iwa.core.services.transfer.swap.ERC20Contract")
    def test_prepare_swap_amount_defaults_to_18_decimals_on_error(self, mock_erc20, mock_ci, svc):
        """Falls back to 18 decimals if ERC20Contract raises."""
        mock_chain_interface = MagicMock()
        mock_chain_interface.chain.get_token_address.return_value = "0xTokenAddr"
        mock_ci.return_value.get.return_value = mock_chain_interface
        mock_erc20.side_effect = Exception("RPC down")

        result = svc._prepare_swap_amount("user", 1.0, "olas", "wxdai", "gnosis", OrderType.SELL)
        assert result == 10**18


# ---- Balance tolerance check tests ----


class TestBalanceTolerance:
    @pytest.mark.asyncio
    @patch("iwa.core.services.transfer.swap.log_transaction")
    @patch("iwa.core.services.transfer.swap.CowSwap")
    @patch("iwa.core.services.transfer.swap.ChainInterfaces")
    async def test_tolerance_adjusts_amount(self, mock_ci, mock_cow_cls, mock_log, svc):
        """When balance is slightly less than requested, amount is adjusted."""
        balance = 10**18
        requested = balance + 10**13  # Tiny diff within tolerance

        account_mock = MagicMock()
        account_mock.address = "0xUser"
        svc.account_service.resolve_account.return_value = account_mock
        svc.key_storage.get_signer.return_value = "signer"
        svc.balance_service.get_erc20_balance_wei.return_value = balance
        svc.get_erc20_allowance.return_value = requested + 1

        cow_instance = AsyncMock()
        mock_cow_cls.return_value = cow_instance
        cow_instance.swap.return_value = {"txHash": "0x1", "executedSellAmount": "0", "executedBuyAmount": "0", "quote": {}}

        await svc.swap(
            account_address_or_tag="user",
            amount_wei=requested,
            sell_token_name="olas",
            buy_token_name="wxdai",
        )

        # The swap call should use the actual balance (adjusted amount)
        call_kwargs = cow_instance.swap.call_args.kwargs
        assert call_kwargs["amount_wei"] == balance

    @pytest.mark.asyncio
    @patch("iwa.core.services.transfer.swap.CowSwap")
    @patch("iwa.core.services.transfer.swap.ChainInterfaces")
    async def test_insufficient_balance_raises(self, mock_ci, mock_cow_cls, svc):
        """When balance is significantly less than requested, raises ValueError."""
        balance = 10**18
        requested = balance + 10**18  # Large diff, NOT within tolerance

        account_mock = MagicMock()
        account_mock.address = "0xUser"
        svc.account_service.resolve_account.return_value = account_mock
        svc.key_storage.get_signer.return_value = "signer"
        svc.balance_service.get_erc20_balance_wei.return_value = balance

        with pytest.raises(ValueError, match="Insufficient .* balance"):
            await svc.swap(
                account_address_or_tag="user",
                amount_wei=requested,
                sell_token_name="olas",
                buy_token_name="wxdai",
            )

    @pytest.mark.asyncio
    @patch("iwa.core.services.transfer.swap.CowSwap")
    @patch("iwa.core.services.transfer.swap.ChainInterfaces")
    async def test_none_balance_raises(self, mock_ci, mock_cow_cls, svc):
        """When balance is None, raises ValueError."""
        account_mock = MagicMock()
        account_mock.address = "0xUser"
        svc.account_service.resolve_account.return_value = account_mock
        svc.key_storage.get_signer.return_value = "signer"
        svc.balance_service.get_erc20_balance_wei.return_value = None

        with pytest.raises(ValueError, match="Could not retrieve balance"):
            await svc.swap(
                account_address_or_tag="user",
                amount_wei=10**18,
                sell_token_name="olas",
                buy_token_name="wxdai",
            )


# ---- _ensure_allowance_for_swap tests ----


class TestEnsureAllowance:
    @pytest.mark.asyncio
    @patch("iwa.core.services.transfer.swap.ChainInterfaces")
    async def test_sufficient_allowance_skips_approval(self, mock_ci, svc):
        """If allowance >= required, no approval is called."""
        svc.get_erc20_allowance.return_value = 10**18 + 100
        cow = AsyncMock()

        result = await svc._ensure_allowance_for_swap(
            "user", "olas", "wxdai", "gnosis", 10**18, OrderType.SELL, cow
        )

        assert result == 10**18
        svc.approve_erc20.assert_not_called()

    @pytest.mark.asyncio
    @patch("iwa.core.services.transfer.swap.ChainInterfaces")
    async def test_insufficient_allowance_triggers_approval(self, mock_ci, svc):
        """If allowance < required, approve_erc20 is called."""
        svc.get_erc20_allowance.return_value = 0
        cow = AsyncMock()

        result = await svc._ensure_allowance_for_swap(
            "user", "olas", "wxdai", "gnosis", 10**18, OrderType.SELL, cow
        )

        assert result == 10**18
        svc.approve_erc20.assert_called_once()

    @pytest.mark.asyncio
    @patch("iwa.core.services.transfer.swap.ChainInterfaces")
    async def test_buy_order_uses_max_sell_amount(self, mock_ci, svc):
        """BUY order calculates required amount via cow.get_max_sell_amount_wei."""
        svc.get_erc20_allowance.return_value = 0
        mock_chain_interface = MagicMock()
        mock_chain_interface.chain.get_token_address.side_effect = lambda name: f"0x{name}"
        mock_ci.return_value.get.return_value = mock_chain_interface

        cow = AsyncMock()
        cow.get_max_sell_amount_wei.return_value = 2 * 10**18

        result = await svc._ensure_allowance_for_swap(
            "user", "olas", "wxdai", "gnosis", 10**18, OrderType.BUY, cow
        )

        assert result == 2 * 10**18
        svc.approve_erc20.assert_called_once()


# ---- Swap execution failure tests ----


class TestSwapExecutionFailure:
    @pytest.mark.asyncio
    @patch("iwa.core.services.transfer.swap.CowSwap")
    @patch("iwa.core.services.transfer.swap.ChainInterfaces")
    async def test_swap_returns_none_on_cowswap_failure(self, mock_ci, mock_cow_cls, svc):
        """When CowSwap.swap() returns None, swap() returns None."""
        account_mock = MagicMock()
        account_mock.address = "0xUser"
        svc.account_service.resolve_account.return_value = account_mock
        svc.key_storage.get_signer.return_value = "signer"
        svc.balance_service.get_erc20_balance_wei.return_value = 10**18
        svc.get_erc20_allowance.return_value = 10**18

        cow_instance = AsyncMock()
        mock_cow_cls.return_value = cow_instance
        cow_instance.swap.return_value = None

        result = await svc.swap(
            account_address_or_tag="user",
            amount_wei=10**18,
            sell_token_name="olas",
            buy_token_name="wxdai",
        )

        assert result is None

    @pytest.mark.asyncio
    @patch("iwa.core.services.transfer.swap.CowSwap")
    @patch("iwa.core.services.transfer.swap.ChainInterfaces")
    async def test_swap_returns_none_when_no_signer(self, mock_ci, mock_cow_cls, svc):
        """When signer cannot be retrieved, swap() returns None."""
        account_mock = MagicMock()
        account_mock.address = "0xUser"
        svc.account_service.resolve_account.return_value = account_mock
        svc.key_storage.get_signer.return_value = None
        svc.balance_service.get_erc20_balance_wei.return_value = 10**18

        result = await svc.swap(
            account_address_or_tag="user",
            amount_wei=10**18,
            sell_token_name="olas",
            buy_token_name="wxdai",
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_swap_rejects_both_amount_types(self, svc):
        """Specifying both amount_eth and amount_wei raises ValueError."""
        with pytest.raises(ValueError, match="Specify either"):
            await svc.swap("user", amount_eth=1.0, amount_wei=10**18)
