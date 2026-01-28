"""Event-based cache invalidation for Olas contracts."""

from loguru import logger

from iwa.core.contracts.cache import ContractCache
from iwa.plugins.olas.contracts.staking import StakingContract


class OlasEventInvalidator:
    """Monitors OLAS events and invalidates caches."""

    def __init__(self, chain_name: str = "gnosis"):
        """Initialize the invalidator."""
        self.chain_name = chain_name
        self.contract_cache = ContractCache()

        # We need to find active staking contracts to monitor
        # For now, we'll use a dynamic approach or configuration
        # Ideally, this service would know about all deployed staking contracts
        # But efficiently, we might just want to monitor the ones in our cache?
        # A simple approach for this MVP: Monitor contracts currently in the cache
        # OR monitor a known set of staking contracts from constants.

        # Since EventMonitor requires a list of addresses upfront, let's use the ones
        # defined in constants if available, or just rely on what's active.
        # However, EventMonitor checks transfers, not generic logs for specific events.
        # The base EventMonitor in iwa.core.monitor is too specific (transfers).
        # We should implement a specific loop here or extend EventMonitor.
        # To avoid complex inheritance of a class not designed for extension (EventMonitor),
        # we will implement a focused loop using the same pattern.

        from iwa.core.chain import ChainInterfaces
        from iwa.plugins.olas.constants import OLAS_TRADER_STAKING_CONTRACTS

        self.chain_interface = ChainInterfaces().get(chain_name)
        self.web3 = self.chain_interface.web3

        # Get addresses to monitor
        contracts = OLAS_TRADER_STAKING_CONTRACTS.get(chain_name, {})
        self.staking_addresses = [addr for _, addr in contracts.items()]

        self.running = False

    def start(self):
        """Start the event monitoring loop."""
        import threading

        self.running = True
        thread = threading.Thread(target=self._monitor_loop, daemon=True)
        thread.start()
        logger.info(f"Started OlasEventInvalidator for {len(self.staking_addresses)} contracts")

    def stop(self):
        """Stop the monitoring loop."""
        self.running = False

    def _monitor_loop(self):
        """Main monitoring loop."""
        import time

        try:
            last_block = self.web3.eth.block_number
        except Exception:
            last_block = 0

        while self.running:
            try:
                current_block = self.web3.eth.block_number

                if current_block > last_block:
                    self._check_events(last_block + 1, current_block)
                    last_block = current_block

            except Exception as e:
                logger.error(f"Error in OlasEventInvalidator: {e}")

            time.sleep(10)  # check every 10 seconds

    def _check_events(self, from_block: int, to_block: int):
        """Check for relevant events in the block range."""
        # Cap range
        if to_block - from_block > 100:
            from_block = to_block - 100

        # We care about Checkpoint events on StakingContracts
        # Event signature for Checkpoint: Checkpoint(uint256,uint256,uint256,uint256,uint256,uint256,uint256,uint256)
        # Actually easier to use the contract instance to get the topic or event object

        # Need ABI for this. Let's assume we can get it from a dummy contract instance
        if not self.staking_addresses:
            return

        # 1. Checkpoint events
        # Topic 0 for Checkpoint event
        # We can construct a filter for all staking addresses

        try:
            # Ensure contract is cached for later use
            self.contract_cache.get_contract(
                StakingContract, self.staking_addresses[0], self.chain_name
            )

            logs = self.web3.eth.get_logs(
                {
                    "fromBlock": from_block,
                    "toBlock": to_block,
                    "address": self.staking_addresses,
                    "topics": [
                        self.web3.keccak(
                            text="Checkpoint(uint256,uint256,uint256,uint256,uint256,uint256,uint256,uint256)"
                        ).hex()
                    ],
                    # Note: signature might vary, safer to use the event object if ABI allows
                }
            )

            # If we used the contract event object to filter, it handles the topic generation:
            # logs = checkpoint_event_abi.get_logs(fromBlock=from_block, toBlock=to_block)
            # But get_logs on the contract object filters by THAT contract address usually?
            # web3.eth.get_logs is broader.

            for log in logs:
                addr = log["address"]
                logger.info(f"Checkpoint detected on {addr} at block {log['blockNumber']}")

                # Invalidate cache for this contract
                # We want to call clear_epoch_cache on the EXISTING cached instance if present
                # ContractCache().get_contract(...) might return it or create new.
                # We need a way to 'get if exists' or assume get_contract is cheap enough.
                # Specifically we want to clear the EPOCH cache, not just destroy the instance
                # (though destroying it works too, it's just less efficient for the next call).

                # Option A: Just invalidate the instance
                # self.contract_cache.invalidate(StakingContract, addr, self.chain_name)

                # Option B: Get instance and clear specific cache (safe public access)
                instance = self.contract_cache.get_if_cached(StakingContract, addr, self.chain_name)
                if instance:
                    instance.clear_epoch_cache()
                    logger.debug(f"Cleared epoch cache for {addr}")

        except Exception as e:
            logger.warning(f"Failed to check logs in invalidator: {e}")
