"""RPC Monitor for tracking API usage."""

import threading
from collections import defaultdict
from typing import Dict

from iwa.core.utils import configure_logger

logger = configure_logger()


class RPCMonitor:
    """Singleton monitor for tracking RPC usage."""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        """Create singleton instance."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super(RPCMonitor, cls).__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        """Initialize monitor."""
        if self._initialized:
            return
        self._counts: Dict[str, int] = defaultdict(int)
        self._lock = threading.Lock()
        self._initialized = True

    def increment(self, metric_name: str, count: int = 1):
        """Increment a metric counter."""
        with self._lock:
            self._counts[metric_name] += count

    def get_counts(self) -> Dict[str, int]:
        """Get a copy of current counts."""
        with self._lock:
            return dict(self._counts)

    def log_stats(self):
        """Log current statistics."""
        stats = self.get_counts()
        if not stats:
            return

        logger.info("RPC Stats Summary:")
        total = 0
        for k, v in sorted(stats.items()):
            logger.info(f"  {k}: {v}")
            total += v
        logger.info(f"  TOTAL: {total}")

    def clear(self):
        """Clear all counters."""
        with self._lock:
            self._counts.clear()
