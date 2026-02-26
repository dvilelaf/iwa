"""Pytest configuration."""

import logging
from unittest.mock import patch

import pytest
from loguru import logger
from peewee import SqliteDatabase


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
def isolate_test_database(tmp_path):
    """Isolate database for each test to prevent test data leaking to production.

    Redirects all DB writes to a temporary SQLite database that is
    destroyed after the test.  This prevents MagicMock objects and other
    test artefacts from polluting data/activity.db.
    """
    from iwa.core import db as db_module

    test_db_path = tmp_path / "test_activity.db"
    test_db = SqliteDatabase(
        str(test_db_path),
        pragmas={"journal_mode": "wal", "foreign_keys": 1},
    )

    # Swap the module-level database with the temporary one
    original_db = db_module.db
    db_module.db = test_db
    db_module.SentTransaction._meta.database = test_db

    # Create tables in the temp DB
    test_db.connect()
    test_db.create_tables([db_module.SentTransaction])

    yield test_db

    # Restore the original database
    test_db.close()
    db_module.db = original_db
    db_module.SentTransaction._meta.database = original_db


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
