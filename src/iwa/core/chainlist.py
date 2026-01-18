"""Module for fetching and parsing RPCs from Chainlist.org."""
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import requests


@dataclass
class RPCNode:
    """Represents a single RPC node with its properties."""

    url: str
    is_working: bool
    privacy: Optional[str] = None
    tracking: Optional[str] = None

    @property
    def is_tracking(self) -> bool:
        """Returns True if the RPC is known to track user data."""
        return self.privacy == "privacy" or self.tracking in ("limited", "yes")

class ChainlistRPC:
    """Fetcher and parser for Chainlist RPC data."""

    URL = "https://chainlist.org/rpcs.json"

    def __init__(self) -> None:
        """Initialize the ChainlistRPC instance."""
        self._data: List[Dict[str, Any]] = []

    def fetch_data(self) -> None:
        """Fetches the RPC data from Chainlist."""
        try:
            response = requests.get(self.URL, timeout=10)
            response.raise_for_status()
            self._data = response.json()
        except requests.RequestException as e:
            print(f"Error fetching Chainlist data: {e}")
            self._data = []

    def get_chain_data(self, chain_id: int) -> Optional[Dict[str, Any]]:
        """Returns the raw chain data for a specific chain ID."""
        if not self._data:
            self.fetch_data()

        for entry in self._data:
            if entry.get('chainId') == chain_id:
                return entry
        return None

    def get_rpcs(self, chain_id: int) -> List[RPCNode]:
        """Returns a list of RPCNode objects for a parsed and cleaner view."""
        chain_data = self.get_chain_data(chain_id)
        if not chain_data:
            return []

        raw_rpcs = chain_data.get('rpc', [])
        nodes = []
        for rpc in raw_rpcs:
            nodes.append(RPCNode(
                url=rpc.get('url', ''),
                is_working=True,
                privacy=rpc.get('privacy'),
                tracking=rpc.get('tracking')
            ))
        return nodes

    def get_https_rpcs(self, chain_id: int) -> List[str]:
        """Returns a list of HTTPS RPC URLs for the given chain."""
        rpcs = self.get_rpcs(chain_id)
        return [
            node.url for node in rpcs
            if node.url.startswith("https://") or node.url.startswith("http://")
        ]

    def get_wss_rpcs(self, chain_id: int) -> List[str]:
        """Returns a list of WSS RPC URLs for the given chain."""
        rpcs = self.get_rpcs(chain_id)
        return [
            node.url for node in rpcs
            if node.url.startswith("wss://") or node.url.startswith("ws://")
        ]
