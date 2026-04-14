"""Tests for cow_utils.get_cowpy_module — specifically CoW API unavailability."""

from unittest.mock import patch

import pytest

from iwa.plugins.gnosis.cow_utils import CowApiUnavailableError


class TestGetCowpyModuleApiDown:
    """get_cowpy_module must not crash when api.cow.fi is unreachable."""

    def _clear_cache(self):
        from iwa.plugins.gnosis import cow_utils

        cow_utils._cowpy_cache.clear()

    def test_network_error_on_import_raises_cow_api_unavailable(self):
        """When cowdao_cowpy.app_data.utils raises NetworkError at import time
        (because api.cow.fi is down), get_cowpy_module('DEFAULT_APP_DATA_HASH')
        must raise CowApiUnavailableError — a controlled error callers can catch."""
        self._clear_cache()

        network_error = Exception("Network error occurred: Connection refused")

        with patch("importlib.import_module", side_effect=network_error):
            from iwa.plugins.gnosis.cow_utils import get_cowpy_module

            with pytest.raises(CowApiUnavailableError, match="CoW Protocol API unreachable"):
                get_cowpy_module("DEFAULT_APP_DATA_HASH")

    def test_other_modules_still_raise_original_error(self):
        """Import failures for non-DEFAULT_APP_DATA_HASH modules propagate as-is."""
        self._clear_cache()

        network_error = Exception("Network error occurred: Connection refused")

        with patch("importlib.import_module", side_effect=network_error):
            from iwa.plugins.gnosis.cow_utils import get_cowpy_module

            with pytest.raises(Exception, match="Network error"):
                get_cowpy_module("OrderBookApi")

    def test_cow_api_down_raises_specific_catchable_error(self):
        """Regression: api.cow.fi being down must raise CowApiUnavailableError,
        NOT a generic unhandled exception. This lets callers (swap, trader) catch
        it explicitly without crashing the process."""
        self._clear_cache()

        network_error = Exception("Network error occurred: api.cow.fi unreachable")

        with patch("importlib.import_module", side_effect=network_error):
            from iwa.plugins.gnosis.cow_utils import get_cowpy_module

            with pytest.raises(CowApiUnavailableError):
                get_cowpy_module("DEFAULT_APP_DATA_HASH")

    def test_cow_api_unavailable_error_wraps_original_cause(self):
        """CowApiUnavailableError must chain the original exception as __cause__
        so callers can inspect the root error if needed."""
        self._clear_cache()

        network_error = Exception("Connection refused to api.cow.fi")

        with patch("importlib.import_module", side_effect=network_error):
            from iwa.plugins.gnosis.cow_utils import get_cowpy_module

            with pytest.raises(CowApiUnavailableError) as exc_info:
                get_cowpy_module("DEFAULT_APP_DATA_HASH")

        assert exc_info.value.__cause__ is network_error
