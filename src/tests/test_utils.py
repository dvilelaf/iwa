import sys
from unittest.mock import patch

import pytest

from iwa.core.utils import configure_logger, get_safe_master_copy_address, singleton


@pytest.fixture
def reset_configure_logger():
    """Remove the configured flag so configure_logger can be called fresh in each test."""
    had_flag = hasattr(configure_logger, "configured")
    if had_flag:
        delattr(configure_logger, "configured")
    yield
    # Restore flag state so other tests aren't affected
    if hasattr(configure_logger, "configured"):
        delattr(configure_logger, "configured")
    if had_flag:
        configure_logger.configured = True


class TestConfigureLogger:
    def test_happy_path(self, reset_configure_logger, tmp_path):
        """File logging and stderr both succeed — stderr added first, then file."""
        with (
            patch("iwa.core.utils.logger") as mock_logger,
            patch("iwa.core.constants.DATA_DIR", tmp_path),
        ):
            result = configure_logger()

        mock_logger.remove.assert_called_once()
        assert mock_logger.add.call_count == 2  # stderr + file
        # Verify stderr is the first sink (order matters for fallback logic)
        first_call_args = mock_logger.add.call_args_list[0]
        assert first_call_args == ((sys.stderr,), {"level": "INFO"})
        assert configure_logger.configured is True
        assert result is mock_logger

    def test_permission_error_on_mkdir(self, reset_configure_logger):
        """PermissionError from mkdir → warning with type name, only stderr sink, no crash."""
        with (
            patch("iwa.core.utils.logger") as mock_logger,
            patch("iwa.core.constants.DATA_DIR") as mock_data_dir,
        ):
            mock_data_dir.mkdir.side_effect = PermissionError("read-only file system")

            configure_logger()

        # Only stderr was added (mkdir failed before logger.add for file)
        mock_logger.add.assert_called_once_with(sys.stderr, level="INFO")
        mock_logger.warning.assert_called_once()
        warning_msg = mock_logger.warning.call_args[0][0]
        assert "unavailable" in warning_msg
        assert configure_logger.configured is True

    def test_oserror_on_mkdir(self, reset_configure_logger):
        """OSError (e.g. disk full) from mkdir → same fallback as PermissionError."""
        with (
            patch("iwa.core.utils.logger") as mock_logger,
            patch("iwa.core.constants.DATA_DIR") as mock_data_dir,
        ):
            mock_data_dir.mkdir.side_effect = OSError("no space left on device")

            configure_logger()

        mock_logger.add.assert_called_once_with(sys.stderr, level="INFO")
        mock_logger.warning.assert_called_once()
        assert "unavailable" in mock_logger.warning.call_args[0][0]
        assert configure_logger.configured is True

    def test_permission_error_on_file_add(self, reset_configure_logger):
        """PermissionError from logger.add(file) → warning with type name, fallback to stderr."""
        with (
            patch("iwa.core.utils.logger") as mock_logger,
            patch("iwa.core.constants.DATA_DIR") as mock_data_dir,
        ):
            mock_data_dir.mkdir.return_value = None
            # First add (stderr) succeeds; second add (file) raises PermissionError
            mock_logger.add.side_effect = [None, PermissionError("permission denied")]

            configure_logger()

        assert mock_logger.add.call_count == 2
        mock_logger.warning.assert_called_once()
        assert "unavailable" in mock_logger.warning.call_args[0][0]
        assert configure_logger.configured is True

    def test_configured_flag_prevents_reinit(self, reset_configure_logger):
        """Second call to configure_logger() returns immediately without re-initializing."""
        with (
            patch("iwa.core.utils.logger") as mock_logger,
            patch("iwa.core.constants.DATA_DIR") as mock_data_dir,
        ):
            mock_data_dir.mkdir.return_value = None
            configure_logger()
            # Verify first call did initialize
            assert mock_logger.add.call_count >= 1
            mock_logger.reset_mock()

            configure_logger()

        mock_logger.remove.assert_not_called()
        mock_logger.add.assert_not_called()


def test_get_safe_master_copy_address_found():
    mock_master_copies = {
        "mainnet": [
            ("0xAddress1", "L2", "1.3.0"),
            ("0xAddress2", "L2", "1.4.1"),
        ]
    }

    with (
        patch("iwa.core.utils.MASTER_COPIES", mock_master_copies),
        patch("iwa.core.utils.EthereumNetwork") as mock_network,
    ):
        mock_network.MAINNET = "mainnet"

        address = get_safe_master_copy_address("1.4.1")
        assert address == "0xAddress2"


def test_get_safe_master_copy_address_not_found():
    mock_master_copies = {
        "mainnet": [
            ("0xAddress1", "L2", "1.3.0"),
        ]
    }

    with (
        patch("iwa.core.utils.MASTER_COPIES", mock_master_copies),
        patch("iwa.core.utils.EthereumNetwork") as mock_network,
    ):
        mock_network.MAINNET = "mainnet"

        with pytest.raises(ValueError, match="Did not find master copy"):
            get_safe_master_copy_address("1.0.0")


def test_singleton():
    @singleton
    class MyClass:
        def __init__(self, val):
            self.val = val

    obj1 = MyClass(1)
    obj2 = MyClass(2)

    assert obj1 is obj2
    assert obj1.val == 1
