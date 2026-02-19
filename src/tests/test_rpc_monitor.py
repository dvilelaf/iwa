"""Tests for RPCMonitor singleton class."""

import threading
from unittest.mock import patch

from iwa.core.rpc_monitor import RPCMonitor


def _reset_singleton():
    """Reset RPCMonitor singleton state for test isolation."""
    RPCMonitor._instance = None


class TestRPCMonitorSingleton:
    """Tests for singleton behavior."""

    def setup_method(self):
        _reset_singleton()

    def teardown_method(self):
        _reset_singleton()

    def test_singleton_returns_same_instance(self):
        """Two calls to RPCMonitor() return the same object."""
        m1 = RPCMonitor()
        m2 = RPCMonitor()
        assert m1 is m2

    def test_singleton_initialized_once(self):
        """__init__ body only runs on first instantiation."""
        m1 = RPCMonitor()
        m1.increment("test_metric", 5)

        # Second instantiation must NOT reset _counts
        m2 = RPCMonitor()
        assert m2.get_counts() == {"test_metric": 5}

    def test_singleton_thread_safety(self):
        """Multiple threads creating RPCMonitor all get the same instance."""
        instances = []
        barrier = threading.Barrier(10)

        def create_instance():
            barrier.wait()
            instances.append(RPCMonitor())

        threads = [threading.Thread(target=create_instance) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All instances should be the same object
        assert len(instances) == 10
        assert all(inst is instances[0] for inst in instances)


class TestRPCMonitorIncrement:
    """Tests for the increment method."""

    def setup_method(self):
        _reset_singleton()

    def teardown_method(self):
        _reset_singleton()

    def test_increment_default_count(self):
        """increment with default count=1."""
        monitor = RPCMonitor()
        monitor.increment("eth_call")
        assert monitor.get_counts() == {"eth_call": 1}

    def test_increment_custom_count(self):
        """increment with explicit count value."""
        monitor = RPCMonitor()
        monitor.increment("eth_call", count=5)
        assert monitor.get_counts() == {"eth_call": 5}

    def test_increment_accumulates(self):
        """Multiple increments on the same metric accumulate."""
        monitor = RPCMonitor()
        monitor.increment("eth_call", 3)
        monitor.increment("eth_call", 7)
        assert monitor.get_counts()["eth_call"] == 10

    def test_increment_multiple_metrics(self):
        """Different metric names tracked independently."""
        monitor = RPCMonitor()
        monitor.increment("eth_call", 2)
        monitor.increment("eth_getBalance", 3)
        counts = monitor.get_counts()
        assert counts == {"eth_call": 2, "eth_getBalance": 3}

    def test_increment_thread_safety(self):
        """Concurrent increments from multiple threads are consistent."""
        monitor = RPCMonitor()
        barrier = threading.Barrier(10)

        def do_increments():
            barrier.wait()
            for _ in range(100):
                monitor.increment("concurrent_metric")

        threads = [threading.Thread(target=do_increments) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert monitor.get_counts()["concurrent_metric"] == 1000


class TestRPCMonitorGetCounts:
    """Tests for the get_counts method."""

    def setup_method(self):
        _reset_singleton()

    def teardown_method(self):
        _reset_singleton()

    def test_get_counts_empty(self):
        """get_counts returns empty dict when no metrics recorded."""
        monitor = RPCMonitor()
        assert monitor.get_counts() == {}

    def test_get_counts_returns_copy(self):
        """get_counts returns a copy, not the internal dict."""
        monitor = RPCMonitor()
        monitor.increment("eth_call", 1)
        counts = monitor.get_counts()
        # Mutating the returned dict should not affect internal state
        counts["eth_call"] = 999
        assert monitor.get_counts()["eth_call"] == 1

    def test_get_counts_is_plain_dict(self):
        """get_counts returns a regular dict, not a defaultdict."""
        monitor = RPCMonitor()
        monitor.increment("a")
        counts = monitor.get_counts()
        assert type(counts) is dict


class TestRPCMonitorLogStats:
    """Tests for the log_stats method."""

    def setup_method(self):
        _reset_singleton()

    def teardown_method(self):
        _reset_singleton()

    def test_log_stats_empty_returns_early(self):
        """log_stats does nothing when there are no stats."""
        monitor = RPCMonitor()
        with patch("iwa.core.rpc_monitor.logger") as mock_logger:
            monitor.log_stats()
            mock_logger.info.assert_not_called()

    def test_log_stats_logs_summary(self):
        """log_stats logs header, each metric sorted, and total."""
        monitor = RPCMonitor()
        monitor.increment("eth_getBalance", 3)
        monitor.increment("eth_call", 7)

        with patch("iwa.core.rpc_monitor.logger") as mock_logger:
            monitor.log_stats()

            calls = [c.args[0] for c in mock_logger.info.call_args_list]
            assert calls[0] == "RPC Stats Summary:"
            # Sorted: eth_call before eth_getBalance
            assert "eth_call: 7" in calls[1]
            assert "eth_getBalance: 3" in calls[2]
            assert "TOTAL: 10" in calls[3]

    def test_log_stats_single_metric(self):
        """log_stats with a single metric."""
        monitor = RPCMonitor()
        monitor.increment("only_metric", 42)

        with patch("iwa.core.rpc_monitor.logger") as mock_logger:
            monitor.log_stats()

            calls = [c.args[0] for c in mock_logger.info.call_args_list]
            assert len(calls) == 3  # header, metric, total
            assert "only_metric: 42" in calls[1]
            assert "TOTAL: 42" in calls[2]


class TestRPCMonitorClear:
    """Tests for the clear method."""

    def setup_method(self):
        _reset_singleton()

    def teardown_method(self):
        _reset_singleton()

    def test_clear_removes_all_metrics(self):
        """clear empties all counters."""
        monitor = RPCMonitor()
        monitor.increment("a", 1)
        monitor.increment("b", 2)
        monitor.clear()
        assert monitor.get_counts() == {}

    def test_clear_allows_new_increments(self):
        """After clear, new increments start from zero."""
        monitor = RPCMonitor()
        monitor.increment("metric", 10)
        monitor.clear()
        monitor.increment("metric", 1)
        assert monitor.get_counts() == {"metric": 1}

    def test_clear_on_empty(self):
        """clear on an already-empty monitor does not raise."""
        monitor = RPCMonitor()
        monitor.clear()  # should not raise
        assert monitor.get_counts() == {}
