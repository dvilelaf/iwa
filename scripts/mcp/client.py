"""Shared MCP client over SSE transport, for use by all agent examples."""

import json
import queue
import threading
import time
from typing import Any

import requests

DEFAULT_MCP_BASE = "http://127.0.0.1:18080"


class MCPClient:
    """Minimal stateful MCP client over SSE transport.

    Usage::

        mcp = MCPClient()
        if not mcp.connect():
            raise SystemExit("Cannot connect to MCP server")

        tools = mcp.list_tools()
        result = mcp.call_tool("get_balance", {"account": "master", "chain": "gnosis"})
        mcp.close()

    """

    def __init__(self, base_url: str = DEFAULT_MCP_BASE):
        self.base_url = base_url.rstrip("/")
        self.messages_url: str | None = None
        self._session_q: queue.Queue = queue.Queue()
        self._pending: dict[int, threading.Event] = {}
        self._responses: dict[int, Any] = {}
        self._msg_id = 2
        self._stop = threading.Event()
        self._sse_thread: threading.Thread | None = None

    # ------------------------------------------------------------------
    # Internal SSE listener
    # ------------------------------------------------------------------

    def _listen_sse(self) -> None:
        try:
            resp = requests.get(
                f"{self.base_url}/sse",
                headers={"Accept": "text/event-stream"},
                stream=True,
                timeout=300,
            )
            event_type = None
            for line in resp.iter_lines(decode_unicode=True):
                if self._stop.is_set():
                    break
                if line.startswith("event:"):
                    event_type = line[6:].strip()
                elif line.startswith("data:"):
                    data = line[5:].strip()
                    if event_type == "endpoint":
                        path = (
                            data if data.startswith("http") else self.base_url + data
                        )
                        self._session_q.put(path)
                    elif data and data != "ping":
                        try:
                            msg = json.loads(data)
                            msg_id = msg.get("id")
                            if msg_id in self._pending:
                                self._responses[msg_id] = msg
                                self._pending[msg_id].set()
                        except json.JSONDecodeError:
                            pass
                    event_type = None
        except Exception as exc:
            self._session_q.put(f"ERROR:{exc}")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def connect(self) -> bool:
        """Connect to the MCP server and initialize the session.

        Returns:
            True if connected successfully, False otherwise.

        """
        self._sse_thread = threading.Thread(target=self._listen_sse, daemon=True)
        self._sse_thread.start()

        try:
            result = self._session_q.get(timeout=10)
        except queue.Empty:
            print("ERROR: Timeout waiting for SSE session")
            return False
        if str(result).startswith("ERROR:"):
            print(f"ERROR: {result}")
            return False
        self.messages_url = result

        # MCP initialize handshake
        init_evt = threading.Event()
        self._pending[1] = init_evt
        requests.post(
            self.messages_url,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "iwa-mcp-client", "version": "1.0"},
                },
            },
            timeout=5,
        )
        init_evt.wait(timeout=10)
        requests.post(
            self.messages_url,
            json={"jsonrpc": "2.0", "method": "notifications/initialized"},
            timeout=5,
        )
        time.sleep(0.3)
        return True

    def list_tools(self) -> list[dict]:
        """Return the full list of tools available on the MCP server."""
        msg_id = self._next_id()
        evt = threading.Event()
        self._pending[msg_id] = evt
        requests.post(
            self.messages_url,
            json={"jsonrpc": "2.0", "id": msg_id, "method": "tools/list", "params": {}},
            timeout=5,
        )
        evt.wait(timeout=15)
        resp = self._responses.pop(msg_id, {})
        return resp.get("result", {}).get("tools", [])

    def call_tool(
        self, name: str, arguments: dict | None = None, timeout: float = 60.0
    ) -> Any:
        """Call an MCP tool and return the parsed result.

        Args:
            name: Tool name (e.g. 'get_balance').
            arguments: Tool arguments dict.
            timeout: Max seconds to wait for a response.

        Returns:
            Parsed JSON response, or ``{"error": ...}`` on failure.

        """
        arguments = arguments or {}
        msg_id = self._next_id()
        evt = threading.Event()
        self._pending[msg_id] = evt
        requests.post(
            self.messages_url,
            json={
                "jsonrpc": "2.0",
                "id": msg_id,
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments},
            },
            timeout=5,
        )
        if not evt.wait(timeout=timeout):
            return {"error": f"Timeout after {timeout}s"}
        resp = self._responses.pop(msg_id, {})
        self._pending.pop(msg_id, None)
        if "error" in resp:
            return {"error": resp["error"]}
        content = resp.get("result", {}).get("content", [])
        if content:
            text = content[0].get("text", "")
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return {"text": text}
        return resp.get("result")

    def close(self) -> None:
        """Stop the SSE listener."""
        self._stop.set()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _next_id(self) -> int:
        msg_id = self._msg_id
        self._msg_id += 1
        return msg_id
