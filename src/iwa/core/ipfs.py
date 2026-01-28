"""IPFS utilities for pushing and retrieving data.

This module provides functionality to push metadata to IPFS using
direct HTTP API calls, avoiding heavy dependencies like open-aea.
"""

import hashlib
import json
import uuid
from typing import TYPE_CHECKING, Any, Dict, Optional, Tuple

import aiohttp
from multiformats import CID

from iwa.core.http import create_retry_session
from iwa.core.models import Config

if TYPE_CHECKING:
    import requests

# Global persistent sessions (reused across calls to prevent FD leaks)
_SYNC_SESSION: Optional["requests.Session"] = None
_ASYNC_SESSION: Optional[aiohttp.ClientSession] = None


def _compute_cid_v1_hex(data: bytes) -> str:
    """Compute CIDv1 hex representation from raw data.

    This creates a CIDv1 with:
    - multibase: 'f' (base16 lowercase)
    - version: 1
    - codec: raw (0x55)
    - multihash: sha2-256

    :param data: The raw data bytes.
    :return: The CIDv1 as hex string (f01...).
    """
    # SHA-256 hash
    digest = hashlib.sha256(data).digest()

    # Build CIDv1: raw codec (0x55), sha2-256 multihash (0x12), 32 bytes length (0x20)
    cid = CID("base16", 1, "raw", ("sha2-256", digest))
    return str(cid)


async def push_to_ipfs_async(
    data: bytes,
    api_url: Optional[str] = None,
    pin: bool = True,
) -> Tuple[str, str]:
    """Push raw data to IPFS using the HTTP API.

    :param data: The data bytes to push.
    :param api_url: Optional IPFS API URL. Defaults to IPFS_API_URL env var or localhost.
    :param pin: Whether to pin the content (default True).
    :return: Tuple of (CIDv1 string, CIDv1 hex representation).
    """
    url = api_url or Config().core.ipfs_api_url
    endpoint = f"{url}/api/v0/add"

    params = {"pin": str(pin).lower(), "cid-version": "1"}

    # Create multipart form data
    form = aiohttp.FormData()
    form.add_field("file", data, filename="data", content_type="application/octet-stream")

    global _ASYNC_SESSION
    if _ASYNC_SESSION is None or _ASYNC_SESSION.closed:
        _ASYNC_SESSION = aiohttp.ClientSession()

    async with _ASYNC_SESSION.post(endpoint, data=form, params=params) as response:
        response.raise_for_status()
        result = await response.json()

    cid_str = result["Hash"]
    cid = CID.decode(cid_str)

    # Convert to hex representation (f01 prefix for base16 + CIDv1)
    # We need to reconstruct with the multihash as a tuple (name, digest)
    cid_hex = str(CID("base16", cid.version, cid.codec, (cid.hashfun.name, cid.raw_digest)))

    return cid_str, cid_hex


def push_to_ipfs_sync(
    data: bytes,
    api_url: Optional[str] = None,
    pin: bool = True,
) -> Tuple[str, str]:
    """Push raw data to IPFS using the HTTP API (synchronous version).

    :param data: The data bytes to push.
    :param api_url: Optional IPFS API URL. Defaults to IPFS_API_URL env var or localhost.
    :param pin: Whether to pin the content (default True).
    :return: Tuple of (CIDv1 string, CIDv1 hex representation).
    """
    global _SYNC_SESSION

    if _SYNC_SESSION is None:
        _SYNC_SESSION = create_retry_session()

    url = api_url or Config().core.ipfs_api_url
    endpoint = f"{url}/api/v0/add"

    params = {"pin": str(pin).lower(), "cid-version": "1"}

    files = {"file": ("data", data, "application/octet-stream")}

    response = _SYNC_SESSION.post(endpoint, files=files, params=params, timeout=60)
    response.raise_for_status()
    result = response.json()

    cid_str = result["Hash"]
    cid = CID.decode(cid_str)

    # Convert to hex representation (f01 prefix for base16 + CIDv1)
    # We need to reconstruct with the multihash as a tuple (name, digest)
    cid_hex = str(CID("base16", cid.version, cid.codec, (cid.hashfun.name, cid.raw_digest)))

    return cid_str, cid_hex


def push_metadata_to_ipfs(
    metadata: Dict[str, Any],
    extra_attributes: Optional[Dict[str, Any]] = None,
    api_url: Optional[str] = None,
) -> Tuple[str, str]:
    """Push a metadata dict to IPFS synchronously.

    A unique nonce is added automatically to ensure uniqueness.

    :param metadata: Metadata dictionary to push.
    :param extra_attributes: Extra attributes to include in the metadata.
    :param api_url: Optional IPFS API URL.
    :return: Tuple of (truncated hash with 0x prefix for contract calls, full CID hex).
    """
    data = {**metadata, "nonce": str(uuid.uuid4())}
    if extra_attributes:
        data.update(extra_attributes)

    json_bytes = json.dumps(data, separators=(",", ":")).encode("utf-8")
    _, cid_hex = push_to_ipfs_sync(json_bytes, api_url)

    # The truncated hash format expected by mech contracts: 0x + hex after the f01 prefix
    # CIDv1 hex format: f01{codec}{multihash} -> we want just the multihash part
    # For compatibility with triton, we return "0x" + cid_hex[9:] (skip f01 + 2-byte codec)
    truncated_hash = "0x" + cid_hex[9:]

    return truncated_hash, cid_hex


def metadata_to_request_data(
    metadata: Dict[str, Any],
    api_url: Optional[str] = None,
) -> bytes:
    """Convert a metadata dict to mech request data by pushing to IPFS.

    :param metadata: Metadata dictionary (typically contains 'prompt', 'tool', etc.).
    :param api_url: Optional IPFS API URL.
    :return: The request data as bytes (truncated IPFS hash).
    """
    truncated_hash, _ = push_metadata_to_ipfs(metadata, api_url=api_url)
    return bytes.fromhex(truncated_hash[2:])
