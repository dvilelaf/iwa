"""Drop-in httpx shim for cowdao-cowpy that uses requests/urllib3 instead.

CloudFront WAF blocks httpx's TLS fingerprint (JA3) with 403 errors.
This module provides a compatible AsyncClient that uses requests.Session
(urllib3) under the hood, which has a different TLS fingerprint.

This shim is injected into sys.modules["httpx"] ONLY during cowdao-cowpy
module imports, so it does NOT affect other httpx users like python-telegram-bot.
See cow_utils.py:get_cowpy_module() for the injection mechanism.

Tracked upstream: https://github.com/cowdao-grants/cow-py/issues/78
"""

import asyncio

import httpx as _real_httpx
import requests as _requests

# Copy ALL public attributes from real httpx so cowdao-cowpy code referencing
# httpx.NetworkError, httpx.HTTPStatusError, httpx.Response, etc. still works.
# This makes the shim a drop-in replacement for the httpx module.
for _attr in dir(_real_httpx):
    if not _attr.startswith("_"):
        globals()[_attr] = getattr(_real_httpx, _attr)


class _ShimResponse:
    """Response wrapper compatible with httpx.Response interface.

    Only implements the subset of httpx.Response that cowdao-cowpy actually uses:
    - .status_code, .text, .headers, .json(), .is_success, .raise_for_status()
    """

    def __init__(self, requests_response: _requests.Response):
        self._response = requests_response
        self.status_code = requests_response.status_code
        self.text = requests_response.text
        self.headers = requests_response.headers

    @property
    def is_success(self) -> bool:
        """True for 2xx status codes."""
        return 200 <= self.status_code < 300

    def json(self):
        """Parse response body as JSON."""
        return self._response.json()

    def raise_for_status(self) -> None:
        """Raise httpx.HTTPStatusError for 4xx/5xx responses."""
        try:
            self._response.raise_for_status()
        except _requests.HTTPError as e:
            req = getattr(self._response, "request", None)
            method = getattr(req, "method", "GET") if req else "GET"
            url = str(getattr(req, "url", "")) if req else ""
            raise _real_httpx.HTTPStatusError(
                message=f"HTTP {self.status_code}",
                request=_real_httpx.Request(method=method, url=url),
                response=self,
            ) from e


class AsyncClient:
    """Drop-in replacement for httpx.AsyncClient using requests.Session.

    Uses asyncio.to_thread() to run synchronous requests calls without
    blocking the event loop. The requests.Session provides connection
    pooling and a different TLS fingerprint (urllib3) that is not blocked
    by CloudFront WAF.
    """

    def __init__(self, *, headers=None, **kwargs):  # noqa: D107
        self._session = _requests.Session()
        if headers:
            self._session.headers.update(headers)

    async def __aenter__(self):  # noqa: D105
        return self

    async def __aexit__(self, *args):  # noqa: D105
        self._session.close()

    async def aclose(self):
        """Close the underlying session."""
        self._session.close()

    async def request(self, method, url, *, headers=None, **kwargs):
        """Execute an HTTP request.

        Supports the kwargs used by cowdao-cowpy:
        - headers, json, data, files, params, content (mapped to data)
        """
        req_kwargs = _map_kwargs(kwargs)
        if headers:
            req_kwargs["headers"] = headers
        try:
            resp = await asyncio.to_thread(
                self._session.request, method, str(url), **req_kwargs
            )
            return _ShimResponse(resp)
        except _requests.ConnectionError as e:
            raise _real_httpx.NetworkError(str(e)) from e

    async def get(self, url, **kwargs):
        """HTTP GET."""
        return await self.request("GET", url, **kwargs)

    async def post(self, url, **kwargs):
        """HTTP POST."""
        return await self.request("POST", url, **kwargs)


def _map_kwargs(kwargs: dict) -> dict:
    """Map httpx-style kwargs to requests-style kwargs."""
    mapped = {}
    for k, v in kwargs.items():
        if k == "content":
            # httpx 'content' (raw bytes) -> requests 'data'
            mapped["data"] = v
        elif k == "follow_redirects":
            # httpx 'follow_redirects' -> requests 'allow_redirects'
            mapped["allow_redirects"] = v
        else:
            mapped[k] = v
    return mapped
