"""Tests for IPFS module."""

from unittest.mock import ANY, MagicMock, patch

import pytest

import iwa.core.ipfs as ipfs_module
from iwa.core.ipfs import push_to_ipfs_sync


@pytest.fixture
def mock_config():
    """Mock config."""
    with patch("iwa.core.ipfs.Config") as mock_c:
        mock_c.return_value.core.ipfs_api_url = "http://fake-ipfs:5001"
        yield mock_c


@pytest.fixture
def mock_cid_decode():
    """Mock CID.decode."""
    with patch("iwa.core.ipfs.CID") as mock_cid:
        # returns an object that has version, codec, hashfun.name, raw_digest attributes
        mock_decoded = MagicMock()
        mock_decoded.version = 1
        mock_decoded.codec = "raw"
        mock_decoded.hashfun.name = "sha2-256"
        mock_decoded.raw_digest = b"digest"

        mock_cid.decode.return_value = mock_decoded
        yield mock_cid


def test_push_to_ipfs_sync_uses_session(mock_config, mock_cid_decode):
    """Test push_to_ipfs_sync uses persistent session."""
    # Reset global session for test
    ipfs_module._SYNC_SESSION = None

    # Mock requests.Session
    with patch("requests.Session") as mock_session_cls:
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session

        # Mock response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"Hash": "QmTestHash"}
        mock_session.post.return_value = mock_response

        # Call function
        cid_str, cid_hex = push_to_ipfs_sync(b"test data")

        # Verify Session was created
        mock_session_cls.assert_called_once()

        # Verify post called on session
        mock_session.post.assert_called_once()

        # Verify session is stored globally
        assert ipfs_module._SYNC_SESSION == mock_session

        # Verify second call reuses session
        push_to_ipfs_sync(b"test data 2")
        mock_session_cls.assert_called_once()  # Should still be 1 call
        assert mock_session.post.call_count == 2


def test_push_to_ipfs_sync_retry_config(mock_cid_decode):
    """Test session matches retry config."""
    # Reset
    ipfs_module._SYNC_SESSION = None

    with patch("requests.Session") as mock_session_cls:
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_session.post.return_value.status_code = 200
        mock_session.post.return_value.json.return_value = {"Hash": "QmHash"}

        push_to_ipfs_sync(b"data")

        # Verify adapter mounting
        # Since we mock the class return value, we check calls on the return value
        assert mock_session.mount.call_count == 2
        mock_session.mount.assert_any_call("https://", ANY)
        mock_session.mount.assert_any_call("http://", ANY)
