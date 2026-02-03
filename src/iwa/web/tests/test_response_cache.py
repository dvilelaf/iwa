"""Tests for response cache functionality."""

import unittest
from unittest.mock import patch

from iwa.web.cache import CacheTTL, ResponseCache, response_cache


class TestResponseCache(unittest.TestCase):
    """Tests for the ResponseCache class."""

    def setUp(self):
        """Reset cache before each test."""
        response_cache.invalidate()

    def test_cache_miss_returns_none(self):
        """Test that cache miss returns None."""
        result = response_cache.get("nonexistent_key", ttl_seconds=60)
        self.assertIsNone(result)

    def test_cache_set_and_get(self):
        """Test basic set and get operations."""
        response_cache.set("test_key", {"data": "value"})
        result = response_cache.get("test_key", ttl_seconds=60)
        self.assertEqual(result, {"data": "value"})

    def test_cache_expiry(self):
        """Test that cached values expire after TTL."""
        response_cache.set("expiring_key", "value")

        # Should be available immediately
        result = response_cache.get("expiring_key", ttl_seconds=60)
        self.assertEqual(result, "value")

        # Should expire with very short TTL
        result = response_cache.get("expiring_key", ttl_seconds=0)
        self.assertIsNone(result)

    def test_invalidate_all(self):
        """Test that invalidate() clears all cache."""
        response_cache.set("key1", "value1")
        response_cache.set("key2", "value2")

        response_cache.invalidate()

        self.assertIsNone(response_cache.get("key1", 60))
        self.assertIsNone(response_cache.get("key2", 60))

    def test_invalidate_pattern(self):
        """Test that invalidate(pattern) only clears matching keys."""
        response_cache.set("service_state:svc1", "state1")
        response_cache.set("service_state:svc2", "state2")
        response_cache.set("balances:svc1", "balance1")

        # Invalidate only service_state keys
        response_cache.invalidate("service_state:")

        # Service state should be gone
        self.assertIsNone(response_cache.get("service_state:svc1", 60))
        self.assertIsNone(response_cache.get("service_state:svc2", 60))

        # Balances should remain
        self.assertEqual(response_cache.get("balances:svc1", 60), "balance1")

    def test_get_or_compute_caches_result(self):
        """Test that get_or_compute caches the computed result."""
        call_count = 0

        def expensive_compute():
            nonlocal call_count
            call_count += 1
            return {"computed": True}

        # First call should compute
        result1 = response_cache.get_or_compute(
            "computed_key", expensive_compute, ttl_seconds=60
        )
        self.assertEqual(result1, {"computed": True})
        self.assertEqual(call_count, 1)

        # Second call should use cache
        result2 = response_cache.get_or_compute(
            "computed_key", expensive_compute, ttl_seconds=60
        )
        self.assertEqual(result2, {"computed": True})
        self.assertEqual(call_count, 1)  # Still 1, not 2

    def test_get_or_compute_recomputes_after_expiry(self):
        """Test that get_or_compute recomputes after cache expires."""
        call_count = 0

        def expensive_compute():
            nonlocal call_count
            call_count += 1
            return call_count

        # First call
        result1 = response_cache.get_or_compute(
            "expiring_compute", expensive_compute, ttl_seconds=0
        )
        self.assertEqual(result1, 1)

        # Immediately expired, should recompute
        result2 = response_cache.get_or_compute(
            "expiring_compute", expensive_compute, ttl_seconds=0
        )
        self.assertEqual(result2, 2)

    def test_singleton_pattern(self):
        """Test that ResponseCache is a singleton."""
        cache1 = ResponseCache()
        cache2 = ResponseCache()
        self.assertIs(cache1, cache2)

    def test_cache_disabled_via_env(self):
        """Test that cache can be disabled via environment variable."""
        with patch.dict("os.environ", {"IWA_RESPONSE_CACHE": "0"}):
            # Create a new instance to pick up env var
            # Note: singleton means we need to reset the instance
            ResponseCache._instance = None
            disabled_cache = ResponseCache()

            disabled_cache.set("test", "value")
            result = disabled_cache.get("test", 60)

            # Should return None when disabled
            self.assertIsNone(result)

            # Restore for other tests
            ResponseCache._instance = None
            response_cache.__class__._instance = None


class TestCacheTTLConstants(unittest.TestCase):
    """Tests for CacheTTL constants."""

    def test_ttl_values_are_reasonable(self):
        """Test that TTL values are within reasonable bounds."""
        # Service state should be at least 1 minute
        self.assertGreaterEqual(CacheTTL.SERVICE_STATE, 60)

        # Balances should be shorter than service state
        self.assertLess(CacheTTL.BALANCES, CacheTTL.SERVICE_STATE)

        # All values should be positive
        self.assertGreater(CacheTTL.SERVICE_STATE, 0)
        self.assertGreater(CacheTTL.STAKING_STATUS, 0)
        self.assertGreater(CacheTTL.BALANCES, 0)
        self.assertGreater(CacheTTL.ACCOUNTS, 0)
        self.assertGreater(CacheTTL.SERVICE_BASIC, 0)


class TestServicesCaching(unittest.TestCase):
    """Tests for services router caching behavior."""

    def setUp(self):
        """Reset cache before each test."""
        response_cache.invalidate()

    def test_service_state_caching_via_cache_api(self):
        """Test that service state lookups use the cache correctly.

        This test verifies caching behavior using the cache API directly,
        avoiding the need to mock complex wallet dependencies.
        """
        call_count = 0

        def mock_fetch_state():
            nonlocal call_count
            call_count += 1
            return "DEPLOYED"

        cache_key = "service_state:test_svc"

        # First call should compute
        result1 = response_cache.get_or_compute(
            cache_key, mock_fetch_state, CacheTTL.SERVICE_STATE
        )
        self.assertEqual(result1, "DEPLOYED")
        self.assertEqual(call_count, 1)

        # Second call should use cache (not recompute)
        result2 = response_cache.get_or_compute(
            cache_key, mock_fetch_state, CacheTTL.SERVICE_STATE
        )
        self.assertEqual(result2, "DEPLOYED")
        self.assertEqual(call_count, 1)  # Still 1, not 2

    def test_cache_invalidation_on_service_change(self):
        """Test that caches are properly invalidated after service changes."""
        # Pre-populate cache
        response_cache.set("service_state:test_svc", "DEPLOYED")
        response_cache.set("staking_status:test_svc", {"is_staked": True})
        response_cache.set("balances:test_svc:gnosis", {"agent": {}})

        # Simulate what stake_service does
        response_cache.invalidate("service_state:test_svc")
        response_cache.invalidate("staking_status:test_svc")
        response_cache.invalidate("balances:test_svc")

        # All should be invalidated
        self.assertIsNone(response_cache.get("service_state:test_svc", 60))
        self.assertIsNone(response_cache.get("staking_status:test_svc", 60))
        self.assertIsNone(response_cache.get("balances:test_svc:gnosis", 60))


class TestAccountsCaching(unittest.TestCase):
    """Tests for accounts router caching behavior."""

    def setUp(self):
        """Reset cache before each test."""
        response_cache.invalidate()

    def test_accounts_cache_key_includes_tokens(self):
        """Test that accounts cache key includes token list for proper isolation."""
        # Different token combinations should have different cache keys
        key1 = f"accounts:gnosis:{'OLAS,WXDAI'}"
        key2 = f"accounts:gnosis:{'OLAS,USDC'}"

        response_cache.set(key1, [{"address": "0x1"}])
        response_cache.set(key2, [{"address": "0x2"}])

        # Should be separate cache entries
        self.assertEqual(
            response_cache.get(key1, 60), [{"address": "0x1"}]
        )
        self.assertEqual(
            response_cache.get(key2, 60), [{"address": "0x2"}]
        )

    def test_accounts_cache_invalidation(self):
        """Test that accounts cache is invalidated on account creation."""
        response_cache.set("accounts:gnosis:native,OLAS", [{"addr": "0x1"}])

        # Simulate what create_eoa does
        response_cache.invalidate("accounts:")

        self.assertIsNone(
            response_cache.get("accounts:gnosis:native,OLAS", 60)
        )


class TestRefreshParameter(unittest.TestCase):
    """Tests for the refresh parameter in web endpoints."""

    def setUp(self):
        """Reset cache before each test."""
        response_cache.invalidate()

    def test_refresh_true_invalidates_and_refetches(self):
        """Test that refresh=True invalidates cache and fetches fresh data."""
        call_count = 0

        def fetch_data():
            nonlocal call_count
            call_count += 1
            return f"data_v{call_count}"

        cache_key = "test:refresh"

        # First call - caches data_v1
        result1 = response_cache.get_or_compute(cache_key, fetch_data, 300)
        self.assertEqual(result1, "data_v1")
        self.assertEqual(call_count, 1)

        # Second call without refresh - should return cached data_v1
        result2 = response_cache.get_or_compute(cache_key, fetch_data, 300)
        self.assertEqual(result2, "data_v1")
        self.assertEqual(call_count, 1)  # Still 1

        # Simulate refresh=True: invalidate then fetch
        response_cache.invalidate(cache_key)
        result3 = response_cache.get_or_compute(cache_key, fetch_data, 300)
        self.assertEqual(result3, "data_v2")  # Fresh data
        self.assertEqual(call_count, 2)  # Now 2

    def test_refresh_only_affects_requested_service(self):
        """Test that refresh invalidates only the specific service cache."""
        response_cache.set("service_state:svc1", "DEPLOYED")
        response_cache.set("service_state:svc2", "STAKED")
        response_cache.set("staking_status:svc1", {"rewards": 100})

        # Refresh svc1 only
        response_cache.invalidate("service_state:svc1")
        response_cache.invalidate("staking_status:svc1")

        # svc1 caches should be gone
        self.assertIsNone(response_cache.get("service_state:svc1", 300))
        self.assertIsNone(response_cache.get("staking_status:svc1", 300))

        # svc2 should still be cached
        self.assertEqual(response_cache.get("service_state:svc2", 300), "STAKED")


class TestServiceManagerCachingIntegration(unittest.TestCase):
    """Tests for ServiceManager caching integration."""

    def setUp(self):
        """Reset cache before each test."""
        response_cache.invalidate()

    def test_force_refresh_pattern(self):
        """Test the force_refresh pattern used by ServiceManager methods."""
        call_count = 0

        def get_data_with_cache(force_refresh: bool = False):
            cache_key = "integration:test"

            if force_refresh:
                response_cache.invalidate(cache_key)

            def fetch():
                nonlocal call_count
                call_count += 1
                return {"count": call_count}

            return response_cache.get_or_compute(cache_key, fetch, 300)

        # Normal calls use cache
        result1 = get_data_with_cache()
        result2 = get_data_with_cache()
        self.assertEqual(result1["count"], 1)
        self.assertEqual(result2["count"], 1)
        self.assertEqual(call_count, 1)

        # force_refresh=True bypasses cache
        result3 = get_data_with_cache(force_refresh=True)
        self.assertEqual(result3["count"], 2)
        self.assertEqual(call_count, 2)


class TestBalancesCaching(unittest.TestCase):
    """Tests for balance caching behavior."""

    def setUp(self):
        """Reset cache before each test."""
        response_cache.invalidate()

    def test_balances_cache_key_includes_chain(self):
        """Test that balance cache keys are chain-specific."""
        response_cache.set("balances:svc1:gnosis", {"native": "1.0"})
        response_cache.set("balances:svc1:ethereum", {"native": "2.0"})

        # Different chains should have different cached values
        gnosis_bal = response_cache.get("balances:svc1:gnosis", 300)
        eth_bal = response_cache.get("balances:svc1:ethereum", 300)

        self.assertEqual(gnosis_bal["native"], "1.0")
        self.assertEqual(eth_bal["native"], "2.0")

    def test_balances_invalidation_by_service(self):
        """Test that balance invalidation can target specific services."""
        response_cache.set("balances:svc1:gnosis", {"native": "1.0"})
        response_cache.set("balances:svc2:gnosis", {"native": "2.0"})

        # Invalidate only svc1 balances
        response_cache.invalidate("balances:svc1")

        # svc1 balance gone, svc2 remains
        self.assertIsNone(response_cache.get("balances:svc1:gnosis", 300))
        self.assertIsNotNone(response_cache.get("balances:svc2:gnosis", 300))


class TestCacheAfterWriteOperations(unittest.TestCase):
    """Tests for cache invalidation after write operations."""

    def setUp(self):
        """Reset cache before each test."""
        response_cache.invalidate()

    def test_stake_invalidates_relevant_caches(self):
        """Test that staking invalidates service_state, staking_status, and balances."""
        service_key = "gnosis:123"

        # Pre-populate caches
        response_cache.set(f"service_state:{service_key}", "DEPLOYED")
        response_cache.set(f"staking_status:{service_key}", {"is_staked": False})
        response_cache.set(f"balances:{service_key}:gnosis", {"native": "1.0"})

        # Simulate what stake_service does on success
        response_cache.invalidate(f"service_state:{service_key}")
        response_cache.invalidate(f"staking_status:{service_key}")
        response_cache.invalidate(f"balances:{service_key}")

        # All should be invalidated
        self.assertIsNone(response_cache.get(f"service_state:{service_key}", 300))
        self.assertIsNone(response_cache.get(f"staking_status:{service_key}", 300))
        self.assertIsNone(response_cache.get(f"balances:{service_key}:gnosis", 300))

    def test_claim_rewards_invalidates_rewards_and_balances(self):
        """Test that claiming rewards invalidates staking_status and balances."""
        service_key = "gnosis:456"

        response_cache.set(f"service_state:{service_key}", "DEPLOYED")
        response_cache.set(f"staking_status:{service_key}", {"rewards": 100})
        response_cache.set(f"balances:{service_key}:gnosis", {"olas": "10.0"})

        # Simulate what claim_rewards does on success
        response_cache.invalidate(f"staking_status:{service_key}")
        response_cache.invalidate(f"balances:{service_key}")

        # service_state should remain (claim doesn't change state)
        self.assertEqual(
            response_cache.get(f"service_state:{service_key}", 300), "DEPLOYED"
        )
        # staking_status and balances should be invalidated
        self.assertIsNone(response_cache.get(f"staking_status:{service_key}", 300))
        self.assertIsNone(response_cache.get(f"balances:{service_key}:gnosis", 300))

    def test_create_service_invalidates_all_service_caches(self):
        """Test that creating a new service invalidates all service caches."""
        # Pre-populate caches for existing services
        response_cache.set("service_state:gnosis:1", "STAKED")
        response_cache.set("service_state:gnosis:2", "DEPLOYED")
        response_cache.set("staking_status:gnosis:1", {"is_staked": True})

        # Simulate what create_service does - invalidates ALL caches
        response_cache.invalidate("service_state:")
        response_cache.invalidate("staking_status:")
        response_cache.invalidate("balances:")

        # All service caches should be gone
        self.assertIsNone(response_cache.get("service_state:gnosis:1", 300))
        self.assertIsNone(response_cache.get("service_state:gnosis:2", 300))
        self.assertIsNone(response_cache.get("staking_status:gnosis:1", 300))

    def test_unstake_invalidates_relevant_caches(self):
        """Test that unstaking invalidates service_state, staking_status, and balances."""
        service_key = "gnosis:789"

        # Pre-populate caches
        response_cache.set(f"service_state:{service_key}", "STAKED")
        response_cache.set(f"staking_status:{service_key}", {"is_staked": True})
        response_cache.set(f"balances:{service_key}:gnosis", {"native": "0.5"})

        # Simulate what unstake does on success
        response_cache.invalidate(f"service_state:{service_key}")
        response_cache.invalidate(f"staking_status:{service_key}")
        response_cache.invalidate(f"balances:{service_key}")

        # All should be invalidated
        self.assertIsNone(response_cache.get(f"service_state:{service_key}", 300))
        self.assertIsNone(response_cache.get(f"staking_status:{service_key}", 300))
        self.assertIsNone(response_cache.get(f"balances:{service_key}:gnosis", 300))

    def test_checkpoint_invalidates_staking_status(self):
        """Test that checkpoint only invalidates staking_status (epoch info)."""
        service_key = "gnosis:321"

        # Pre-populate caches
        response_cache.set(f"service_state:{service_key}", "STAKED")
        response_cache.set(f"staking_status:{service_key}", {"epoch": 5})
        response_cache.set(f"balances:{service_key}:gnosis", {"native": "1.0"})

        # Simulate what call_checkpoint does on success
        response_cache.invalidate(f"staking_status:{service_key}")

        # Only staking_status should be invalidated
        self.assertEqual(
            response_cache.get(f"service_state:{service_key}", 300), "STAKED"
        )
        self.assertIsNone(response_cache.get(f"staking_status:{service_key}", 300))
        self.assertEqual(
            response_cache.get(f"balances:{service_key}:gnosis", 300), {"native": "1.0"}
        )


class TestLifecycleOperationsCaching(unittest.TestCase):
    """Tests for cache invalidation after lifecycle operations."""

    def setUp(self):
        """Reset cache before each test."""
        response_cache.invalidate()

    def test_deploy_invalidates_service_state(self):
        """Test that deploy only invalidates service_state."""
        service_key = "gnosis:100"

        # Pre-populate caches
        response_cache.set(f"service_state:{service_key}", "FINISHED_REGISTRATION")
        response_cache.set(f"staking_status:{service_key}", {"is_staked": False})

        # Simulate what deploy does on success
        response_cache.invalidate(f"service_state:{service_key}")

        # Only service_state should be invalidated
        self.assertIsNone(response_cache.get(f"service_state:{service_key}", 300))
        self.assertEqual(
            response_cache.get(f"staking_status:{service_key}", 300),
            {"is_staked": False},
        )

    def test_terminate_invalidates_service_state(self):
        """Test that terminate only invalidates service_state."""
        service_key = "gnosis:200"

        response_cache.set(f"service_state:{service_key}", "DEPLOYED")
        response_cache.set(f"balances:{service_key}:gnosis", {"native": "0.1"})

        # Simulate what terminate does on success
        response_cache.invalidate(f"service_state:{service_key}")

        # Only service_state should be invalidated
        self.assertIsNone(response_cache.get(f"service_state:{service_key}", 300))
        self.assertEqual(
            response_cache.get(f"balances:{service_key}:gnosis", 300), {"native": "0.1"}
        )

    def test_unbond_invalidates_service_state(self):
        """Test that unbond only invalidates service_state."""
        service_key = "gnosis:300"

        response_cache.set(f"service_state:{service_key}", "TERMINATED_BONDED")

        # Simulate what unbond does on success
        response_cache.invalidate(f"service_state:{service_key}")

        self.assertIsNone(response_cache.get(f"service_state:{service_key}", 300))


class TestDrainOperationsCaching(unittest.TestCase):
    """Tests for cache invalidation after drain operations."""

    def setUp(self):
        """Reset cache before each test."""
        response_cache.invalidate()

    def test_withdraw_rewards_invalidates_balances(self):
        """Test that withdraw_rewards invalidates balances cache."""
        service_key = "gnosis:400"

        response_cache.set(f"service_state:{service_key}", "STAKED")
        response_cache.set(f"staking_status:{service_key}", {"rewards": 50})
        response_cache.set(f"balances:{service_key}:gnosis", {"olas": "100.0"})

        # Simulate what withdraw_rewards does on success
        response_cache.invalidate(f"balances:{service_key}")

        # service_state and staking_status should remain
        self.assertEqual(
            response_cache.get(f"service_state:{service_key}", 300), "STAKED"
        )
        self.assertEqual(
            response_cache.get(f"staking_status:{service_key}", 300), {"rewards": 50}
        )
        # balances should be invalidated
        self.assertIsNone(response_cache.get(f"balances:{service_key}:gnosis", 300))

    def test_drain_service_invalidates_balances(self):
        """Test that drain_service invalidates balances cache."""
        service_key = "gnosis:500"

        response_cache.set(f"balances:{service_key}:gnosis", {"native": "5.0", "olas": "10.0"})

        # Simulate what drain_service does on success
        response_cache.invalidate(f"balances:{service_key}")

        self.assertIsNone(response_cache.get(f"balances:{service_key}:gnosis", 300))


class TestCacheThreadSafety(unittest.TestCase):
    """Tests for cache thread safety."""

    def setUp(self):
        """Reset cache before each test."""
        response_cache.invalidate()

    def test_concurrent_set_and_get(self):  # noqa: C901
        """Test that concurrent set/get operations are thread-safe."""
        import threading

        errors = []
        iterations = 100

        def writer():
            for i in range(iterations):
                try:
                    response_cache.set(f"thread_key:{i}", {"value": i})
                except Exception as e:
                    errors.append(f"Writer error: {e}")

        def reader():
            for i in range(iterations):
                try:
                    response_cache.get(f"thread_key:{i}", 300)
                except Exception as e:
                    errors.append(f"Reader error: {e}")

        def invalidator():
            for _ in range(iterations // 10):
                try:
                    response_cache.invalidate("thread_key:")
                except Exception as e:
                    errors.append(f"Invalidator error: {e}")

        threads = [
            threading.Thread(target=writer),
            threading.Thread(target=reader),
            threading.Thread(target=writer),
            threading.Thread(target=reader),
            threading.Thread(target=invalidator),
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [], f"Thread safety errors: {errors}")


class TestCacheEdgeCases(unittest.TestCase):
    """Tests for cache edge cases."""

    def setUp(self):
        """Reset cache before each test."""
        response_cache.invalidate()

    def test_empty_string_key(self):
        """Test cache with empty string key."""
        response_cache.set("", "empty_key_value")
        result = response_cache.get("", 300)
        self.assertEqual(result, "empty_key_value")

    def test_special_characters_in_key(self):
        """Test cache with special characters in key."""
        key = "service:gnosis:123:special/chars:test"
        response_cache.set(key, {"data": True})
        result = response_cache.get(key, 300)
        self.assertEqual(result, {"data": True})

    def test_large_value(self):
        """Test cache with large value."""
        large_data = {"items": list(range(10000))}
        response_cache.set("large_key", large_data)
        result = response_cache.get("large_key", 300)
        self.assertEqual(len(result["items"]), 10000)

    def test_invalidate_nonexistent_pattern(self):
        """Test invalidating a pattern that doesn't match anything."""
        response_cache.set("existing_key", "value")
        # Should not raise an error
        response_cache.invalidate("nonexistent_pattern")
        # Original key should still exist
        self.assertEqual(response_cache.get("existing_key", 300), "value")

    def test_get_or_compute_with_exception(self):
        """Test get_or_compute when compute function raises exception."""
        def failing_compute():
            raise ValueError("Compute failed")

        with self.assertRaises(ValueError):
            response_cache.get_or_compute("fail_key", failing_compute, 300)

        # Key should not be cached after failure
        self.assertIsNone(response_cache.get("fail_key", 300))


if __name__ == "__main__":
    unittest.main()
