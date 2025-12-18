from datetime import timedelta
from unittest.mock import patch

import pytest

from iwa.core.pricing import PriceService


@pytest.fixture
def mock_secrets():
    with patch("iwa.core.pricing.settings") as mock:
        mock.coingecko_api_key.get_secret_value.return_value = "test_api_key"
        yield mock


@pytest.fixture
def price_service(mock_secrets):
    return PriceService()


def test_get_token_price_success(price_service):
    with patch("iwa.core.pricing.requests.get") as mock_get:
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {"ethereum": {"eur": 2000.50}}

        price = price_service.get_token_price("ethereum", "eur")

        assert price == 2000.50
        mock_get.assert_called_once()
        # Verify API key in headers
        args, kwargs = mock_get.call_args
        assert kwargs["headers"]["x-cg-demo-api-key"] == "test_api_key"


def test_get_token_price_cached(price_service):
    # Pre-populate cache
    from datetime import datetime

    price_service.cache["ethereum_eur"] = {"price": 100.0, "timestamp": datetime.now()}

    with patch("iwa.core.pricing.requests.get") as mock_get:
        price = price_service.get_token_price("ethereum", "eur")
        assert price == 100.0
        mock_get.assert_not_called()


def test_get_token_price_cache_expired(price_service):
    # Pre-populate expired cache
    from datetime import datetime

    price_service.cache["ethereum_eur"] = {
        "price": 100.0,
        "timestamp": datetime.now() - timedelta(minutes=10),
    }

    with patch("iwa.core.pricing.requests.get") as mock_get:
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {"ethereum": {"eur": 200.0}}

        price = price_service.get_token_price("ethereum", "eur")
        assert price == 200.0
        mock_get.assert_called_once()


def test_get_token_price_api_error(price_service):
    with patch("iwa.core.pricing.requests.get") as mock_get:
        mock_get.side_effect = Exception("API Error")

        price = price_service.get_token_price("ethereum", "eur")
        assert price is None


def test_get_token_price_key_not_found(price_service):
    with patch("iwa.core.pricing.requests.get") as mock_get:
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {}  # Empty response

        price = price_service.get_token_price("ethereum", "eur")
        assert price is None
