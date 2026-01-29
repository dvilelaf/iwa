"""Tests for contract instance caching."""

import time
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def reset_singleton():
    """Reset the ContractCache singleton before each test."""
    from iwa.core.contracts.cache import ContractCache

    ContractCache._instance = None
    yield
    ContractCache._instance = None


class TestContractCache:
    """Test ContractCache singleton and caching behavior."""

    def test_singleton_pattern(self):
        """Test that ContractCache is a singleton."""
        from iwa.core.contracts.cache import ContractCache

        c1 = ContractCache()
        c2 = ContractCache()
        assert c1 is c2

    def test_get_contract_creates_new_instance(self):
        """Test get_contract creates new instance when not cached."""
        from iwa.core.contracts.cache import ContractCache

        cache = ContractCache()
        mock_cls = MagicMock(__name__="MockContract")
        mock_instance = MagicMock()
        mock_cls.return_value = mock_instance

        result = cache.get_contract(
            mock_cls, "0x1234567890123456789012345678901234567890", "gnosis"
        )

        mock_cls.assert_called_once_with(
            "0x1234567890123456789012345678901234567890", chain_name="gnosis"
        )
        assert result is mock_instance

    def test_get_contract_returns_cached_instance(self):
        """Test get_contract returns cached instance on second call."""
        from iwa.core.contracts.cache import ContractCache

        cache = ContractCache()
        mock_cls = MagicMock(__name__="MockContract")
        mock_instance = MagicMock()
        mock_cls.return_value = mock_instance

        result1 = cache.get_contract(
            mock_cls, "0x1234567890123456789012345678901234567890", "gnosis"
        )
        result2 = cache.get_contract(
            mock_cls, "0x1234567890123456789012345678901234567890", "gnosis"
        )

        # Should only create once
        mock_cls.assert_called_once()
        assert result1 is result2

    def test_get_contract_raises_on_empty_address(self):
        """Test get_contract raises ValueError for empty address."""
        from iwa.core.contracts.cache import ContractCache

        cache = ContractCache()
        mock_cls = MagicMock(__name__="MockContract")

        with pytest.raises(ValueError, match="Address is required"):
            cache.get_contract(mock_cls, "", "gnosis")

    def test_get_contract_respects_ttl_expiry(self):
        """Test get_contract recreates instance after TTL expires."""
        from iwa.core.contracts.cache import ContractCache

        cache = ContractCache()
        mock_cls = MagicMock(__name__="MockContract")
        mock_cls.return_value = MagicMock()

        # First call
        cache.get_contract(
            mock_cls, "0x1234567890123456789012345678901234567890", "gnosis", ttl=0
        )

        # Wait for expiry (TTL=0 means immediate expiry)
        time.sleep(0.01)

        # Second call should create new instance
        cache.get_contract(
            mock_cls, "0x1234567890123456789012345678901234567890", "gnosis", ttl=0
        )

        assert mock_cls.call_count == 2

    def test_get_if_cached_returns_cached_instance(self):
        """Test get_if_cached returns cached instance."""
        from iwa.core.contracts.cache import ContractCache

        cache = ContractCache()
        mock_cls = MagicMock(__name__="MockContract")
        mock_instance = MagicMock()
        mock_cls.return_value = mock_instance

        # First populate cache
        cache.get_contract(
            mock_cls, "0x1234567890123456789012345678901234567890", "gnosis"
        )

        # get_if_cached should return it
        result = cache.get_if_cached(
            mock_cls, "0x1234567890123456789012345678901234567890", "gnosis"
        )

        assert result is mock_instance

    def test_get_if_cached_returns_none_when_not_cached(self):
        """Test get_if_cached returns None when not cached."""
        from iwa.core.contracts.cache import ContractCache

        cache = ContractCache()
        mock_cls = MagicMock(__name__="MockContract")

        result = cache.get_if_cached(
            mock_cls, "0x1234567890123456789012345678901234567890", "gnosis"
        )

        assert result is None

    def test_get_if_cached_returns_none_for_empty_address(self):
        """Test get_if_cached returns None for empty address."""
        from iwa.core.contracts.cache import ContractCache

        cache = ContractCache()
        mock_cls = MagicMock(__name__="MockContract")

        result = cache.get_if_cached(mock_cls, "", "gnosis")

        assert result is None

    def test_get_if_cached_returns_none_after_expiry(self):
        """Test get_if_cached returns None after TTL expires."""
        from iwa.core.contracts.cache import ContractCache

        cache = ContractCache()
        cache.ttl = 0  # Immediate expiry
        mock_cls = MagicMock(__name__="MockContract")
        mock_cls.return_value = MagicMock()

        # Populate cache
        cache.get_contract(
            mock_cls, "0x1234567890123456789012345678901234567890", "gnosis"
        )

        time.sleep(0.01)

        # get_if_cached should return None due to expiry
        result = cache.get_if_cached(
            mock_cls, "0x1234567890123456789012345678901234567890", "gnosis"
        )

        assert result is None

    def test_clear_removes_all_entries(self):
        """Test clear removes all cached contracts."""
        from iwa.core.contracts.cache import ContractCache

        cache = ContractCache()
        mock_cls = MagicMock(__name__="MockContract")
        mock_cls.return_value = MagicMock()

        # Populate cache
        cache.get_contract(
            mock_cls, "0x1234567890123456789012345678901234567890", "gnosis"
        )

        cache.clear()

        # get_if_cached should return None
        result = cache.get_if_cached(
            mock_cls, "0x1234567890123456789012345678901234567890", "gnosis"
        )
        assert result is None

    def test_invalidate_removes_specific_entry(self):
        """Test invalidate removes specific cached contract."""
        from iwa.core.contracts.cache import ContractCache

        cache = ContractCache()
        mock_cls1 = MagicMock(__name__="Contract1")
        mock_cls2 = MagicMock(__name__="Contract2")
        mock_cls1.return_value = MagicMock()
        mock_cls2.return_value = MagicMock()

        # Populate cache with two contracts
        cache.get_contract(
            mock_cls1, "0x1234567890123456789012345678901234567890", "gnosis"
        )
        cache.get_contract(
            mock_cls2, "0xABCDEF1234567890123456789012345678901234", "gnosis"
        )

        # Invalidate only the first one
        cache.invalidate(
            mock_cls1, "0x1234567890123456789012345678901234567890", "gnosis"
        )

        # First should be gone
        result1 = cache.get_if_cached(
            mock_cls1, "0x1234567890123456789012345678901234567890", "gnosis"
        )
        assert result1 is None

        # Second should still exist
        result2 = cache.get_if_cached(
            mock_cls2, "0xABCDEF1234567890123456789012345678901234", "gnosis"
        )
        assert result2 is not None

    def test_invalidate_nonexistent_does_nothing(self):
        """Test invalidate does nothing for non-existent entry."""
        from iwa.core.contracts.cache import ContractCache

        cache = ContractCache()
        mock_cls = MagicMock(__name__="Contract")

        # Should not raise
        cache.invalidate(
            mock_cls, "0x1234567890123456789012345678901234567890", "gnosis"
        )

    def test_env_ttl_configuration(self):
        """Test TTL is configurable via environment variable."""
        from iwa.core.contracts.cache import ContractCache

        with patch.dict("os.environ", {"IWA_CONTRACT_CACHE_TTL": "7200"}):
            ContractCache._instance = None
            cache = ContractCache()
            assert cache.ttl == 7200

    def test_invalid_env_ttl_uses_default(self):
        """Test invalid TTL env var uses default value."""
        from iwa.core.contracts.cache import ContractCache

        with patch.dict("os.environ", {"IWA_CONTRACT_CACHE_TTL": "invalid"}):
            ContractCache._instance = None
            cache = ContractCache()
            assert cache.ttl == 3600
