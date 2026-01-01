"""Tests for Swap Web API endpoints."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

# We need to mock Wallet and ChainInterfaces BEFORE importing app from server
with (
    patch("iwa.core.wallet.Wallet"),
    patch("iwa.core.chain.ChainInterfaces"),
    patch("iwa.core.wallet.init_db"),
):
    from iwa.web.server import app


@pytest.fixture
def client():
    """TestClient for FastAPI app."""
    return TestClient(app)


def test_get_swap_quote_invalid_account(client):
    """Test /api/swap/quote with invalid account."""
    with patch("iwa.web.routers.swap.wallet") as mock_wallet:
        mock_wallet.account_service.resolve_account.return_value = None

        response = client.get(
            "/api/swap/quote?"
            "account=invalid&sell_token=WXDAI&buy_token=OLAS&amount=1.0"
        )
        assert response.status_code == 400


def test_swap_tokens_invalid_order_type(client):
    """Test /api/swap with invalid order type."""
    response = client.post(
        "/api/swap",
        json={
            "account": "master",
            "sell_token": "WXDAI",
            "buy_token": "OLAS",
            "amount": 1.0,
            "order_type": "invalid",
            "chain": "gnosis",
        },
    )
    # Should return 422 for validation error
    assert response.status_code == 422


def test_swap_quote_invalid_mode(client):
    """Test /api/swap/quote with invalid mode."""
    response = client.get(
        "/api/swap/quote?"
        "account=master&sell_token=WXDAI&buy_token=OLAS&amount=1.0&mode=invalid"
    )
    assert response.status_code == 400


def test_swap_tokens_negative_amount(client):
    """Test /api/swap with negative amount."""
    response = client.post(
        "/api/swap",
        json={
            "account": "master",
            "sell_token": "WXDAI",
            "buy_token": "OLAS",
            "amount": -1.0,
            "order_type": "sell",
            "chain": "gnosis",
        },
    )
    # Should return 422 for validation error
    assert response.status_code == 422


def test_swap_tokens_invalid_chain(client):
    """Test /api/swap with invalid chain."""
    response = client.post(
        "/api/swap",
        json={
            "account": "master",
            "sell_token": "WXDAI",
            "buy_token": "OLAS",
            "amount": 1.0,
            "order_type": "sell",
            "chain": "invalid!chain",
        },
    )
    # Should return 422 for validation error
    assert response.status_code == 422
