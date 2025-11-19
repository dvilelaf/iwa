import sys
import os
from pathlib import Path
import pytest
from unittest.mock import MagicMock, patch

# Ensure src is in path
src_path = Path(__file__).parent.parent
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))

@pytest.fixture(autouse=True)
def mock_env_setup(monkeypatch):
    """Mock environment variables and load_dotenv to avoid needing a real secrets file."""
    # Prevent load_dotenv from actually loading a file
    monkeypatch.setattr("iwa.core.models.load_dotenv", lambda *args, **kwargs: None)

    # Set dummy environment variables for Secrets
    monkeypatch.setenv("WALLET_PASSWORD", "test_password")
    monkeypatch.setenv("GNOSIS_RPC", "https://gnosis.rpc")
    monkeypatch.setenv("ETHEREUM_RPC", "https://eth.rpc")
    monkeypatch.setenv("BASE_RPC", "https://base.rpc")
    monkeypatch.setenv("GNOSISSCAN_API_KEY", "test_key")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test_token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123456")
    monkeypatch.setenv("COINGECKO_API_KEY", "test_key")
    monkeypatch.setenv("SECURITY_WORD", "test_word")

@pytest.fixture
def temp_wallet_file(tmp_path):
    """Return a path to a temporary wallet file."""
    return tmp_path / "test_wallet.json"

@pytest.fixture
def caplog(caplog):
    """Fixture to capture loguru logs."""
    from loguru import logger
    import logging

    class PropagateHandler(logging.Handler):
        def emit(self, record):
            logging.getLogger(record.name).handle(record)

    handler_id = logger.add(PropagateHandler(), format="{message}")
    yield caplog
    logger.remove(handler_id)
