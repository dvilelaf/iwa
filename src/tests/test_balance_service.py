"""Tests for BalanceService."""

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def mock_chain_interfaces():
    with patch("iwa.core.services.balance.ChainInterfaces") as mock:
        instance = mock.return_value
        gnosis_interface = MagicMock()
        gnosis_interface.chain.name = "Gnosis"
        gnosis_interface.get_native_balance_eth.return_value = 1.5
        gnosis_interface.get_native_balance_wei.return_value = 1500000000000000000
        instance.get.return_value = gnosis_interface
        yield instance


@pytest.fixture
def mock_account_service():
    mock = MagicMock()
    mock.get_token_address.return_value = "0xTokenAddress"
    mock.resolve_account.return_value = MagicMock(address="0xAccountAddress")
    return mock


@pytest.fixture
def mock_key_storage():
    return MagicMock()


@pytest.fixture
def balance_service(mock_key_storage, mock_account_service):
    from iwa.core.services.balance import BalanceService

    return BalanceService(mock_key_storage, mock_account_service)


def test_get_native_balance_eth(balance_service, mock_chain_interfaces, mock_account_service):
    """Test get_native_balance_eth returns correct value."""
    result = balance_service.get_native_balance_eth("0xAccount", "gnosis")

    assert result == 1.5
    # Now resolves account first, so expects resolved address
    mock_chain_interfaces.get.return_value.get_native_balance_eth.assert_called_with(
        "0xAccountAddress"
    )
    mock_account_service.resolve_account.assert_called_with("0xAccount")


def test_get_native_balance_wei(balance_service, mock_chain_interfaces, mock_account_service):
    """Test get_native_balance_wei returns correct value."""
    result = balance_service.get_native_balance_wei("0xAccount", "gnosis")

    assert result == 1500000000000000000
    # Now resolves account first, so expects resolved address
    mock_chain_interfaces.get.return_value.get_native_balance_wei.assert_called_with(
        "0xAccountAddress"
    )
    mock_account_service.resolve_account.assert_called_with("0xAccount")


def test_get_erc20_balance_eth_success(
    balance_service, mock_chain_interfaces, mock_account_service
):
    """Test get_erc20_balance_eth returns correct value."""
    with patch("iwa.core.services.balance.ERC20Contract") as mock_erc20:
        mock_erc20.return_value.balance_of_eth.return_value = 100.5

        result = balance_service.get_erc20_balance_eth("0xAccount", "DAI", "gnosis")

        assert result == 100.5
        mock_account_service.get_token_address.assert_called()
        mock_account_service.resolve_account.assert_called_with("0xAccount")


def test_get_erc20_balance_eth_token_not_found(
    balance_service, mock_chain_interfaces, mock_account_service
):
    """Test get_erc20_balance_eth returns None when token not found."""
    mock_account_service.get_token_address.return_value = None

    result = balance_service.get_erc20_balance_eth("0xAccount", "UNKNOWN", "gnosis")

    assert result is None


def test_get_erc20_balance_eth_account_not_found(
    balance_service, mock_chain_interfaces, mock_account_service
):
    """Test get_erc20_balance_eth returns None when account not found."""
    mock_account_service.resolve_account.return_value = None

    result = balance_service.get_erc20_balance_eth("unknown_tag", "DAI", "gnosis")

    assert result is None


def test_get_erc20_balance_wei_success(
    balance_service, mock_chain_interfaces, mock_account_service
):
    """Test get_erc20_balance_wei returns correct value."""
    with patch("iwa.core.services.balance.ERC20Contract") as mock_erc20:
        mock_erc20.return_value.balance_of_wei.return_value = 100500000000000000000

        result = balance_service.get_erc20_balance_wei("0xAccount", "DAI", "gnosis")

        assert result == 100500000000000000000


def test_get_erc20_balance_wei_token_not_found(
    balance_service, mock_chain_interfaces, mock_account_service
):
    """Test get_erc20_balance_wei returns None when token not found."""
    mock_account_service.get_token_address.return_value = None

    result = balance_service.get_erc20_balance_wei("0xAccount", "UNKNOWN", "gnosis")

    assert result is None


def test_get_erc20_balance_wei_account_not_found(
    balance_service, mock_chain_interfaces, mock_account_service
):
    """Test get_erc20_balance_wei returns None when account not found."""
    mock_account_service.resolve_account.return_value = None

    result = balance_service.get_erc20_balance_wei("unknown_tag", "DAI", "gnosis")

    assert result is None


def test_get_erc20_balance_with_retry_success(
    balance_service, mock_chain_interfaces, mock_account_service
):
    """Test get_erc20_balance_with_retry succeeds on first try."""
    with patch("iwa.core.services.balance.ERC20Contract") as mock_erc20:
        mock_erc20.return_value.balance_of_eth.return_value = 50.0

        result = balance_service.get_erc20_balance_with_retry("0xAccount", "DAI", "gnosis")

        assert result == 50.0


def test_get_erc20_balance_with_retry_fails_then_succeeds(
    balance_service, mock_chain_interfaces, mock_account_service
):
    """Test get_erc20_balance_with_retry retries on failure."""
    with patch("iwa.core.services.balance.ERC20Contract") as mock_erc20, patch("time.sleep"):
        mock_erc20.return_value.balance_of_eth.side_effect = [
            Exception("Network error"),
            25.0,
        ]

        result = balance_service.get_erc20_balance_with_retry(
            "0xAccount", "DAI", "gnosis", retries=3
        )

        assert result == 25.0


def test_get_erc20_balance_with_retry_all_attempts_fail(
    balance_service, mock_chain_interfaces, mock_account_service
):
    """Test get_erc20_balance_with_retry returns None after all retries fail."""
    with patch("iwa.core.services.balance.ERC20Contract") as mock_erc20, patch("time.sleep"):
        mock_erc20.return_value.balance_of_eth.side_effect = Exception("Network error")

        result = balance_service.get_erc20_balance_with_retry(
            "0xAccount", "DAI", "gnosis", retries=3
        )

        assert result is None


def test_balance_service_with_wallet(mock_account_service):
    """Test BalanceService initialization with Wallet (has key_storage attr)."""
    from iwa.core.services.balance import BalanceService

    mock_wallet = MagicMock()
    mock_wallet.key_storage = MagicMock()

    service = BalanceService(mock_wallet, mock_account_service)

    assert service.key_storage == mock_wallet.key_storage
