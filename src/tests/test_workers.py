"""Tests for MonitorWorker."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from iwa.tui.workers import MonitorWorker


@pytest.mark.asyncio
async def test_monitor_worker_init():
    """Test initialization."""
    mock_monitor = MagicMock()
    mock_app = MagicMock()
    worker = MonitorWorker(mock_monitor, mock_app)

    assert worker.monitor == mock_monitor
    assert worker.app == mock_app
    assert not worker._running


@pytest.mark.asyncio
async def test_monitor_worker_stop():
    """Test stop method."""
    mock_monitor = MagicMock()
    mock_app = MagicMock()
    worker = MonitorWorker(mock_monitor, mock_app)
    worker._running = True

    worker.stop()

    assert not worker._running
    mock_monitor.stop.assert_called_once()


@pytest.mark.asyncio
async def test_monitor_worker_run():
    """Test run loop."""
    mock_monitor = MagicMock()
    mock_monitor.chain_name = "test_chain"
    mock_app = MagicMock()
    worker = MonitorWorker(mock_monitor, mock_app)

    # Side effect to stop the loop after first iteration
    def stop_worker(*args, **kwargs):
        worker._running = False

    mock_monitor.check_activity.side_effect = stop_worker

    # We need to patch asyncio.sleep to avoid waiting
    with patch("asyncio.sleep", new_callable=AsyncMock):
        await worker.run()

    assert mock_monitor.running
    # check_activity is called in a thread, so we verify it was called
    # Since it's run in to_thread, the side_effect happens in the thread
    # But since we mock check_activity, side_effect executes.
    # Wait, check_activity is called via asyncio.to_thread(self.monitor.check_activity)
    # So we should verify check_activity was called.

    mock_monitor.check_activity.assert_called()


@pytest.mark.asyncio
async def test_monitor_worker_run_error():
    """Test run loop handles errors."""
    mock_monitor = MagicMock()
    mock_monitor.chain_name = "test_chain"
    mock_app = MagicMock()
    worker = MonitorWorker(mock_monitor, mock_app)

    # Side effect: First call raises error, second call stops worker
    async def side_effect(*args, **kwargs):
        if not hasattr(side_effect, "called"):
            side_effect.called = True
            raise ValueError("Test Error")
        worker._running = False
        return None

    worker._running = True

    # Patch asyncio.to_thread to use our side effect
    # We also patch sleep to be fast
    with patch("asyncio.to_thread", side_effect=side_effect) as mock_to_thread:
        with patch("asyncio.sleep", new_callable=AsyncMock):
            await worker.run()

    # This verifies passing through error handling
    assert not worker._running
    # Should be called twice (once error, once success/stop)
    assert mock_to_thread.call_count >= 2
