"""Tests for Pricing module."""

from unittest.mock import MagicMock, patch

import pytest
import requests

from iwa.core.pricing import PriceService


@pytest.fixture
def mock_secrets():
    """Mock secrets."""
    with patch("iwa.core.pricing.secrets") as mock_s:
        mock_s.coingecko_api_key.get_secret_value.return_value = "fake_key"
        yield mock_s


@pytest.fixture
def price_service(mock_secrets):
    """PriceService fixture."""
    return PriceService()


def test_init_session(price_service):
    """Test session initialization."""
    assert isinstance(price_service.session, requests.Session)

    # Verify adapters are mounted
    assert "https://" in price_service.session.adapters
    assert "http://" in price_service.session.adapters

    # Verify retry configuration in adapter
    adapter = price_service.session.adapters["https://"]
    assert adapter.max_retries.total == 3
    assert adapter.max_retries.status_forcelist == [429, 500, 502, 503, 504]


def test_close(price_service):
    """Test close method."""
    price_service.session = MagicMock()
    price_service.close()
    price_service.session.close.assert_called_once()


def test_get_token_price_uses_session(price_service):
    """Test get_token_price uses session."""
    price_service.session = MagicMock()

    # Mock response
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"autonolas": {"eur": 5.0}}
    price_service.session.get.return_value = mock_response

    price = price_service.get_token_price("autonolas", "eur")

    assert price == 5.0
    price_service.session.get.assert_called()

    # Verify call args
    args, kwargs = price_service.session.get.call_args
    assert "api.coingecko.com" in args[0]
    assert kwargs["params"]["ids"] == "autonolas"
    assert kwargs["params"]["vs_currencies"] == "eur"
