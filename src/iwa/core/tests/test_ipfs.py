"""Tests for IPFS module."""

import hashlib
import json
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import pytest

import iwa.core.ipfs as ipfs_module
from iwa.core.ipfs import (
    _compute_cid_v1_hex,
    metadata_to_request_data,
    push_metadata_to_ipfs,
    push_to_ipfs_async,
    push_to_ipfs_sync,
)


@pytest.fixture
def mock_config():
    """Mock config."""
    with patch("iwa.core.ipfs.Config") as mock_c:
        mock_c.return_value.core.ipfs_api_url = "http://fake-ipfs:5001"
        yield mock_c


@pytest.fixture
def mock_cid_decode():
    """Mock CID.decode and CID constructor."""
    with patch("iwa.core.ipfs.CID") as mock_cid:
        # CID.decode returns an object with version, codec, hashfun.name, raw_digest
        mock_decoded = MagicMock()
        mock_decoded.version = 1
        mock_decoded.codec = "raw"
        mock_decoded.hashfun.name = "sha2-256"
        mock_decoded.raw_digest = b"digest"

        mock_cid.decode.return_value = mock_decoded
        # CID() constructor returns a stringifiable object
        mock_cid.return_value = MagicMock(__str__=lambda self: "f01551220abcdef")
        yield mock_cid


@pytest.fixture(autouse=True)
def reset_global_sessions():
    """Reset global sessions before each test to ensure isolation."""
    old_sync = ipfs_module._SYNC_SESSION
    old_async = ipfs_module._ASYNC_SESSION
    ipfs_module._SYNC_SESSION = None
    ipfs_module._ASYNC_SESSION = None
    yield
    ipfs_module._SYNC_SESSION = old_sync
    ipfs_module._ASYNC_SESSION = old_async


# ---------------------------------------------------------------------------
# Tests for _compute_cid_v1_hex
# ---------------------------------------------------------------------------


class TestComputeCidV1Hex:
    """Tests for the _compute_cid_v1_hex helper."""

    def test_returns_string(self):
        """_compute_cid_v1_hex returns a string."""
        result = _compute_cid_v1_hex(b"hello world")
        assert isinstance(result, str)

    def test_deterministic(self):
        """Same input always produces the same CID."""
        data = b"deterministic test data"
        result1 = _compute_cid_v1_hex(data)
        result2 = _compute_cid_v1_hex(data)
        assert result1 == result2

    def test_different_data_different_cid(self):
        """Different inputs produce different CIDs."""
        cid1 = _compute_cid_v1_hex(b"data one")
        cid2 = _compute_cid_v1_hex(b"data two")
        assert cid1 != cid2

    def test_cid_starts_with_f(self):
        """CIDv1 hex representation starts with 'f' (base16 multibase prefix)."""
        result = _compute_cid_v1_hex(b"test data")
        assert result.startswith("f")

    def test_empty_data(self):
        """_compute_cid_v1_hex works with empty bytes."""
        result = _compute_cid_v1_hex(b"")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_uses_sha256(self):
        """The CID is built using SHA-256 of the input data."""
        data = b"sha256 test"
        expected_digest = hashlib.sha256(data).digest()

        with patch("iwa.core.ipfs.CID") as mock_cid:
            mock_cid.return_value = MagicMock(__str__=lambda self: "f01551220aabb")
            _compute_cid_v1_hex(data)

            # Verify CID was constructed with the correct parameters
            mock_cid.assert_called_once_with(
                "base16", 1, "raw", ("sha2-256", expected_digest)
            )


# ---------------------------------------------------------------------------
# Tests for push_to_ipfs_sync
# ---------------------------------------------------------------------------


class TestPushToIpfsSync:
    """Tests for push_to_ipfs_sync."""

    def test_uses_persistent_session(self, mock_config, mock_cid_decode):
        """push_to_ipfs_sync creates and reuses a persistent session."""
        with patch("iwa.core.ipfs.create_retry_session") as mock_create:
            mock_session = MagicMock()
            mock_create.return_value = mock_session

            mock_response = MagicMock()
            mock_response.json.return_value = {"Hash": "QmTestHash"}
            mock_session.post.return_value = mock_response

            push_to_ipfs_sync(b"test data")
            mock_create.assert_called_once()
            assert ipfs_module._SYNC_SESSION is mock_session

            # Second call reuses the session
            push_to_ipfs_sync(b"test data 2")
            mock_create.assert_called_once()
            assert mock_session.post.call_count == 2

    def test_uses_custom_api_url(self, mock_cid_decode):
        """push_to_ipfs_sync uses a custom API URL when provided."""
        with patch("iwa.core.ipfs.create_retry_session") as mock_create:
            mock_session = MagicMock()
            mock_create.return_value = mock_session

            mock_response = MagicMock()
            mock_response.json.return_value = {"Hash": "QmTestHash"}
            mock_session.post.return_value = mock_response

            push_to_ipfs_sync(b"data", api_url="http://custom:5001")

            call_args = mock_session.post.call_args
            assert "http://custom:5001/api/v0/add" == call_args[0][0]

    def test_uses_config_default_url(self, mock_config, mock_cid_decode):
        """push_to_ipfs_sync falls back to Config when no api_url given."""
        with patch("iwa.core.ipfs.create_retry_session") as mock_create:
            mock_session = MagicMock()
            mock_create.return_value = mock_session

            mock_response = MagicMock()
            mock_response.json.return_value = {"Hash": "QmTestHash"}
            mock_session.post.return_value = mock_response

            push_to_ipfs_sync(b"data")

            call_args = mock_session.post.call_args
            assert "http://fake-ipfs:5001/api/v0/add" == call_args[0][0]

    def test_passes_pin_true_by_default(self, mock_config, mock_cid_decode):
        """push_to_ipfs_sync passes pin=true by default."""
        with patch("iwa.core.ipfs.create_retry_session") as mock_create:
            mock_session = MagicMock()
            mock_create.return_value = mock_session

            mock_response = MagicMock()
            mock_response.json.return_value = {"Hash": "QmTestHash"}
            mock_session.post.return_value = mock_response

            push_to_ipfs_sync(b"data")

            call_kwargs = mock_session.post.call_args[1]
            assert call_kwargs["params"]["pin"] == "true"
            assert call_kwargs["params"]["cid-version"] == "1"

    def test_passes_pin_false(self, mock_config, mock_cid_decode):
        """push_to_ipfs_sync passes pin=false when requested."""
        with patch("iwa.core.ipfs.create_retry_session") as mock_create:
            mock_session = MagicMock()
            mock_create.return_value = mock_session

            mock_response = MagicMock()
            mock_response.json.return_value = {"Hash": "QmTestHash"}
            mock_session.post.return_value = mock_response

            push_to_ipfs_sync(b"data", pin=False)

            call_kwargs = mock_session.post.call_args[1]
            assert call_kwargs["params"]["pin"] == "false"

    def test_returns_cid_str_and_hex(self, mock_config, mock_cid_decode):
        """push_to_ipfs_sync returns (cid_str, cid_hex) tuple."""
        with patch("iwa.core.ipfs.create_retry_session") as mock_create:
            mock_session = MagicMock()
            mock_create.return_value = mock_session

            mock_response = MagicMock()
            mock_response.json.return_value = {"Hash": "bafkreitestcid"}
            mock_session.post.return_value = mock_response

            cid_str, cid_hex = push_to_ipfs_sync(b"data")

            assert cid_str == "bafkreitestcid"
            assert isinstance(cid_hex, str)

    def test_calls_raise_for_status(self, mock_config, mock_cid_decode):
        """push_to_ipfs_sync calls raise_for_status on the response."""
        with patch("iwa.core.ipfs.create_retry_session") as mock_create:
            mock_session = MagicMock()
            mock_create.return_value = mock_session

            mock_response = MagicMock()
            mock_response.json.return_value = {"Hash": "QmHash"}
            mock_session.post.return_value = mock_response

            push_to_ipfs_sync(b"data")

            mock_response.raise_for_status.assert_called_once()

    def test_timeout_is_60(self, mock_config, mock_cid_decode):
        """push_to_ipfs_sync passes timeout=60."""
        with patch("iwa.core.ipfs.create_retry_session") as mock_create:
            mock_session = MagicMock()
            mock_create.return_value = mock_session

            mock_response = MagicMock()
            mock_response.json.return_value = {"Hash": "QmHash"}
            mock_session.post.return_value = mock_response

            push_to_ipfs_sync(b"data")

            call_kwargs = mock_session.post.call_args[1]
            assert call_kwargs["timeout"] == 60


# ---------------------------------------------------------------------------
# Tests for push_to_ipfs_async
# ---------------------------------------------------------------------------


class TestPushToIpfsAsync:
    """Tests for push_to_ipfs_async."""

    @pytest.mark.asyncio
    async def test_creates_session_if_none(self, mock_config, mock_cid_decode):
        """push_to_ipfs_async creates a new aiohttp session if none exists."""
        mock_resp = AsyncMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json = AsyncMock(return_value={"Hash": "bafkreitestcid"})

        mock_ctx_manager = AsyncMock()
        mock_ctx_manager.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_ctx_manager.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.closed = False
        mock_session.post = MagicMock(return_value=mock_ctx_manager)

        with patch("iwa.core.ipfs.aiohttp.ClientSession", return_value=mock_session):
            with patch("iwa.core.ipfs.aiohttp.FormData"):
                cid_str, cid_hex = await push_to_ipfs_async(b"test data")

        assert cid_str == "bafkreitestcid"
        assert isinstance(cid_hex, str)
        assert ipfs_module._ASYNC_SESSION is mock_session

    @pytest.mark.asyncio
    async def test_reuses_existing_open_session(self, mock_config, mock_cid_decode):
        """push_to_ipfs_async reuses an existing open session."""
        mock_resp = AsyncMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json = AsyncMock(return_value={"Hash": "bafkreitestcid"})

        mock_ctx_manager = AsyncMock()
        mock_ctx_manager.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_ctx_manager.__aexit__ = AsyncMock(return_value=False)

        existing_session = MagicMock()
        existing_session.closed = False
        existing_session.post = MagicMock(return_value=mock_ctx_manager)

        ipfs_module._ASYNC_SESSION = existing_session

        with patch("iwa.core.ipfs.aiohttp.ClientSession") as mock_client_cls:
            with patch("iwa.core.ipfs.aiohttp.FormData"):
                await push_to_ipfs_async(b"data")

        # Should NOT have created a new session
        mock_client_cls.assert_not_called()
        assert ipfs_module._ASYNC_SESSION is existing_session

    @pytest.mark.asyncio
    async def test_recreates_closed_session(self, mock_config, mock_cid_decode):
        """push_to_ipfs_async creates a new session if the existing one is closed."""
        mock_resp = AsyncMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json = AsyncMock(return_value={"Hash": "bafkreitestcid"})

        mock_ctx_manager = AsyncMock()
        mock_ctx_manager.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_ctx_manager.__aexit__ = AsyncMock(return_value=False)

        closed_session = MagicMock()
        closed_session.closed = True

        new_session = MagicMock()
        new_session.closed = False
        new_session.post = MagicMock(return_value=mock_ctx_manager)

        ipfs_module._ASYNC_SESSION = closed_session

        with patch("iwa.core.ipfs.aiohttp.ClientSession", return_value=new_session):
            with patch("iwa.core.ipfs.aiohttp.FormData"):
                await push_to_ipfs_async(b"data")

        assert ipfs_module._ASYNC_SESSION is new_session

    @pytest.mark.asyncio
    async def test_uses_custom_api_url(self, mock_cid_decode):
        """push_to_ipfs_async uses a custom API URL when provided."""
        mock_resp = AsyncMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json = AsyncMock(return_value={"Hash": "bafkreitestcid"})

        mock_ctx_manager = AsyncMock()
        mock_ctx_manager.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_ctx_manager.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.closed = False
        mock_session.post = MagicMock(return_value=mock_ctx_manager)

        with patch("iwa.core.ipfs.aiohttp.ClientSession", return_value=mock_session):
            with patch("iwa.core.ipfs.aiohttp.FormData"):
                await push_to_ipfs_async(b"data", api_url="http://my-ipfs:5001")

        # Verify the endpoint was constructed with the custom URL
        call_args = mock_session.post.call_args
        assert call_args[0][0] == "http://my-ipfs:5001/api/v0/add"

    @pytest.mark.asyncio
    async def test_passes_pin_params(self, mock_config, mock_cid_decode):
        """push_to_ipfs_async passes correct pin and cid-version params."""
        mock_resp = AsyncMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json = AsyncMock(return_value={"Hash": "bafkreitestcid"})

        mock_ctx_manager = AsyncMock()
        mock_ctx_manager.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_ctx_manager.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.closed = False
        mock_session.post = MagicMock(return_value=mock_ctx_manager)

        with patch("iwa.core.ipfs.aiohttp.ClientSession", return_value=mock_session):
            with patch("iwa.core.ipfs.aiohttp.FormData"):
                await push_to_ipfs_async(b"data", pin=False)

        call_kwargs = mock_session.post.call_args[1]
        assert call_kwargs["params"]["pin"] == "false"
        assert call_kwargs["params"]["cid-version"] == "1"

    @pytest.mark.asyncio
    async def test_calls_raise_for_status(self, mock_config, mock_cid_decode):
        """push_to_ipfs_async calls raise_for_status on the response."""
        mock_resp = AsyncMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json = AsyncMock(return_value={"Hash": "bafkreitestcid"})

        mock_ctx_manager = AsyncMock()
        mock_ctx_manager.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_ctx_manager.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.closed = False
        mock_session.post = MagicMock(return_value=mock_ctx_manager)

        with patch("iwa.core.ipfs.aiohttp.ClientSession", return_value=mock_session):
            with patch("iwa.core.ipfs.aiohttp.FormData"):
                await push_to_ipfs_async(b"data")

        mock_resp.raise_for_status.assert_called_once()


# ---------------------------------------------------------------------------
# Tests for push_metadata_to_ipfs
# ---------------------------------------------------------------------------


class TestPushMetadataToIpfs:
    """Tests for push_metadata_to_ipfs."""

    def test_adds_nonce_to_metadata(self, mock_config, mock_cid_decode):
        """push_metadata_to_ipfs adds a UUID nonce to the data."""
        with patch("iwa.core.ipfs.create_retry_session") as mock_create:
            mock_session = MagicMock()
            mock_create.return_value = mock_session

            mock_response = MagicMock()
            mock_response.json.return_value = {"Hash": "bafkreitest"}
            mock_session.post.return_value = mock_response

            with patch("iwa.core.ipfs.uuid.uuid4", return_value="fake-uuid"):
                push_metadata_to_ipfs({"prompt": "hello", "tool": "test"})

            # Verify the data posted contains the nonce
            call_kwargs = mock_session.post.call_args[1]
            posted_files = call_kwargs["files"]
            posted_data = json.loads(posted_files["file"][1])
            assert posted_data["nonce"] == "fake-uuid"
            assert posted_data["prompt"] == "hello"
            assert posted_data["tool"] == "test"

    def test_includes_extra_attributes(self, mock_config, mock_cid_decode):
        """push_metadata_to_ipfs merges extra_attributes into the data."""
        with patch("iwa.core.ipfs.create_retry_session") as mock_create:
            mock_session = MagicMock()
            mock_create.return_value = mock_session

            mock_response = MagicMock()
            mock_response.json.return_value = {"Hash": "bafkreitest"}
            mock_session.post.return_value = mock_response

            with patch("iwa.core.ipfs.uuid.uuid4", return_value="fake-uuid"):
                push_metadata_to_ipfs(
                    {"prompt": "hello"},
                    extra_attributes={"sender": "0xABC", "chain_id": 100},
                )

            call_kwargs = mock_session.post.call_args[1]
            posted_files = call_kwargs["files"]
            posted_data = json.loads(posted_files["file"][1])
            assert posted_data["sender"] == "0xABC"
            assert posted_data["chain_id"] == 100

    def test_no_extra_attributes(self, mock_config, mock_cid_decode):
        """push_metadata_to_ipfs works without extra_attributes."""
        with patch("iwa.core.ipfs.create_retry_session") as mock_create:
            mock_session = MagicMock()
            mock_create.return_value = mock_session

            mock_response = MagicMock()
            mock_response.json.return_value = {"Hash": "bafkreitest"}
            mock_session.post.return_value = mock_response

            with patch("iwa.core.ipfs.uuid.uuid4", return_value="fake-uuid"):
                truncated_hash, cid_hex = push_metadata_to_ipfs({"key": "value"})

            assert truncated_hash.startswith("0x")
            assert isinstance(cid_hex, str)

    def test_returns_truncated_hash(self, mock_config):
        """push_metadata_to_ipfs returns truncated hash with 0x prefix."""
        # Use a known CID hex to verify truncation logic
        fake_cid_hex = "f01551220aabbccdd"

        with patch("iwa.core.ipfs.create_retry_session") as mock_create:
            mock_session = MagicMock()
            mock_create.return_value = mock_session

            mock_response = MagicMock()
            mock_response.json.return_value = {"Hash": "bafkreitest"}
            mock_session.post.return_value = mock_response

            with patch("iwa.core.ipfs.CID") as mock_cid:
                mock_decoded = MagicMock()
                mock_decoded.version = 1
                mock_decoded.codec = "raw"
                mock_decoded.hashfun.name = "sha2-256"
                mock_decoded.raw_digest = b"digest"
                mock_cid.decode.return_value = mock_decoded
                mock_cid.return_value = MagicMock(
                    __str__=lambda self: fake_cid_hex
                )

                with patch("iwa.core.ipfs.uuid.uuid4", return_value="uuid"):
                    truncated_hash, cid_hex = push_metadata_to_ipfs({"k": "v"})

            # truncated_hash should be "0x" + cid_hex[9:]
            assert truncated_hash == "0x" + fake_cid_hex[9:]
            assert cid_hex == fake_cid_hex

    def test_json_serialization_compact(self, mock_config, mock_cid_decode):
        """push_metadata_to_ipfs serializes JSON with compact separators."""
        with patch("iwa.core.ipfs.create_retry_session") as mock_create:
            mock_session = MagicMock()
            mock_create.return_value = mock_session

            mock_response = MagicMock()
            mock_response.json.return_value = {"Hash": "bafkreitest"}
            mock_session.post.return_value = mock_response

            with patch("iwa.core.ipfs.uuid.uuid4", return_value="nonce-val"):
                push_metadata_to_ipfs({"key": "value"})

            call_kwargs = mock_session.post.call_args[1]
            posted_bytes = call_kwargs["files"]["file"][1]
            # Compact JSON should not have spaces after separators
            assert b" " not in posted_bytes or b": " not in posted_bytes
            # Verify it parses correctly
            parsed = json.loads(posted_bytes)
            assert parsed["key"] == "value"
            assert parsed["nonce"] == "nonce-val"

    def test_passes_api_url_through(self, mock_cid_decode):
        """push_metadata_to_ipfs passes api_url to push_to_ipfs_sync."""
        with patch("iwa.core.ipfs.create_retry_session") as mock_create:
            mock_session = MagicMock()
            mock_create.return_value = mock_session

            mock_response = MagicMock()
            mock_response.json.return_value = {"Hash": "bafkreitest"}
            mock_session.post.return_value = mock_response

            with patch("iwa.core.ipfs.uuid.uuid4", return_value="uuid"):
                push_metadata_to_ipfs({"k": "v"}, api_url="http://custom:5001")

            call_args = mock_session.post.call_args
            assert "http://custom:5001/api/v0/add" == call_args[0][0]


# ---------------------------------------------------------------------------
# Tests for metadata_to_request_data
# ---------------------------------------------------------------------------


class TestMetadataToRequestData:
    """Tests for metadata_to_request_data."""

    def test_returns_bytes(self, mock_config, mock_cid_decode):
        """metadata_to_request_data returns bytes."""
        with patch("iwa.core.ipfs.create_retry_session") as mock_create:
            mock_session = MagicMock()
            mock_create.return_value = mock_session

            mock_response = MagicMock()
            mock_response.json.return_value = {"Hash": "bafkreitest"}
            mock_session.post.return_value = mock_response

            with patch("iwa.core.ipfs.uuid.uuid4", return_value="uuid"):
                result = metadata_to_request_data({"prompt": "test", "tool": "t"})

        assert isinstance(result, bytes)

    def test_converts_truncated_hash_to_bytes(self, mock_config):
        """metadata_to_request_data converts the truncated hex hash to bytes."""
        fake_cid_hex = "f01551220aabbccddee"

        with patch("iwa.core.ipfs.create_retry_session") as mock_create:
            mock_session = MagicMock()
            mock_create.return_value = mock_session

            mock_response = MagicMock()
            mock_response.json.return_value = {"Hash": "bafkreitest"}
            mock_session.post.return_value = mock_response

            with patch("iwa.core.ipfs.CID") as mock_cid:
                mock_decoded = MagicMock()
                mock_decoded.version = 1
                mock_decoded.codec = "raw"
                mock_decoded.hashfun.name = "sha2-256"
                mock_decoded.raw_digest = b"digest"
                mock_cid.decode.return_value = mock_decoded
                mock_cid.return_value = MagicMock(
                    __str__=lambda self: fake_cid_hex
                )

                with patch("iwa.core.ipfs.uuid.uuid4", return_value="uuid"):
                    result = metadata_to_request_data({"prompt": "test"})

        # The truncated_hash is "0x" + fake_cid_hex[9:] = "0xaabbccddee"
        # bytes.fromhex strips the "0x" prefix: bytes.fromhex("aabbccddee")
        expected = bytes.fromhex(fake_cid_hex[9:])
        assert result == expected

    def test_passes_api_url(self, mock_config, mock_cid_decode):
        """metadata_to_request_data forwards api_url to push_metadata_to_ipfs."""
        with patch("iwa.core.ipfs.push_metadata_to_ipfs") as mock_push:
            mock_push.return_value = ("0xaabbccdd", "f01551220aabbccdd")

            metadata_to_request_data(
                {"prompt": "test"}, api_url="http://custom:5001"
            )

            mock_push.assert_called_once_with(
                {"prompt": "test"}, api_url="http://custom:5001"
            )


# ---------------------------------------------------------------------------
# Legacy tests (kept from original file for backward compatibility)
# ---------------------------------------------------------------------------


def test_push_to_ipfs_sync_uses_session(mock_config, mock_cid_decode):
    """Test push_to_ipfs_sync uses persistent session."""
    with patch("iwa.core.ipfs.create_retry_session") as mock_create:
        mock_session = MagicMock()
        mock_create.return_value = mock_session

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"Hash": "QmTestHash"}
        mock_session.post.return_value = mock_response

        cid_str, cid_hex = push_to_ipfs_sync(b"test data")
        mock_create.assert_called_once()
        mock_session.post.assert_called_once()
        assert ipfs_module._SYNC_SESSION is mock_session

        # Second call reuses the session
        push_to_ipfs_sync(b"test data 2")
        mock_create.assert_called_once()
        assert mock_session.post.call_count == 2
