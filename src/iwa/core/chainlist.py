"""Module for fetching and parsing RPCs from Chainlist.org."""
import json
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import requests

from iwa.core.constants import CACHE_DIR


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
    CACHE_PATH = CACHE_DIR / "chainlist_rpcs.json"
    CACHE_TTL = 86400  # 24 hours

    def __init__(self) -> None:
        """Initialize the ChainlistRPC instance."""
        self._data: List[Dict[str, Any]] = []

    def fetch_data(self, force_refresh: bool = False) -> None:
        """Fetches the RPC data from Chainlist with local caching."""
        # 1. Try local cache first unless force_refresh is requested
        if not force_refresh and self.CACHE_PATH.exists():
            try:
                mtime = self.CACHE_PATH.stat().st_mtime
                if time.time() - mtime < self.CACHE_TTL:
                    with self.CACHE_PATH.open("r") as f:
                        self._data = json.load(f)
                    if self._data:
                        return
            except Exception as e:
                print(f"Error reading Chainlist cache: {e}")

        # 2. Fetch from remote
        try:
            response = requests.get(self.URL, timeout=10)
            response.raise_for_status()
            self._data = response.json()

            # 3. Update local cache
            if self._data:
                self.CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
                with self.CACHE_PATH.open("w") as f:
                    json.dump(self._data, f)
        except requests.RequestException as e:
            print(f"Error fetching Chainlist data from {self.URL}: {e}")
            # Fallback to expired cache if available
            if not self._data and self.CACHE_PATH.exists():
                try:
                    with self.CACHE_PATH.open("r") as f:
                        self._data = json.load(f)
                except Exception:
                    pass
            if not self._data:
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
