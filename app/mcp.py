import asyncio
import json
from typing import Any

import httpx

from app.security import ReadOnlyToolPolicy


class RovoMcpClient:
    """Minimal read-only MCP client supporting JSON and SSE responses."""

    def __init__(self, endpoint: str, authorization: str, policy: ReadOnlyToolPolicy | None = None):
        self.endpoint = endpoint
        self.authorization = authorization
        self.policy = policy or ReadOnlyToolPolicy()
        self._request_id = 0
        self._lock = asyncio.Lock()
        self._session_id: str | None = None

    async def call_tool(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.policy.authorize(tool)
        if not self.authorization:
            raise RuntimeError("Rovo MCP service identity is not connected.")
        headers = {
            "Authorization": self.authorization,
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            await self._initialize(client, headers)
            if self._session_id:
                headers["Mcp-Session-Id"] = self._session_id
            async with self._lock:
                self._request_id += 1
                request_id = self._request_id
            response = await client.post(
                self.endpoint,
                headers=headers,
                json={
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "method": "tools/call",
                    "params": {"name": tool, "arguments": arguments},
                },
            )
        response.raise_for_status()
        result = _mcp_payload(response)
        if result.get("error"):
            raise RuntimeError(str(result["error"]))
        value = result.get("result")
        if not isinstance(value, dict):
            raise TypeError("Rovo MCP returned an invalid tool result.")
        return value

    async def _initialize(self, client: httpx.AsyncClient, headers: dict[str, str]) -> None:
        if self._session_id:
            return
        async with self._lock:
            if self._session_id:
                return
            self._request_id += 1
            response = await client.post(
                self.endpoint,
                headers=headers,
                json={
                    "jsonrpc": "2.0",
                    "id": self._request_id,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-06-18",
                        "capabilities": {},
                        "clientInfo": {
                            "name": "project-intelligence-atlassian",
                            "version": "0.1.0",
                        },
                    },
                },
            )
            response.raise_for_status()
            payload = _mcp_payload(response)
            if payload.get("error") or not isinstance(payload.get("result"), dict):
                raise RuntimeError("Rovo MCP initialization failed.")
            self._session_id = response.headers.get("Mcp-Session-Id")
            initialized_headers = dict(headers)
            if self._session_id:
                initialized_headers["Mcp-Session-Id"] = self._session_id
            initialized = await client.post(
                self.endpoint,
                headers=initialized_headers,
                json={"jsonrpc": "2.0", "method": "notifications/initialized"},
            )
            initialized.raise_for_status()


def _mcp_payload(response: httpx.Response) -> dict[str, Any]:
    if "text/event-stream" not in response.headers.get("content-type", ""):
        value = response.json()
        if not isinstance(value, dict):
            raise RuntimeError("Invalid MCP JSON response.")
        return value
    for line in reversed(response.text.splitlines()):
        if line.startswith("data:"):
            value = json.loads(line[5:].strip())
            if isinstance(value, dict):
                return value
    raise RuntimeError("MCP event stream contained no JSON-RPC result.")
