"""Tests for iwa.plugins.olas.events — OlasEventInvalidator."""

import time
import unittest
from unittest.mock import MagicMock, patch

# Valid Ethereum addresses for testing
ADDR_STAKING_1 = "0x389B46C259631Acd6a69Bde8B6cEe218230bAE8C"
ADDR_STAKING_2 = "0x238EB6993b90A978ec6AAD7530D6429c949C08DA"


def _build_invalidator(
    chain_name="gnosis",
    staking_contracts=None,
    web3=None,
    chain_interface=None,
):
    """Build an OlasEventInvalidator with mocked dependencies.

    Patches ChainInterfaces, OLAS_TRADER_STAKING_CONTRACTS, and ContractCache
    so the constructor does not make real RPC calls.

    Because __init__ does local imports from iwa.core.chain and
    iwa.plugins.olas.constants, we must patch at the source modules.
    """
    if staking_contracts is None:
        staking_contracts = {
            chain_name: {
                "Contract A": ADDR_STAKING_1,
                "Contract B": ADDR_STAKING_2,
            }
        }
    if web3 is None:
        web3 = MagicMock()
    if chain_interface is None:
        chain_interface = MagicMock()
        chain_interface.web3 = web3

    mock_cache = MagicMock()

    with (
        patch("iwa.core.chain.ChainInterfaces") as mock_ci_cls,
        patch(
            "iwa.plugins.olas.constants.OLAS_TRADER_STAKING_CONTRACTS",
            staking_contracts,
        ),
        patch("iwa.core.contracts.cache.ContractCache") as mock_cache_cls,
    ):
        mock_ci_cls.return_value.get.return_value = chain_interface
        mock_cache_cls.return_value = mock_cache

        from iwa.plugins.olas.events import OlasEventInvalidator

        inv = OlasEventInvalidator(chain_name=chain_name)
        # Reassign the cache mock so tests can inspect it
        inv.contract_cache = mock_cache

    return inv


class TestOlasEventInvalidatorInit(unittest.TestCase):
    """Tests for __init__."""

    def test_init_default_chain(self):
        inv = _build_invalidator()
        self.assertEqual(inv.chain_name, "gnosis")
        self.assertFalse(inv.running)

    def test_init_custom_chain(self):
        contracts = {
            "base": {"Pool": ADDR_STAKING_1},
        }
        inv = _build_invalidator(chain_name="base", staking_contracts=contracts)
        self.assertEqual(inv.chain_name, "base")
        self.assertEqual(inv.staking_addresses, [ADDR_STAKING_1])

    def test_init_stores_web3_from_chain_interface(self):
        web3 = MagicMock(name="web3_mock")
        ci = MagicMock()
        ci.web3 = web3
        inv = _build_invalidator(web3=web3, chain_interface=ci)
        self.assertIs(inv.web3, web3)

    def test_init_extracts_addresses_from_constants(self):
        inv = _build_invalidator()
        self.assertEqual(len(inv.staking_addresses), 2)
        self.assertIn(ADDR_STAKING_1, inv.staking_addresses)
        self.assertIn(ADDR_STAKING_2, inv.staking_addresses)

    def test_init_no_contracts_for_chain(self):
        """If the chain has no staking contracts the list should be empty."""
        inv = _build_invalidator(
            chain_name="gnosis",
            staking_contracts={"base": {"Pool": ADDR_STAKING_1}},
        )
        self.assertEqual(inv.staking_addresses, [])


class TestStartStop(unittest.TestCase):
    """Tests for start / stop lifecycle."""

    def test_start_sets_running(self):
        inv = _build_invalidator()
        # Patch _monitor_loop so the thread exits immediately
        inv._monitor_loop = MagicMock()

        inv.start()
        self.assertTrue(inv.running)

    def test_stop_clears_running(self):
        inv = _build_invalidator()
        inv.running = True
        inv.stop()
        self.assertFalse(inv.running)

    def test_start_spawns_daemon_thread(self):
        inv = _build_invalidator()
        inv._monitor_loop = MagicMock()

        with patch("threading.Thread") as mock_thread_cls:
            mock_thread = MagicMock()
            mock_thread_cls.return_value = mock_thread

            inv.start()

            mock_thread_cls.assert_called_once_with(
                target=inv._monitor_loop, daemon=True
            )
            mock_thread.start.assert_called_once()


class TestMonitorLoop(unittest.TestCase):
    """Tests for _monitor_loop."""

    def test_loop_exits_when_running_set_to_false(self):
        """The loop should exit promptly after running is cleared."""
        inv = _build_invalidator()
        inv.web3.eth.block_number = 100

        call_count = 0

        def fake_sleep(seconds):
            nonlocal call_count
            call_count += 1
            # After first sleep, stop the loop
            inv.running = False

        with patch("time.sleep", side_effect=fake_sleep):
            inv.running = True
            inv._monitor_loop()

        self.assertGreaterEqual(call_count, 1)

    def test_loop_calls_check_events_on_new_blocks(self):
        """When block number advances, _check_events should be called."""
        inv = _build_invalidator()

        # Simulate block advancing: initial=100, then 105
        block_values = [100, 105]
        block_iter = iter(block_values)
        type(inv.web3.eth).block_number = property(
            lambda self: next(block_iter)
        )

        inv._check_events = MagicMock()

        def fake_sleep(seconds):
            inv.running = False

        with patch("time.sleep", side_effect=fake_sleep):
            inv.running = True
            inv._monitor_loop()

        inv._check_events.assert_called_once_with(101, 105)

    def test_loop_does_not_call_check_events_when_no_new_blocks(self):
        """If block number doesn't advance, _check_events should not be called."""
        inv = _build_invalidator()

        type(inv.web3.eth).block_number = property(lambda self: 100)

        inv._check_events = MagicMock()

        def fake_sleep(seconds):
            inv.running = False

        with patch("time.sleep", side_effect=fake_sleep):
            inv.running = True
            inv._monitor_loop()

        inv._check_events.assert_not_called()

    def test_loop_handles_initial_block_number_exception(self):
        """If getting initial block_number fails, last_block defaults to 0."""
        inv = _build_invalidator()

        # First call (initial) raises, second call in loop returns 50
        calls = [0]

        def block_number_getter(self):
            calls[0] += 1
            if calls[0] == 1:
                raise ConnectionError("RPC down")
            return 50

        type(inv.web3.eth).block_number = property(block_number_getter)

        inv._check_events = MagicMock()

        def fake_sleep(seconds):
            inv.running = False

        with patch("time.sleep", side_effect=fake_sleep):
            inv.running = True
            inv._monitor_loop()

        # last_block was 0, current=50, so check_events(1, 50)
        inv._check_events.assert_called_once_with(1, 50)

    def test_loop_handles_exception_during_iteration(self):
        """Exceptions during the loop body should be caught and logged."""
        inv = _build_invalidator()

        # First call to block_number succeeds (initial), second raises
        calls = [0]

        def block_number_getter(self):
            calls[0] += 1
            if calls[0] == 1:
                return 100
            raise RuntimeError("RPC failure")

        type(inv.web3.eth).block_number = property(block_number_getter)

        def fake_sleep(seconds):
            inv.running = False

        with patch("time.sleep", side_effect=fake_sleep):
            inv.running = True
            inv._monitor_loop()  # Should not raise


class TestCheckEvents(unittest.TestCase):
    """Tests for _check_events."""

    def test_returns_early_when_no_staking_addresses(self):
        """If there are no staking addresses, the method should return immediately."""
        inv = _build_invalidator(
            staking_contracts={"gnosis": {}},
        )
        inv.staking_addresses = []

        # Should not try to call web3.eth.get_logs
        inv._check_events(1, 10)
        inv.web3.eth.get_logs.assert_not_called()

    def test_caps_block_range_to_100(self):
        """If to_block - from_block > 100, from_block should be capped."""
        inv = _build_invalidator()
        inv.web3.eth.get_logs.return_value = []

        inv._check_events(0, 200)

        # from_block should have been adjusted to 200 - 100 = 100
        filter_arg = inv.web3.eth.get_logs.call_args[0][0]
        self.assertEqual(filter_arg["fromBlock"], 100)
        self.assertEqual(filter_arg["toBlock"], 200)

    def test_normal_block_range_not_capped(self):
        """A normal range (<= 100 blocks) should remain as-is."""
        inv = _build_invalidator()
        inv.web3.eth.get_logs.return_value = []

        inv._check_events(50, 100)

        filter_arg = inv.web3.eth.get_logs.call_args[0][0]
        self.assertEqual(filter_arg["fromBlock"], 50)
        self.assertEqual(filter_arg["toBlock"], 100)

    def test_passes_staking_addresses_in_filter(self):
        """The filter should include all staking addresses."""
        inv = _build_invalidator()
        inv.web3.eth.get_logs.return_value = []

        inv._check_events(10, 20)

        filter_arg = inv.web3.eth.get_logs.call_args[0][0]
        self.assertEqual(filter_arg["address"], inv.staking_addresses)

    def test_checkpoint_event_topic_uses_keccak(self):
        """The filter should compute the Checkpoint topic via web3.keccak."""
        inv = _build_invalidator()
        inv.web3.keccak.return_value = MagicMock(hex=MagicMock(return_value="0xabc123"))
        inv.web3.eth.get_logs.return_value = []

        inv._check_events(10, 20)

        inv.web3.keccak.assert_called_once_with(
            text="Checkpoint(uint256,uint256,uint256,uint256,uint256,uint256,uint256,uint256)"
        )

        filter_arg = inv.web3.eth.get_logs.call_args[0][0]
        self.assertEqual(filter_arg["topics"], ["0xabc123"])

    def test_invalidates_cache_for_checkpoint_event(self):
        """When a Checkpoint log is found, the cached instance should get clear_epoch_cache called."""
        inv = _build_invalidator()
        inv.web3.keccak.return_value = MagicMock(hex=MagicMock(return_value="0xabc123"))

        mock_instance = MagicMock()
        inv.contract_cache.get_if_cached.return_value = mock_instance

        log_entry = {
            "address": ADDR_STAKING_1,
            "blockNumber": 42,
        }
        inv.web3.eth.get_logs.return_value = [log_entry]

        inv._check_events(10, 20)

        # Should have tried to get the cached instance
        inv.contract_cache.get_if_cached.assert_called()
        # And cleared its epoch cache
        mock_instance.clear_epoch_cache.assert_called_once()

    def test_no_clear_when_instance_not_cached(self):
        """If get_if_cached returns None, clear_epoch_cache should not be called."""
        inv = _build_invalidator()
        inv.web3.keccak.return_value = MagicMock(hex=MagicMock(return_value="0xabc123"))
        inv.contract_cache.get_if_cached.return_value = None

        log_entry = {
            "address": ADDR_STAKING_1,
            "blockNumber": 42,
        }
        inv.web3.eth.get_logs.return_value = [log_entry]

        # Should not raise
        inv._check_events(10, 20)

    def test_handles_multiple_logs(self):
        """Multiple Checkpoint logs should each trigger cache invalidation."""
        inv = _build_invalidator()
        inv.web3.keccak.return_value = MagicMock(hex=MagicMock(return_value="0xabc123"))

        mock_instance_1 = MagicMock()
        mock_instance_2 = MagicMock()

        # Return different instances for different addresses
        def get_cached_side_effect(cls, addr, chain):
            if addr == ADDR_STAKING_1:
                return mock_instance_1
            elif addr == ADDR_STAKING_2:
                return mock_instance_2
            return None

        inv.contract_cache.get_if_cached.side_effect = get_cached_side_effect

        logs = [
            {"address": ADDR_STAKING_1, "blockNumber": 42},
            {"address": ADDR_STAKING_2, "blockNumber": 43},
        ]
        inv.web3.eth.get_logs.return_value = logs

        inv._check_events(10, 20)

        mock_instance_1.clear_epoch_cache.assert_called_once()
        mock_instance_2.clear_epoch_cache.assert_called_once()

    def test_handles_get_logs_exception(self):
        """An exception from web3.eth.get_logs should be caught and logged."""
        inv = _build_invalidator()
        inv.web3.eth.get_logs.side_effect = Exception("RPC error")

        # Should not raise
        inv._check_events(10, 20)

    def test_handles_get_contract_exception(self):
        """An exception from contract_cache.get_contract should be caught."""
        inv = _build_invalidator()
        inv.contract_cache.get_contract.side_effect = Exception("Cache error")

        # Should not raise
        inv._check_events(10, 20)

    def test_calls_get_contract_to_ensure_cached(self):
        """_check_events should call get_contract to ensure contract is cached."""
        inv = _build_invalidator()
        inv.web3.keccak.return_value = MagicMock(hex=MagicMock(return_value="0xabc123"))
        inv.web3.eth.get_logs.return_value = []

        inv._check_events(10, 20)

        from iwa.plugins.olas.contracts.staking import StakingContract

        inv.contract_cache.get_contract.assert_called_once_with(
            StakingContract, inv.staking_addresses[0], "gnosis"
        )

    def test_exact_boundary_100_blocks_not_capped(self):
        """If range is exactly 100 blocks, from_block should NOT be capped."""
        inv = _build_invalidator()
        inv.web3.eth.get_logs.return_value = []

        inv._check_events(100, 200)

        filter_arg = inv.web3.eth.get_logs.call_args[0][0]
        # 200 - 100 == 100, which is NOT > 100, so no capping
        self.assertEqual(filter_arg["fromBlock"], 100)

    def test_boundary_101_blocks_is_capped(self):
        """If range is 101 blocks, from_block should be capped."""
        inv = _build_invalidator()
        inv.web3.eth.get_logs.return_value = []

        inv._check_events(99, 200)

        filter_arg = inv.web3.eth.get_logs.call_args[0][0]
        # 200 - 99 = 101 > 100, so from_block = 200 - 100 = 100
        self.assertEqual(filter_arg["fromBlock"], 100)


class TestIntegrationStartStop(unittest.TestCase):
    """Integration-style test for start/stop with a real thread."""

    def test_start_stop_lifecycle(self):
        """Start launches a thread; stop terminates the loop."""
        inv = _build_invalidator()
        inv.web3.eth.block_number = 100

        original_sleep = time.sleep

        def controlled_sleep(seconds):
            # Use a very short sleep so the test is fast
            original_sleep(0.01)

        with patch("time.sleep", side_effect=controlled_sleep):
            inv.start()
            self.assertTrue(inv.running)

            # Let the thread run briefly
            original_sleep(0.05)

            inv.stop()
            self.assertFalse(inv.running)

            # Wait for thread to actually exit
            original_sleep(0.05)


if __name__ == "__main__":
    unittest.main()
