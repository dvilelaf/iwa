"""Tests for httpx monkey-patch scoped to cowdao-cowpy modules."""

import sys
from unittest.mock import MagicMock, patch

import httpx as real_httpx
import pytest
import requests

# ---------------------------------------------------------------------------
# Group 1: Unit tests for _ShimResponse
# ---------------------------------------------------------------------------


class TestShimResponse:
    """Tests for the _ShimResponse wrapper around requests.Response."""

    def _make_requests_response(self, status=200, json_data=None, text="", headers=None):
        """Helper to build a fake requests.Response."""
        resp = requests.models.Response()
        resp.status_code = status
        resp._content = b""
        if json_data is not None:
            import json

            resp._content = json.dumps(json_data).encode()
            resp.headers["Content-Type"] = "application/json"
        elif text:
            resp._content = text.encode()
        if headers:
            resp.headers.update(headers)
        # Attach a fake request so raise_for_status works
        resp.request = requests.models.PreparedRequest()
        resp.request.method = "GET"
        resp.request.url = "https://example.com"
        return resp

    def test_status_code(self):
        from iwa.plugins.gnosis.cowpy_httpx_shim import _ShimResponse

        resp = _ShimResponse(self._make_requests_response(status=404))
        assert resp.status_code == 404

    def test_text(self):
        from iwa.plugins.gnosis.cowpy_httpx_shim import _ShimResponse

        resp = _ShimResponse(self._make_requests_response(text="hello"))
        assert resp.text == "hello"

    def test_json(self):
        from iwa.plugins.gnosis.cowpy_httpx_shim import _ShimResponse

        resp = _ShimResponse(self._make_requests_response(json_data={"key": "value"}))
        assert resp.json() == {"key": "value"}

    def test_headers(self):
        from iwa.plugins.gnosis.cowpy_httpx_shim import _ShimResponse

        resp = _ShimResponse(
            self._make_requests_response(headers={"X-Custom": "test"})
        )
        assert resp.headers["X-Custom"] == "test"

    @pytest.mark.parametrize("status", [200, 201, 204, 299])
    def test_is_success_true(self, status):
        from iwa.plugins.gnosis.cowpy_httpx_shim import _ShimResponse

        resp = _ShimResponse(self._make_requests_response(status=status))
        assert resp.is_success is True

    @pytest.mark.parametrize("status", [400, 403, 404, 500, 502])
    def test_is_success_false(self, status):
        from iwa.plugins.gnosis.cowpy_httpx_shim import _ShimResponse

        resp = _ShimResponse(self._make_requests_response(status=status))
        assert resp.is_success is False

    def test_raise_for_status_success(self):
        from iwa.plugins.gnosis.cowpy_httpx_shim import _ShimResponse

        resp = _ShimResponse(self._make_requests_response(status=200))
        resp.raise_for_status()  # Should not raise

    def test_raise_for_status_4xx(self):
        from iwa.plugins.gnosis.cowpy_httpx_shim import _ShimResponse

        resp = _ShimResponse(self._make_requests_response(status=403))
        with pytest.raises(real_httpx.HTTPStatusError) as exc_info:
            resp.raise_for_status()
        assert exc_info.value.response is resp

    def test_raise_for_status_5xx(self):
        from iwa.plugins.gnosis.cowpy_httpx_shim import _ShimResponse

        resp = _ShimResponse(self._make_requests_response(status=500))
        with pytest.raises(real_httpx.HTTPStatusError):
            resp.raise_for_status()


# ---------------------------------------------------------------------------
# Group 2: Unit tests for shim AsyncClient
# ---------------------------------------------------------------------------


class TestShimAsyncClient:
    """Tests for the AsyncClient replacement that uses requests.Session."""

    @pytest.mark.asyncio
    async def test_context_manager(self):
        from iwa.plugins.gnosis.cowpy_httpx_shim import AsyncClient

        async with AsyncClient() as client:
            assert client is not None
        # After exit, session should be closed
        assert client._session is not None  # Session object exists but is closed

    @pytest.mark.asyncio
    async def test_get(self):
        from iwa.plugins.gnosis.cowpy_httpx_shim import AsyncClient

        client = AsyncClient()
        with patch.object(client._session, "request") as mock_req:
            fake_resp = requests.models.Response()
            fake_resp.status_code = 200
            fake_resp._content = b'{"ok": true}'
            fake_resp.headers["Content-Type"] = "application/json"
            mock_req.return_value = fake_resp

            resp = await client.get("https://api.cow.fi/test")

            mock_req.assert_called_once_with("GET", "https://api.cow.fi/test")
            assert resp.status_code == 200
            assert resp.json() == {"ok": True}

    @pytest.mark.asyncio
    async def test_post_with_content(self):
        """Test that httpx 'content' kwarg is mapped to requests 'data'."""
        from iwa.plugins.gnosis.cowpy_httpx_shim import AsyncClient

        client = AsyncClient()
        with patch.object(client._session, "request") as mock_req:
            fake_resp = requests.models.Response()
            fake_resp.status_code = 200
            fake_resp._content = b"{}"
            mock_req.return_value = fake_resp

            await client.post("https://api.cow.fi/subgraph", content=b'{"query":"{}"}')

            call_kwargs = mock_req.call_args
            assert call_kwargs[0] == ("POST", "https://api.cow.fi/subgraph")
            assert call_kwargs[1].get("data") == b'{"query":"{}"}'

    @pytest.mark.asyncio
    async def test_post_with_json(self):
        from iwa.plugins.gnosis.cowpy_httpx_shim import AsyncClient

        client = AsyncClient()
        with patch.object(client._session, "request") as mock_req:
            fake_resp = requests.models.Response()
            fake_resp.status_code = 200
            fake_resp._content = b"{}"
            mock_req.return_value = fake_resp

            await client.post("https://api.cow.fi/test", json={"key": "val"})

            call_kwargs = mock_req.call_args
            assert call_kwargs[1].get("json") == {"key": "val"}

    @pytest.mark.asyncio
    async def test_post_with_files(self):
        from iwa.plugins.gnosis.cowpy_httpx_shim import AsyncClient

        client = AsyncClient()
        with patch.object(client._session, "request") as mock_req:
            fake_resp = requests.models.Response()
            fake_resp.status_code = 200
            fake_resp._content = b"{}"
            mock_req.return_value = fake_resp

            files = {"file": ("test.txt", b"data")}
            await client.post("https://api.cow.fi/upload", files=files)

            call_kwargs = mock_req.call_args
            assert call_kwargs[1].get("files") == files

    @pytest.mark.asyncio
    async def test_request_with_headers(self):
        """Test client.request(method, url, headers=...) as used by api_base.py."""
        from iwa.plugins.gnosis.cowpy_httpx_shim import AsyncClient

        client = AsyncClient()
        with patch.object(client._session, "request") as mock_req:
            fake_resp = requests.models.Response()
            fake_resp.status_code = 200
            fake_resp._content = b"{}"
            mock_req.return_value = fake_resp

            # api_base.py calls: client.request(url=url, headers=headers, method=method)
            await client.request(
                method="POST", url="https://api.cow.fi/quote", headers={"Auth": "Bearer x"}
            )

            mock_req.assert_called_once()
            args, kwargs = mock_req.call_args
            assert args == ("POST", "https://api.cow.fi/quote")
            assert kwargs.get("headers") == {"Auth": "Bearer x"}

    @pytest.mark.asyncio
    async def test_constructor_headers(self):
        """Test headers passed to constructor are applied to session."""
        from iwa.plugins.gnosis.cowpy_httpx_shim import AsyncClient

        client = AsyncClient(headers={"X-Api-Key": "abc123"})
        assert client._session.headers["X-Api-Key"] == "abc123"

    @pytest.mark.asyncio
    async def test_aclose(self):
        from iwa.plugins.gnosis.cowpy_httpx_shim import AsyncClient

        client = AsyncClient()
        with patch.object(client._session, "close") as mock_close:
            await client.aclose()
            mock_close.assert_called_once()

    @pytest.mark.asyncio
    async def test_network_error_on_connection_failure(self):
        """Connection errors should propagate (not silently swallowed)."""
        from iwa.plugins.gnosis.cowpy_httpx_shim import AsyncClient

        client = AsyncClient()
        with patch.object(
            client._session, "request", side_effect=requests.ConnectionError("DNS failed")
        ):
            with pytest.raises(real_httpx.NetworkError):
                await client.get("https://api.cow.fi/test")

    @pytest.mark.asyncio
    async def test_context_manager_closes_on_exception(self):
        """Session is closed even if exception occurs inside context manager."""
        from iwa.plugins.gnosis.cowpy_httpx_shim import AsyncClient

        client = AsyncClient()
        with patch.object(client._session, "close") as mock_close:
            with pytest.raises(ValueError):
                async with client:
                    raise ValueError("boom")
            mock_close.assert_called_once()

    @pytest.mark.asyncio
    async def test_multiple_requests_reuse_session(self):
        """Multiple requests on same client reuse the session (connection pooling)."""
        from iwa.plugins.gnosis.cowpy_httpx_shim import AsyncClient

        client = AsyncClient()
        with patch.object(client._session, "request") as mock_req:
            fake_resp = requests.models.Response()
            fake_resp.status_code = 200
            fake_resp._content = b"{}"
            mock_req.return_value = fake_resp

            await client.get("https://api.cow.fi/a")
            await client.get("https://api.cow.fi/b")

            assert mock_req.call_count == 2


# ---------------------------------------------------------------------------
# Group 3: Patch scoping tests
# ---------------------------------------------------------------------------


class TestPatchScoping:
    """Tests that the httpx patch is scoped only to cowdao-cowpy modules."""

    def test_shim_has_real_httpx_exceptions(self):
        """The shim's NetworkError and HTTPStatusError are the real httpx classes."""
        import iwa.plugins.gnosis.cowpy_httpx_shim as shim

        assert shim.NetworkError is real_httpx.NetworkError
        assert shim.HTTPStatusError is real_httpx.HTTPStatusError

    def test_shim_overrides_async_client(self):
        """The shim's AsyncClient is NOT the real httpx.AsyncClient."""
        import iwa.plugins.gnosis.cowpy_httpx_shim as shim

        assert shim.AsyncClient is not real_httpx.AsyncClient

    def test_global_httpx_not_affected_after_get_cowpy_module(self):
        """After get_cowpy_module(), global httpx.AsyncClient is still the original."""
        from iwa.plugins.gnosis.cow_utils import _cowpy_cache, get_cowpy_module

        original_async_client = real_httpx.AsyncClient

        # Clear cache to force a fresh import
        saved_cache = dict(_cowpy_cache)
        _cowpy_cache.clear()

        try:
            # Mock importlib.import_module so we don't need real cowdao-cowpy
            fake_module = MagicMock()
            fake_module.Chain = MagicMock()
            with patch("importlib.import_module", return_value=fake_module):
                get_cowpy_module("Chain")

            # Global httpx.AsyncClient must be unchanged
            assert sys.modules["httpx"].AsyncClient is original_async_client
            assert real_httpx.AsyncClient is original_async_client
        finally:
            _cowpy_cache.clear()
            _cowpy_cache.update(saved_cache)


# ---------------------------------------------------------------------------
# Group 4: Integration with get_cowpy_module
# ---------------------------------------------------------------------------


class TestGetCowpyModuleIntegration:
    """Tests for get_cowpy_module applying the patch correctly."""

    def test_unknown_module_raises(self):
        from iwa.plugins.gnosis.cow_utils import get_cowpy_module

        with pytest.raises(ValueError, match="Unknown cowpy module"):
            get_cowpy_module("NonExistent")

    def test_caching_skips_reimport(self):
        """Subsequent calls return cached value without re-importing."""
        from iwa.plugins.gnosis.cow_utils import _cowpy_cache, get_cowpy_module

        sentinel = object()
        _cowpy_cache["Chain"] = sentinel
        try:
            result = get_cowpy_module("Chain")
            assert result is sentinel
        finally:
            del _cowpy_cache["Chain"]

    def test_sys_modules_restored_on_import_error(self):
        """If import fails, sys.modules['httpx'] is restored to original."""
        from iwa.plugins.gnosis.cow_utils import _cowpy_cache, get_cowpy_module

        original_httpx = sys.modules["httpx"]
        saved_cache = dict(_cowpy_cache)
        _cowpy_cache.clear()

        try:
            with patch("importlib.import_module", side_effect=ImportError("no cowpy")):
                with pytest.raises(ImportError):
                    get_cowpy_module("Chain")

            # sys.modules must be restored
            assert sys.modules["httpx"] is original_httpx
        finally:
            _cowpy_cache.clear()
            _cowpy_cache.update(saved_cache)

    def test_all_known_modules_resolvable(self):
        """Every key in _COWPY_IMPORTS can be loaded (with mocked importlib)."""
        from iwa.plugins.gnosis.cow_utils import (
            _COWPY_IMPORTS,
            _cowpy_cache,
            get_cowpy_module,
        )

        saved_cache = dict(_cowpy_cache)
        _cowpy_cache.clear()

        try:
            fake_module = MagicMock()
            with patch("importlib.import_module", return_value=fake_module):
                for name in _COWPY_IMPORTS:
                    result = get_cowpy_module(name)
                    assert result is not None
        finally:
            _cowpy_cache.clear()
            _cowpy_cache.update(saved_cache)


# ---------------------------------------------------------------------------
# Group 5: Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Edge case tests for robustness."""

    @pytest.mark.asyncio
    async def test_url_coerced_to_string(self):
        """URLs that are not strings (e.g., httpx.URL) are coerced to str."""
        from iwa.plugins.gnosis.cowpy_httpx_shim import AsyncClient

        client = AsyncClient()
        with patch.object(client._session, "request") as mock_req:
            fake_resp = requests.models.Response()
            fake_resp.status_code = 200
            fake_resp._content = b"{}"
            mock_req.return_value = fake_resp

            # Simulate URL-like object
            class FakeURL:
                def __str__(self):
                    return "https://api.cow.fi/test"

            await client.get(FakeURL())
            args = mock_req.call_args[0]
            assert args[1] == "https://api.cow.fi/test"

    @pytest.mark.asyncio
    async def test_raise_for_status_includes_request_object(self):
        """HTTPStatusError should have request and response attributes set."""
        from iwa.plugins.gnosis.cowpy_httpx_shim import _ShimResponse

        resp = requests.models.Response()
        resp.status_code = 500
        resp._content = b"Internal Server Error"
        resp.request = requests.models.PreparedRequest()
        resp.request.method = "POST"
        resp.request.url = "https://api.cow.fi/quote"

        shim_resp = _ShimResponse(resp)
        with pytest.raises(real_httpx.HTTPStatusError) as exc_info:
            shim_resp.raise_for_status()

        exc = exc_info.value
        assert exc.response is shim_resp
        assert hasattr(exc, "request")


# ---------------------------------------------------------------------------
# Group 6: CloudFront WAF canary — detects when the upstream issue is fixed
# ---------------------------------------------------------------------------

# Canary tests that hit the REAL CowSwap API to verify that CloudFront WAF
# still blocks httpx's TLS fingerprint (JA3). When these tests FAIL, it means
# CloudFront or cow-py have stopped blocking httpx and the shim can be removed.
#
# Workaround commit: 61c6fb718a37df11a66815b5e8f414ecc5802c6c
# Upstream issue:    https://github.com/cowdao-grants/cow-py/issues/78
#
# When to revert:
#   1. test_httpx_blocked_by_cloudfront starts FAILING (httpx gets 200)
#   2. Remove cowpy_httpx_shim.py and the sys.modules swap in cow_utils.py
#   3. Close the upstream issue

COW_API_URL = (
    "https://api.cow.fi/mainnet/api/v1/app_data/"
    "0x0000000000000000000000000000000000000000000000000000000000000000"
)


@pytest.mark.network
class TestCloudFrontWAFCanary:
    """Canary: these tests hit the real CowSwap API.

    FAIL = upstream fixed → revert commit 61c6fb71 and remove the shim.
    See: https://github.com/cowdao-grants/cow-py/issues/78
    """

    def test_httpx_blocked_by_cloudfront(self):
        """httpx should get 403 from CloudFront WAF (TLS fingerprint blocked).

        If httpx gets 200, the workaround may no longer be needed:
        - Revert commit 61c6fb718a37df11a66815b5e8f414ecc5802c6c
        - Remove cowpy_httpx_shim.py
        - Remove sys.modules swap in cow_utils.py:get_cowpy_module()
        - Close https://github.com/cowdao-grants/cow-py/issues/78

        Skipped automatically when api.cow.fi is unreachable (outage/DNS hijack).
        """
        import warnings

        try:
            resp = real_httpx.get(COW_API_URL, timeout=10)
        except Exception as exc:
            pytest.skip(f"api.cow.fi unreachable (outage or DNS hijack): {exc}")

        if resp.status_code != 403:
            warnings.warn(
                f"httpx got {resp.status_code} instead of 403 — CloudFront WAF "
                f"may have stopped blocking httpx. The cowpy_httpx_shim workaround "
                f"(commit 61c6fb71) can possibly be removed. "
                f"See: https://github.com/cowdao-grants/cow-py/issues/78",
                stacklevel=1,
            )

    def test_requests_not_blocked(self):
        """requests (urllib3) should get 200 — confirms the API itself works.

        Skipped automatically when api.cow.fi is unreachable (outage/DNS hijack).
        """
        try:
            resp = requests.get(COW_API_URL, timeout=10)
        except Exception as exc:
            pytest.skip(f"api.cow.fi unreachable (outage or DNS hijack): {exc}")

        assert resp.status_code == 200, (
            f"requests got {resp.status_code} — CowSwap API may be down"
        )
