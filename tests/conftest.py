"""Shared pytest fixtures for the linkedin-mcp offline unit suite.

Every test runs against a fully in-memory fake HTTP transport: `server.httpx.Client`
is replaced with a shared `FakeHttpClient`, so no network or real LinkedIn
credentials are used. Module-level mutable state (`_SESSION`, `_ACTIVE_ROLE_HINTS`,
`_PENDING_OAUTH`) and the shared client call log are reset between tests so ordering
never matters.
"""

from __future__ import annotations

from typing import Any

import pytest

import linkedin_mcp as server
from _util import capabilities_default


class FakeResponse:
    """Minimal stand-in for httpx.Response used by the fake transport."""

    def __init__(self, status_code: int = 200, payload: Any = None, text: str = ""):
        self.status_code = status_code
        self._payload = payload if payload is not None else {"ok": True}
        self._text = text
        self._headers = {"content-type": "application/json", "x-test": "1"}

    @property
    def is_success(self) -> bool:
        return 200 <= self.status_code < 300

    @property
    def headers(self) -> dict[str, str]:
        return dict(self._headers)

    def json(self) -> Any:
        return self._payload

    @property
    def text(self) -> str:
        return self._text


class FakeHttpClient:
    """Records every request and returns canned responses.

    `_request`/`_request_form` construct a fresh `httpx.Client` per call, so every
    instantiation shares one global `all_calls` log. The `route()` helper lets a
    test pin specific method+path combinations to richer payloads.
    """

    all_calls: list[dict[str, Any]] = []
    routes: list[tuple[str, str, int, Any]] = []
    default_status: int = 200
    default_payload: Any = {"ok": True}

    def __init__(self, timeout: float = 30.0):
        self.timeout = timeout

    def _respond(self, method: str, url: str) -> FakeResponse:
        for m, prefix, status, payload in self.routes:
            if method.upper() == m and url.startswith(prefix):
                return FakeResponse(status_code=status, payload=payload)
        return FakeResponse(status_code=self.default_status, payload=self.default_payload)

    def request(self, method: str, url: str, **kwargs: Any) -> FakeResponse:
        self.all_calls.append({"method": method.upper(), "url": url, "kwargs": kwargs})
        return self._respond(method.upper(), url)

    def post(self, url: str, **kwargs: Any) -> FakeResponse:
        self.all_calls.append({"method": "POST", "url": url, "kwargs": kwargs})
        return self._respond("POST", url)

    def __enter__(self) -> "FakeHttpClient":
        return self

    def __exit__(self, *exc: Any) -> None:
        return None

    @classmethod
    def reset(cls) -> None:
        cls.all_calls = []
        cls.routes = []
        cls.default_status = 200
        cls.default_payload = {"ok": True}


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch):
    """Reset module state, the fake transport, and disable side effects."""
    server._SESSION = None
    server._ACTIVE_ROLE_HINTS = set()
    with server._PENDING_OAUTH_LOCK:
        server._PENDING_OAUTH.clear()
    FakeHttpClient.reset()
    monkeypatch.setattr(server.httpx, "Client", FakeHttpClient)
    monkeypatch.setattr("linkedin_mcp.webbrowser.open", lambda *a, **k: False)
    monkeypatch.setattr(server, "_start_callback_listener",
                        lambda state_value, redirect_uri: {"started": False, "reason": "stubbed"})
    yield
    server._SESSION = None
    server._ACTIVE_ROLE_HINTS = set()
    with server._PENDING_OAUTH_LOCK:
        server._PENDING_OAUTH.clear()
    monkeypatch.undo()


@pytest.fixture
def fake_client():
    """Expose the shared fake transport for asserting endpoint calls."""
    return FakeHttpClient


@pytest.fixture
def authed():
    """Return a callable that sets an all-scope/all-role test session."""
    return capabilities_default


@pytest.fixture
async def call():
    """Invoke a registered tool through the FastMCP tool manager with raw args."""
    async def _call(name: str, arguments: dict[str, Any]):
        return await server.mcp._tool_manager.call_tool(name, arguments, convert_result=False)
    return _call
