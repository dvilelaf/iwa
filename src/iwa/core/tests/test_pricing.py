"""Tests for Pricing module."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
import requests

from iwa.core import pricing as pricing_module
from iwa.core.pricing import PriceService, _CACHE_TTL, _NEGATIVE_CACHE_TTL


@pytest.fixture(autouse=True)
def clear_price_cache():
    """Clear the global price cache before each test."""
    pricing_module._PRICE_CACHE.clear()
    yield
    pricing_module._PRICE_CACHE.clear()


@pytest.fixture
def mock_secrets():
    """Mock secrets with an API key."""
    with patch("iwa.core.pricing.secrets") as mock_s:
        mock_s.coingecko_api_key.get_secret_value.return_value = "fake_key"
        yield mock_s


@pytest.fixture
def mock_secrets_no_key():
    """Mock secrets without an API key."""
    with patch("iwa.core.pricing.secrets") as mock_s:
        mock_s.coingecko_api_key = None
        yield mock_s


@pytest.fixture
def price_service(mock_secrets):
    """PriceService fixture with API key."""
    return PriceService()


@pytest.fixture
def price_service_no_key(mock_secrets_no_key):
    """PriceService fixture without API key."""
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


def test_init_with_api_key(price_service):
    """Test initialization with API key."""
    assert price_service.api_key == "fake_key"


def test_init_without_api_key(price_service_no_key):
    """Test initialization without API key."""
    assert price_service_no_key.api_key is None


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


# ---- Cache tests (lines 52-55) ----


def test_get_token_price_cache_hit_positive(price_service):
    """Test cache hit for a positive (non-None) cached price."""
    # Pre-populate the global cache with a recent entry
    pricing_module._PRICE_CACHE["ethereum_usd"] = {
        "price": 3500.0,
        "timestamp": datetime.now(),
    }

    price_service.session = MagicMock()
    result = price_service.get_token_price("ethereum", "usd")

    assert result == 3500.0
    # Session should NOT be called because cache was hit
    price_service.session.get.assert_not_called()


def test_get_token_price_cache_hit_negative(price_service):
    """Test cache hit for a negative (None) cached price within TTL."""
    # Pre-populate with a None entry (negative cache) that is recent
    pricing_module._PRICE_CACHE["badtoken_eur"] = {
        "price": None,
        "timestamp": datetime.now(),
    }

    price_service.session = MagicMock()
    result = price_service.get_token_price("badtoken", "eur")

    assert result is None
    # Session should NOT be called because negative cache was hit
    price_service.session.get.assert_not_called()


def test_get_token_price_cache_expired_positive(price_service):
    """Test that expired positive cache triggers a new fetch."""
    # Pre-populate with an expired entry (older than _CACHE_TTL)
    pricing_module._PRICE_CACHE["ethereum_usd"] = {
        "price": 3500.0,
        "timestamp": datetime.now() - _CACHE_TTL - timedelta(seconds=10),
    }

    price_service.session = MagicMock()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"ethereum": {"usd": 3600.0}}
    price_service.session.get.return_value = mock_response

    result = price_service.get_token_price("ethereum", "usd")

    assert result == 3600.0
    price_service.session.get.assert_called_once()


def test_get_token_price_cache_expired_negative(price_service):
    """Test that expired negative cache triggers a new fetch."""
    # Pre-populate with an expired negative entry (older than _NEGATIVE_CACHE_TTL)
    pricing_module._PRICE_CACHE["badtoken_eur"] = {
        "price": None,
        "timestamp": datetime.now() - _NEGATIVE_CACHE_TTL - timedelta(seconds=10),
    }

    price_service.session = MagicMock()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"badtoken": {"eur": 1.5}}
    price_service.session.get.return_value = mock_response

    result = price_service.get_token_price("badtoken", "eur")

    assert result == 1.5
    price_service.session.get.assert_called_once()


def test_get_token_price_updates_cache(price_service):
    """Test that a fresh fetch updates the global cache."""
    price_service.session = MagicMock()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"gnosis": {"eur": 2.5}}
    price_service.session.get.return_value = mock_response

    price_service.get_token_price("gnosis", "eur")

    assert "gnosis_eur" in pricing_module._PRICE_CACHE
    assert pricing_module._PRICE_CACHE["gnosis_eur"]["price"] == 2.5


# ---- 401 API key invalid tests (lines 78-83) ----


def test_fetch_price_401_retries_without_key(price_service):
    """Test that 401 response strips the API key and retries without it."""
    # First response: 401 (invalid key), second response: 200 (success without key)
    mock_response_401 = MagicMock()
    mock_response_401.status_code = 401

    mock_response_200 = MagicMock()
    mock_response_200.status_code = 200
    mock_response_200.json.return_value = {"ethereum": {"eur": 3000.0}}

    price_service.session = MagicMock()
    price_service.session.get.side_effect = [mock_response_401, mock_response_200]

    result = price_service.get_token_price("ethereum", "eur")

    assert result == 3000.0
    assert price_service.api_key is None
    # Called twice: first with key (got 401), then without key (got 200)
    assert price_service.session.get.call_count == 2


def test_fetch_price_401_without_api_key_no_retry(price_service_no_key):
    """Test that 401 without an API key does not trigger key removal retry."""
    mock_response_401 = MagicMock()
    mock_response_401.status_code = 401
    mock_response_401.raise_for_status.side_effect = requests.HTTPError("401 Unauthorized")

    price_service_no_key.session = MagicMock()
    price_service_no_key.session.get.return_value = mock_response_401

    with patch("iwa.core.pricing.time.sleep"):
        result = price_service_no_key.get_token_price("ethereum", "eur")

    # Without an API key, the 401 path for key removal is skipped.
    # raise_for_status will trigger the exception path.
    assert result is None


# ---- 429 Rate limit tests (lines 86-93) ----


def test_fetch_price_429_retries_and_succeeds(price_service):
    """Test that 429 triggers retries with backoff and eventually succeeds."""
    mock_response_429 = MagicMock()
    mock_response_429.status_code = 429

    mock_response_200 = MagicMock()
    mock_response_200.status_code = 200
    mock_response_200.json.return_value = {"ethereum": {"eur": 3100.0}}

    price_service.session = MagicMock()
    price_service.session.get.side_effect = [mock_response_429, mock_response_200]

    with patch("iwa.core.pricing.time.sleep") as mock_sleep:
        result = price_service.get_token_price("ethereum", "eur")

    assert result == 3100.0
    # Sleep should be called once for the first 429 retry (2 * (0+1) = 2 seconds)
    mock_sleep.assert_called_once_with(2)


def test_fetch_price_429_exhausts_retries(price_service):
    """Test that persistent 429 returns None after exhausting retries."""
    mock_response_429 = MagicMock()
    mock_response_429.status_code = 429

    price_service.session = MagicMock()
    # All 3 attempts (max_retries=2, so attempts 0,1,2) return 429
    price_service.session.get.return_value = mock_response_429

    with patch("iwa.core.pricing.time.sleep") as mock_sleep:
        result = price_service.get_token_price("ethereum", "eur")

    assert result is None
    # 3 total calls (attempts 0, 1, 2)
    assert price_service.session.get.call_count == 3
    # Sleep called for first two 429s (attempts 0 and 1), not the last one
    assert mock_sleep.call_count == 2


# ---- Token not found in response (line 102-103) ----


def test_fetch_price_token_not_in_response(price_service):
    """Test that a response missing the token_id returns None."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {}  # Empty response, token not found

    price_service.session = MagicMock()
    price_service.session.get.return_value = mock_response

    result = price_service.get_token_price("nonexistent_token", "eur")
    assert result is None


def test_fetch_price_currency_not_in_response(price_service):
    """Test that a response with token but missing currency returns None."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"ethereum": {"usd": 3000.0}}

    price_service.session = MagicMock()
    price_service.session.get.return_value = mock_response

    # Requesting 'eur' but only 'usd' is in the response
    result = price_service.get_token_price("ethereum", "eur")
    assert result is None


# ---- Exception handling tests (lines 105-112) ----


def test_fetch_price_exception_retries_and_fails(price_service):
    """Test that network exceptions trigger retries and eventually return None."""
    price_service.session = MagicMock()
    price_service.session.get.side_effect = ConnectionError("Network error")

    with patch("iwa.core.pricing.time.sleep") as mock_sleep:
        result = price_service.get_token_price("ethereum", "eur")

    assert result is None
    # 3 total attempts (0, 1, 2)
    assert price_service.session.get.call_count == 3
    # Sleep called between retries (attempts 0 and 1), not after the last
    assert mock_sleep.call_count == 2
    mock_sleep.assert_any_call(1)


def test_fetch_price_exception_then_success(price_service):
    """Test that a transient exception on first attempt recovers on retry."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"ethereum": {"eur": 3200.0}}

    price_service.session = MagicMock()
    price_service.session.get.side_effect = [
        ConnectionError("Transient error"),
        mock_response,
    ]

    with patch("iwa.core.pricing.time.sleep"):
        result = price_service.get_token_price("ethereum", "eur")

    assert result == 3200.0
    assert price_service.session.get.call_count == 2


def test_fetch_price_http_error_retries(price_service):
    """Test that raise_for_status HTTPError triggers retries."""
    mock_response = MagicMock()
    mock_response.status_code = 500
    mock_response.raise_for_status.side_effect = requests.HTTPError("500 Server Error")

    price_service.session = MagicMock()
    price_service.session.get.return_value = mock_response

    with patch("iwa.core.pricing.time.sleep"):
        result = price_service.get_token_price("ethereum", "eur")

    assert result is None
    # 3 attempts total
    assert price_service.session.get.call_count == 3


# ---- API key header tests ----


def test_fetch_price_includes_api_key_header(price_service):
    """Test that API key is included in headers when present."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"ethereum": {"eur": 3000.0}}

    price_service.session = MagicMock()
    price_service.session.get.return_value = mock_response

    price_service.get_token_price("ethereum", "eur")

    _, kwargs = price_service.session.get.call_args
    assert kwargs["headers"]["x-cg-demo-api-key"] == "fake_key"


def test_fetch_price_no_api_key_no_header(price_service_no_key):
    """Test that no API key header is sent when key is absent."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"ethereum": {"eur": 3000.0}}

    price_service_no_key.session = MagicMock()
    price_service_no_key.session.get.return_value = mock_response

    price_service_no_key.get_token_price("ethereum", "eur")

    _, kwargs = price_service_no_key.session.get.call_args
    assert "x-cg-demo-api-key" not in kwargs["headers"]


# ---- Default currency test ----


def test_get_token_price_default_currency(price_service):
    """Test that the default currency is 'eur'."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"ethereum": {"eur": 2800.0}}

    price_service.session = MagicMock()
    price_service.session.get.return_value = mock_response

    result = price_service.get_token_price("ethereum")

    assert result == 2800.0
    _, kwargs = price_service.session.get.call_args
    assert kwargs["params"]["vs_currencies"] == "eur"


# ---- Negative cache storage test ----


def test_get_token_price_stores_none_in_cache(price_service):
    """Test that a failed fetch stores None in cache (negative caching)."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {}  # Token not found

    price_service.session = MagicMock()
    price_service.session.get.return_value = mock_response

    result = price_service.get_token_price("invalid_token", "eur")

    assert result is None
    assert "invalid_token_eur" in pricing_module._PRICE_CACHE
    assert pricing_module._PRICE_CACHE["invalid_token_eur"]["price"] is None
