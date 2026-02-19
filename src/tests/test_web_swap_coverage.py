"""Tests for swap router coverage."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# PATCH Wallet before importing app to avoid global instantiation triggering KeyStorage security check
with patch("iwa.core.wallet.Wallet") as MockWallet:
    # Ensure the mock returns a flexible object
    MockWallet.return_value = MagicMock()
    # Import app inside the patch context or after patching (if patch was global, but here it's context)
    # Actually, importing here means 'app' is only available in this scope?
    # No, we need 'app' for TestClient.
    from iwa.web.server import app


@pytest.fixture
def client():
    """Create a test client with patched dependnecies."""
    # Patch init_db to prevent real KeyStorage init during lifespan
    with patch("iwa.web.server.init_db"):
        # Also patch ChainInterfaces to avoid block tracking init
        with patch("iwa.core.chain.ChainInterfaces"):
            with TestClient(app) as c:
                yield c


@pytest.fixture
def mock_cow_plugin():
    """Mock the CowSwap plugin."""
    with patch("iwa.web.routers.swap.CowSwap") as mock_cow:
        mock_instance = MagicMock()
        mock_cow.return_value = mock_instance
        yield mock_instance


def test_get_quote_errors(client, mock_cow_plugin):
    """Test error handling in get_quote."""
    # The router instantiates CowSwap inside the endpoint (or dependency)
    # We mocked CowSwap class.
    # The endpoint calls get_max_buy_amount_wei or get_max_sell_amount_wei

    # We need to ensure authentication passes.
    # verify_auth depends on X-API-Key or Password.
    # Use dependency override for auth if needed, or just rely on default allow if no password set.

    mock_cow_plugin.get_max_buy_amount_wei.side_effect = Exception("CowSwap API Error")

    response = client.get(
        "/api/swap/quote",
        params={
            "account": "master",
            "sell_token": "WXDAI",
            "buy_token": "OLAS",
            "amount": "100",
            "mode": "sell",
            "chain": "gnosis",
        },
    )

    assert response.status_code == 400
    assert "CowSwap API Error" in response.json()["detail"]


def test_swap_tokens_success(client):
    """Test successful token swap."""
    # We need to mock wallet.transfer_service.swap returns a coroutine (AsyncMock)
    with patch(
        "iwa.web.routers.swap.wallet.transfer_service.swap", new_callable=AsyncMock
    ) as mock_swap:
        mock_swap.return_value = {
            "status": "open",
            "uid": "0x123",
            "sellToken": "0xSell",
            "buyToken": "0xBuy",
            "sellAmount": "1000",
            "buyAmount": "990",
            "validTo": 1234567890,
        }

        response = client.post(
            "/api/swap",
            json={
                "account": "master",
                "sell_token": "WXDAI",
                "buy_token": "OLAS",
                "amount_eth": 10.0,
                "order_type": "sell",
                "chain": "gnosis",
            },
        )

        assert response.status_code == 200, response.json()
        assert response.json()["status"] == "success"
        assert response.json()["order"]["uid"] == "0x123"


def test_swap_tokens_error(client):
    """Test error when swapping tokens."""
    with patch(
        "iwa.web.routers.swap.wallet.transfer_service.swap", new_callable=AsyncMock
    ) as mock_swap:
        mock_swap.side_effect = Exception("Swap Failed")

        response = client.post(
            "/api/swap",
            json={
                "account": "master",
                "sell_token": "WXDAI",
                "buy_token": "OLAS",
                "amount_eth": 10.0,
                "order_type": "sell",
                "chain": "gnosis",
            },
        )

        assert response.status_code == 400
        assert "Swap Failed" in response.json()["detail"]


def test_get_orders_history(client):
    """Test retrieving order history."""
    # Mock requests.get globally since it's imported inside the function
    with patch("requests.get") as mock_get:
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = [
            {
                "uid": "0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
                "status": "open",
                "creationDate": "2023-01-01T00:00:00Z",
                "validTo": 9999999999,
                "sellToken": "0xSell",
                "buyToken": "0xBuy",
                "sellAmount": "1000000000000000000",
                "buyAmount": "900000000000000000",
            }
        ]

        # We also need to mock Account resolution and ChainInterfaces
        with patch("iwa.web.routers.swap.wallet.account_service.resolve_account") as mock_resolve:
            mock_resolve.return_value.address = "0xUser"

            with patch("iwa.web.routers.swap.ChainInterfaces") as mock_chain_interfaces:
                mock_chain = MagicMock()
                mock_chain.chain.chain_id = 100
                mock_chain.chain.get_token_name.return_value = "TOKEN"
                mock_chain_interfaces.return_value.get.return_value = mock_chain

                response = client.get("/api/swap/orders", params={"account": "master"})

                assert response.status_code == 200
                data = response.json()
                assert "orders" in data
                assert len(data["orders"]) == 1
                assert data["orders"][0]["status"] == "open"
