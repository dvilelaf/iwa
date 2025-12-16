"""Pytest configuration."""

import logging

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
