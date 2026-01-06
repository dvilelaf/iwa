"""Event Monitor for Iwa TUI"""

import time
from typing import Any, Callable, Dict, List

from web3 import Web3

from iwa.core.chain import ChainInterfaces
from iwa.core.utils import configure_logger

logger = configure_logger()


class EventMonitor:
    """Monitors chain for events affecting specific addresses."""

    def __init__(
        self, addresses: List[str], callback: Callable, chain_name: str = "gnosis"
    ) -> None:
        """Initialize events monitor."""
        self.chain_name = chain_name
        self.addresses = [Web3.to_checksum_address(addr) for addr in addresses]
        self.callback = callback
        self.chain_interface = ChainInterfaces().get(chain_name)
        self.web3 = self.chain_interface.web3
        self.running = False
        if self.chain_interface.chain.rpc:
            try:
                self.last_checked_block = self.web3.eth.block_number
            except Exception:
                self.last_checked_block = 0
        else:
            self.last_checked_block = 0

    def start(self):
        """Start monitoring loop."""
        self.running = True
        logger.info(
            f"Starting EventMonitor for {len(self.addresses)} addresses on {self.chain_interface.chain.name}"
        )

        if not self.chain_interface.chain.rpc:
            logger.error(
                f"Cannot start EventMonitor: No RPC URL found for chain {self.chain_interface.chain.name}"
            )
            self.running = False
            return

        logger.info(f"Monitoring addresses: {self.addresses}")

        while self.running:
            try:
                self.check_activity()
            except Exception as e:
                logger.error(f"Error in EventMonitor: {e}")

            time.sleep(6)

    def stop(self):
        """Stop monitoring."""
        self.running = False

    def check_activity(self):
        """Check for new blocks and logs."""
        try:
            latest_block = self.web3.eth.block_number
        except Exception as e:
            logger.error(f"Failed to get block number: {e}")
            return

        if not self._should_check(latest_block):
            return

        logger.info(f"New block detected: {latest_block} (Last: {self.last_checked_block})")

        from_block, to_block = self._get_block_range(latest_block)

        found_txs = []
        found_txs.extend(self._check_native_transfers(from_block, to_block))
        found_txs.extend(self._check_erc20_transfers(from_block, to_block))

        self.last_checked_block = to_block

        if found_txs:
            self.callback(found_txs)

    def _should_check(self, latest_block: int) -> bool:
        return latest_block > self.last_checked_block

    def _get_block_range(self, latest_block: int) -> tuple[int, int]:
        from_block = self.last_checked_block + 1
        to_block = latest_block

        if to_block - from_block > 100:
            from_block = to_block - 100
        return from_block, to_block

    def _check_native_transfers(self, from_block: int, to_block: int) -> List[Dict[str, Any]]:
        found_txs = []
        my_addrs = set(a.lower() for a in self.addresses)

        for block_num in range(from_block, to_block + 1):
            try:
                block = self.web3.eth.get_block(block_num, full_transactions=True)
                for tx in block.transactions:
                    # Handle case where RPC returns hash despite full_transactions=True
                    if isinstance(tx, (str, bytes)):
                        logger.debug(f"Got tx hash {tx}, fetching details...")
                        tx = self.web3.eth.get_transaction(tx)

                    # Normalize tx addresses to lower, handling None for contract creation
                    tx_from = tx.get("from", "").lower() if tx.get("from") else None
                    tx_to = tx.get("to", "").lower() if tx.get("to") else None

                    if (tx_from and tx_from in my_addrs) or (tx_to and tx_to in my_addrs):
                        logger.info(
                            f"Native activity detected in block {block_num} tx {tx['hash'].hex()}"
                        )
                        found_txs.append(
                            {
                                "hash": tx["hash"].hex(),
                                # Use original checksummed 'from' if available in tx, or re-checksum
                                "from": Web3.to_checksum_address(tx_from) if tx_from else None,
                                "to": Web3.to_checksum_address(tx_to) if tx_to else None,
                                "value": tx.get("value", 0),
                                "token": "NATIVE",
                                "timestamp": block.timestamp,
                                "chain": self.chain_name,
                            }
                        )
            except Exception as e:
                logger.warning(f"Failed to fetch/process block {block_num}: {e}")

        return found_txs

    def _check_erc20_transfers(self, from_block: int, to_block: int) -> List[Dict[str, Any]]:
        found_txs = []
        my_addrs = set(a.lower() for a in self.addresses)

        transfer_topic = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
        padded_addresses = [
            "0x000000000000000000000000" + addr.lower().replace("0x", "") for addr in self.addresses
        ]

        try:
            # Efficiently Query 1: Transfers FROM our addresses (Topic 1)
            logs_sent = self.web3.eth.get_logs(
                {
                    "fromBlock": from_block,
                    "toBlock": to_block,
                    "topics": [transfer_topic, padded_addresses],
                }
            )

            # Efficiently Query 2: Transfers TO our addresses (Topic 2)
            logs_received = self.web3.eth.get_logs(
                {
                    "fromBlock": from_block,
                    "toBlock": to_block,
                    "topics": [transfer_topic, None, padded_addresses],
                }
            )

            all_logs = logs_sent + logs_received

            for log in all_logs:
                if len(log["topics"]) < 3:
                    continue
                # topic[1] is from, topic[2] is to. (32 bytes)
                t_from = "0x" + log["topics"][1].hex()[-40:]
                t_to = "0x" + log["topics"][2].hex()[-40:]

                # Check for uniqueness? Hash is unique key in UI anyway.

                # Double check (though RPC filter should have ensured it)
                t_from_lower = t_from.lower()
                t_to_lower = t_to.lower()

                is_related = False
                for my_addr in my_addrs:
                    if my_addr in t_from_lower or my_addr in t_to_lower:
                        is_related = True
                        break

                if is_related:
                    found_txs.append(
                        {
                            "hash": log["transactionHash"].hex(),
                            "from": Web3.to_checksum_address(t_from),
                            "to": Web3.to_checksum_address(t_to),
                            "value": int(
                                log["data"].hex()
                                if isinstance(log["data"], bytes)
                                else log["data"],
                                16,
                            )
                            if log.get("data")
                            else 0,
                            "token": "TOKEN",
                            "contract_address": log["address"],
                            "timestamp": 0,  # Would require block fetch
                            "chain": self.chain_name,
                        }
                    )

        except Exception as e:
            logger.warning(f"Failed to fetch logs: {e}")

        return found_txs
