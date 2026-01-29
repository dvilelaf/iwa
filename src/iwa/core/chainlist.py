"""Module for fetching and parsing RPCs from Chainlist.org."""

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import requests

from iwa.core.constants import CACHE_DIR
from iwa.core.utils import configure_logger

logger = configure_logger()

# -- RPC probing constants --------------------------------------------------

MAX_CHAINLIST_CANDIDATES = 15  # Probe at most this many candidates
PROBE_TIMEOUT = 5.0  # Seconds per probe request
MAX_BLOCK_LAG = 10  # Blocks behind majority → considered stale


def _normalize_url(url: str) -> str:
    """Normalize an RPC URL for deduplication (lowercase, strip trailing slash)."""
    return url.rstrip("/").lower()


def _is_template_url(url: str) -> bool:
    """Return True if the URL contains template variables requiring an API key."""
    return "${" in url or "{" in url


def probe_rpc(
    url: str,
    timeout: float = PROBE_TIMEOUT,
    session: Optional[requests.Session] = None,
) -> Optional[Tuple[str, float, int]]:
    """Probe an RPC endpoint with eth_blockNumber.

    Returns ``(url, latency_ms, block_number)`` on success, or ``None``
    if the endpoint is unreachable, slow, or returns invalid data.

    Args:
        url: The RPC endpoint URL to probe.
        timeout: Request timeout in seconds.
        session: Optional requests.Session for connection reuse. If None,
                 creates a temporary session that is properly closed.

    """
    # Use provided session or create temporary one with proper cleanup
    own_session = session is None
    if own_session:
        session = requests.Session()

    try:
        start = time.monotonic()
        resp = session.post(
            url,
            json={"jsonrpc": "2.0", "method": "eth_blockNumber", "params": [], "id": 1},
            timeout=timeout,
        )
        latency_ms = (time.monotonic() - start) * 1000
        data = resp.json()
        block_hex = data.get("result")
        if not block_hex or not isinstance(block_hex, str) or block_hex == "0x0":
            return None
        return (url, latency_ms, int(block_hex, 16))
    except Exception:
        return None
    finally:
        if own_session:
            session.close()


def _filter_candidates(
    nodes: "List[RPCNode]",
    existing_normalized: set,
) -> List[str]:
    """Filter ChainList nodes to usable HTTPS candidates."""
    candidates: List[str] = []
    for node in nodes:
        url = node.url
        if not url.startswith("https://"):
            continue
        if _is_template_url(url):
            continue
        if _normalize_url(url) in existing_normalized:
            continue
        candidates.append(url)
        if len(candidates) >= MAX_CHAINLIST_CANDIDATES:
            break
    return candidates


def _probe_candidates(
    candidates: List[str],
) -> List[Tuple[str, float, int]]:
    """Probe a list of RPC URLs in parallel, returning successful results.

    Uses a shared session for all probes to enable connection pooling and
    ensure proper cleanup of all connections when probing completes.
    """
    results: List[Tuple[str, float, int]] = []
    # Use a shared session with connection pooling for all probes
    # This prevents FD leaks from individual probe connections
    with requests.Session() as session:
        # Configure connection pool size to match our max workers
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=10,
            pool_maxsize=10,
            max_retries=0,  # No retries - we handle failure gracefully
        )
        session.mount("https://", adapter)
        session.mount("http://", adapter)

        with ThreadPoolExecutor(max_workers=min(len(candidates), 10)) as pool:
            futures = {
                pool.submit(probe_rpc, url, PROBE_TIMEOUT, session): url
                for url in candidates
            }
            for future in as_completed(futures, timeout=15):
                try:
                    result = future.result()
                    if result is not None:
                        results.append(result)
                except Exception:
                    pass
    # Session is closed here via context manager, releasing all connections
    return results


def _rank_and_select(
    results: List[Tuple[str, float, int]],
    candidates: List[str],
    chain_id: int,
    max_results: int,
) -> List[str]:
    """Rank probed RPCs by latency, filtering stale ones."""
    blocks = sorted(r[2] for r in results)
    median_block = blocks[len(blocks) // 2]

    valid = [
        (url, latency)
        for url, latency, block in results
        if median_block - block <= MAX_BLOCK_LAG
    ]
    valid.sort(key=lambda x: x[1])

    selected = [url for url, _ in valid[:max_results]]
    if selected:
        logger.info(
            f"ChainList: validated {len(selected)}/{len(candidates)} "
            f"candidates for chain {chain_id} "
            f"(median block: {median_block})"
        )
    return selected


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

        # 2. Fetch from remote (use session context for proper cleanup)
        try:
            with requests.Session() as session:
                response = session.get(self.URL, timeout=10)
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
            if entry.get("chainId") == chain_id:
                return entry
        return None

    def get_rpcs(self, chain_id: int) -> List[RPCNode]:
        """Returns a list of RPCNode objects for a parsed and cleaner view."""
        chain_data = self.get_chain_data(chain_id)
        if not chain_data:
            return []

        raw_rpcs = chain_data.get("rpc", [])
        nodes = []
        for rpc in raw_rpcs:
            nodes.append(
                RPCNode(
                    url=rpc.get("url", ""),
                    is_working=True,
                    privacy=rpc.get("privacy"),
                    tracking=rpc.get("tracking"),
                )
            )
        return nodes

    def get_https_rpcs(self, chain_id: int) -> List[str]:
        """Returns a list of HTTPS RPC URLs for the given chain."""
        rpcs = self.get_rpcs(chain_id)
        return [
            node.url
            for node in rpcs
            if node.url.startswith("https://") or node.url.startswith("http://")
        ]

    def get_wss_rpcs(self, chain_id: int) -> List[str]:
        """Returns a list of WSS RPC URLs for the given chain."""
        rpcs = self.get_rpcs(chain_id)
        return [
            node.url
            for node in rpcs
            if node.url.startswith("wss://") or node.url.startswith("ws://")
        ]

    def get_validated_rpcs(
        self,
        chain_id: int,
        existing_rpcs: List[str],
        max_results: int = 5,
    ) -> List[str]:
        """Return ChainList RPCs filtered, probed, and sorted by quality.

        1. Fetch HTTPS RPCs from ChainList for *chain_id*.
        2. Filter out template URLs, duplicates of *existing_rpcs*, and
           websocket endpoints.
        3. Probe the top candidates in parallel with ``eth_blockNumber``.
        4. Discard RPCs that are stale (block number lagging behind majority).
        5. Return up to *max_results* URLs sorted by latency (fastest first).
        """
        nodes = self.get_rpcs(chain_id)
        if not nodes:
            return []

        existing_normalized = {_normalize_url(u) for u in existing_rpcs}
        candidates = _filter_candidates(nodes, existing_normalized)
        if not candidates:
            return []

        results = _probe_candidates(candidates)
        if not results:
            return []

        selected = _rank_and_select(results, candidates, chain_id, max_results)
        return selected
