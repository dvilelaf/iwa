"""Background workers for TUI."""

import asyncio
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from iwa.core.monitor import EventMonitor
    from iwa.tui.app import IwaApp


class MonitorWorker:
    """Worker to run the EventMonitor."""

    def __init__(self, monitor: "EventMonitor", app: "IwaApp"):
        """Initialize MonitorWorker."""
        self.monitor = monitor
        self.app = app
        self._running = False

    async def run(self):
        """Run the monitor loop."""
        self._running = True
        self.monitor.running = True
        logger.info(f"Starting MonitorWorker for {self.monitor.chain_name}")

        while self._running:
            try:
                # Run check_activity in a thread to avoid blocking the async loop
                # since web3 calls are synchronous
                await asyncio.to_thread(self.monitor.check_activity)
            except Exception as e:
                logger.error(f"Error in MonitorWorker: {e}")

            # Non-blocking sleep
            await asyncio.sleep(6)

    def stop(self):
        """Stop the worker."""
        self._running = False
        self.monitor.stop()
