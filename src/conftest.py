"""Pytest configuration."""

import logging
from unittest.mock import patch

import pytest
from loguru import logger


@pytest.fixture(autouse=True)
def caplog(caplog):
    """Make loguru logs visible to pytest caplog."""

    class PropagateHandler(logging.Handler):
        def emit(self, record):
            logging.getLogger(record.name).handle(record)

    handler_id = logger.add(PropagateHandler(), format="{message}")
    yield caplog
    try:
        logger.remove(handler_id)
    except ValueError:
        pass


@pytest.fixture(autouse=True)
def mock_rate_limiter_sleep():
    """Bypass rate limiter and retry delays in tests globally."""
    with (
        patch("iwa.core.chain.rate_limiter.time.sleep"),
        patch("iwa.core.chain.interface.time.sleep"),
        patch("iwa.core.services.safe_executor.time.sleep"),
    ):
        from iwa.core.chain.rate_limiter import _rate_limiters

        _rate_limiters.clear()
        yield


@pytest.fixture(autouse=True)
def mock_chainlist_enrichment():
    """Prevent ChainList network calls during tests.

    Tests that explicitly test enrichment should patch ChainlistRPC directly.
    """
    with patch(
        "iwa.core.chain.interface.ChainInterface._enrich_rpcs_from_chainlist"
    ):
        yield
