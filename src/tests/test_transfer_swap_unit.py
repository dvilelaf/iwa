"""Unit tests for SwapMixin.swap logic."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from iwa.core.services.transfer.swap import OrderType, SwapMixin


# Dummy class to mixin
class MockTransferService(SwapMixin):
    def __init__(self):
        self.balance_service = MagicMock()
        self.account_service = MagicMock()
        self.key_storage = MagicMock()
        self.wallet = MagicMock()
        self.get_erc20_allowance = MagicMock()
        self.approve_erc20 = MagicMock()


@pytest.fixture
def transfer_service():
    return MockTransferService()


@pytest.fixture
def mock_chain_interfaces():
    with patch("iwa.core.services.transfer.swap.ChainInterfaces") as mock:
        yield mock


@pytest.fixture
def mock_cow_swap():
    with patch("iwa.core.services.transfer.swap.CowSwap") as mock:
        yield mock


@pytest.fixture
def mock_erc20_contract():
    with patch("iwa.core.services.transfer.swap.ERC20Contract") as mock:
        yield mock


@pytest.fixture
def mock_log_transaction():
    with patch("iwa.core.services.transfer.swap.log_transaction") as mock:
        yield mock


@pytest.mark.asyncio
async def test_swap_happy_path(
    transfer_service, mock_chain_interfaces, mock_cow_swap, mock_log_transaction
):
    """Test successful swap with sufficient allowance."""
    # Setup
    account_mock = MagicMock()
    account_mock.address = "0xUser"
    transfer_service.account_service.resolve_account.return_value = account_mock
    transfer_service.key_storage.get_signer.return_value = "signer"
    transfer_service.key_storage.get_signer.return_value = "signer"
    transfer_service.get_erc20_allowance.return_value = 10**18 + 100  # Sufficient

    # Mock balance for pre-swap check
    transfer_service.balance_service.get_erc20_balance_wei.return_value = 2 * 10**18
    transfer_service.balance_service.get_native_balance_wei.return_value = 2 * 10**18

    # Mock CowSwap instance
    cow_instance = AsyncMock()
    mock_cow_swap.return_value = cow_instance

    # Mock Swap Result
    swap_result = {
        "executedSellAmount": "1000000000000000000",
        "executedBuyAmount": "2000000",
        "quote": {"sellTokenPrice": 1.0, "buyTokenPrice": 500.0},
        "txHash": "0xHash",
    }
    cow_instance.swap.return_value = swap_result

    # Execute
    result = await transfer_service.swap(
        account_address_or_tag="user",
        amount_eth=1.0,
        sell_token_name="WETH",
        buy_token_name="USDC",
        chain_name="gnosis",
    )

    # Verify
    assert result == swap_result
    # Check allowance was checked
    transfer_service.get_erc20_allowance.assert_called_once()
    # Check approval was skipped
    transfer_service.approve_erc20.assert_not_called()
    # Check logs
    mock_log_transaction.assert_called_once()
    assert result["analytics"]["value_change_pct"] != "N/A"


@pytest.mark.asyncio
async def test_swap_insufficient_allowance(transfer_service, mock_chain_interfaces, mock_cow_swap):
    """Test approval is called when allowance is insufficient."""
    # Setup
    account_mock = MagicMock()
    account_mock.address = "0xUser"
    transfer_service.account_service.resolve_account.return_value = account_mock
    transfer_service.key_storage.get_signer.return_value = "signer"
    transfer_service.key_storage.get_signer.return_value = "signer"
    transfer_service.get_erc20_allowance.return_value = 0  # Insufficient

    # Mock balance for pre-swap check
    transfer_service.balance_service.get_erc20_balance_wei.return_value = 2 * 10**18

    cow_instance = AsyncMock()
    mock_cow_swap.return_value = cow_instance
    cow_instance.swap.return_value = {"txHash": "0xHash"}

    # Execute
    await transfer_service.swap(
        account_address_or_tag="user", amount_eth=1.0, sell_token_name="WETH", buy_token_name="USDC"
    )

    # Verify Approval
    transfer_service.approve_erc20.assert_called_once()


@pytest.mark.asyncio
async def test_swap_full_balance(transfer_service, mock_chain_interfaces, mock_cow_swap):
    """Test swapping entire balance (amount_eth=None)."""
    # Setup
    account_mock = MagicMock()
    account_mock.address = "0xUser"
    transfer_service.account_service.resolve_account.return_value = account_mock
    transfer_service.key_storage.get_signer.return_value = "signer"

    # Mock balance
    transfer_service.balance_service.get_erc20_balance_wei.return_value = 500
    transfer_service.get_erc20_allowance.return_value = 1000

    cow_instance = AsyncMock()
    mock_cow_swap.return_value = cow_instance
    cow_instance.swap.return_value = {"txHash": "0xHash"}

    # Execute
    await transfer_service.swap(
        account_address_or_tag="user",
        amount_eth=None,
        sell_token_name="WETH",
        buy_token_name="USDC",
    )

    # Verify correct amount passed to swap
    cow_instance.swap.assert_called_with(
        amount_wei=500, sell_token_name="WETH", buy_token_name="USDC", order_type=OrderType.SELL
    )
