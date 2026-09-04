from __future__ import annotations

import json
import os
import secrets
import threading
import time
import webbrowser
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from importlib import resources
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import httpx
from mcp.server.fastmcp import FastMCP
try:
    from mcp.server.auth.provider import AccessToken, TokenVerifier
    from mcp.server.auth.settings import AuthSettings
except Exception:
    AccessToken = None
    TokenVerifier = None
    AuthSettings = None

API_BASE_URL = os.getenv("LINKEDIN_API_BASE_URL", "https://api.linkedin.com").rstrip("/")
DEFAULT_API_VERSION = os.getenv("LINKEDIN_API_VERSION")
OAUTH_AUTH_URL = os.getenv("LINKEDIN_OAUTH_AUTH_URL", "https://www.linkedin.com/oauth/v2/authorization")
OAUTH_TOKEN_URL = os.getenv("LINKEDIN_OAUTH_TOKEN_URL", "https://www.linkedin.com/oauth/v2/accessToken")
OAUTH_CALLBACK_TIMEOUT_SECONDS = int(os.getenv("LINKEDIN_OAUTH_CALLBACK_TIMEOUT_SECONDS", "300"))
MCP_API_KEY = os.environ.get("MCP_API_KEY", "")


@dataclass
class SessionState:
    access_token: str
    scopes: set[str]
    member_urn: str | None = None
    expires_at: str | None = None
    refresh_token: str | None = None
    token_type: str | None = None
    source: str = "manual"


@dataclass
class OAuthPendingState:
    state: str
    client_id: str
    redirect_uri: str
    scopes: list[str]
    created_at: str
    expires_at: str
    authorization_code: str | None = None
    error: str | None = None
    error_description: str | None = None
    listener_started: bool = False
    listener_address: str | None = None


_SESSION: SessionState | None = None
_ACTIVE_ROLE_HINTS: set[str] = set()
_TOOL_CATALOG_CACHE: list[dict[str, Any]] | None = None
_PENDING_OAUTH: dict[str, OAuthPendingState] = {}
_PENDING_OAUTH_LOCK = threading.Lock()


def _load_json_resource(name: str) -> Any:
    return json.loads(resources.files("linkedin_mcp").joinpath(name).read_text(encoding="utf-8"))


def _load_tool_catalog() -> list[dict[str, Any]]:
    global _TOOL_CATALOG_CACHE
    if _TOOL_CATALOG_CACHE is None:
        _TOOL_CATALOG_CACHE = _load_json_resource("tool_catalog.json")
    return _TOOL_CATALOG_CACHE


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _expire_pending_oauth() -> None:
    now = datetime.now(UTC)
    stale_states: list[str] = []
    with _PENDING_OAUTH_LOCK:
        for state, pending in _PENDING_OAUTH.items():
            if datetime.fromisoformat(pending.expires_at) < now:
                stale_states.append(state)
        for state in stale_states:
            _PENDING_OAUTH.pop(state, None)


def _require_session() -> SessionState:
    if _SESSION is None:
        raise RuntimeError("Not authenticated. Use auth_set_access_token first.")
    return _SESSION


def _build_headers(api_version: str | None = None, extra: dict[str, str] | None = None) -> dict[str, str]:
    session = _require_session()
    headers = {
        "Authorization": f"Bearer {session.access_token}",
        "Content-Type": "application/json",
    }
    version = api_version or DEFAULT_API_VERSION
    if version:
        headers["LinkedIn-Version"] = version
    if extra:
        headers.update(extra)
    return headers


def _request(
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    body: dict[str, Any] | None = None,
    api_version: str | None = None,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    if not path.startswith("/"):
        path = "/" + path
    url = f"{API_BASE_URL}{path}"
    req_headers = _build_headers(api_version=api_version, extra=headers)

    with httpx.Client(timeout=30.0) as client:
        response = client.request(method=method.upper(), url=url, params=params, json=body, headers=req_headers)

    out: dict[str, Any] = {
        "ok": response.is_success,
        "status_code": response.status_code,
        "headers": dict(response.headers),
        "path": path,
        "method": method.upper(),
    }
    try:
        out["data"] = response.json()
    except json.JSONDecodeError:
        out["text"] = response.text
    return out


def _request_form(url: str, data: dict[str, str]) -> dict[str, Any]:
    with httpx.Client(timeout=30.0) as client:
        response = client.post(url=url, data=data)
    out: dict[str, Any] = {
        "ok": response.is_success,
        "status_code": response.status_code,
        "headers": dict(response.headers),
        "url": url,
    }
    try:
        out["data"] = response.json()
    except json.JSONDecodeError:
        out["text"] = response.text
    return out


def _start_callback_listener(state_value: str, redirect_uri: str) -> dict[str, Any]:
    parsed = urlparse(redirect_uri)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
        return {"started": False, "reason": "callback listener supports only localhost/127.0.0.1 http redirect URIs"}

    host = parsed.hostname
    port = parsed.port
    path = parsed.path or "/"
    if port is None:
        return {"started": False, "reason": "redirect_uri must include explicit port for local callback listener"}

    class OAuthCallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            request = urlparse(self.path)
            if request.path != path:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b"Not found")
                return

            query = parse_qs(request.query)
            callback_state = (query.get("state") or [""])[0]
            code = (query.get("code") or [""])[0]
            error = (query.get("error") or [""])[0]
            error_description = (query.get("error_description") or [""])[0]

            with _PENDING_OAUTH_LOCK:
                pending = _PENDING_OAUTH.get(callback_state)
                if pending:
                    pending.authorization_code = code or None
                    pending.error = error or None
                    pending.error_description = error_description or None

            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            if error:
                self.wfile.write(b"<html><body><h2>LinkedIn authorization failed.</h2><p>You can close this window.</p></body></html>")
            else:
                self.wfile.write(b"<html><body><h2>LinkedIn authorization received.</h2><p>You can return to your MCP client.</p></body></html>")

            threading.Thread(target=self.server.shutdown, daemon=True).start()

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
            return

    def _run_server() -> None:
        try:
            server = HTTPServer((host, port), OAuthCallbackHandler)
            server.timeout = float(OAUTH_CALLBACK_TIMEOUT_SECONDS)
            server.handle_request()
            server.server_close()
        except OSError:
            with _PENDING_OAUTH_LOCK:
                pending = _PENDING_OAUTH.get(state_value)
                if pending:
                    pending.error = "callback_listener_error"
                    pending.error_description = "Could not bind local callback listener; port may already be in use."

    threading.Thread(target=_run_server, daemon=True).start()
    return {"started": True, "listener_address": f"{host}:{port}{path}"}


def _has_scopes(required_scopes: list[str]) -> bool:
    if not required_scopes:
        return True
    session = _require_session()
    return set(required_scopes).issubset(session.scopes)


def _has_roles(required_roles: list[str]) -> bool:
    if not required_roles:
        return True
    return set(required_roles).issubset(_ACTIVE_ROLE_HINTS)


def _validate_capabilities(required_scopes: list[str], required_roles: list[str], product_gate: str | None) -> dict[str, Any]:
    scope_ok = _has_scopes(required_scopes)
    role_ok = _has_roles(required_roles)
    missing_scopes = sorted(set(required_scopes) - (_SESSION.scopes if _SESSION else set()))
    missing_roles = sorted(set(required_roles) - _ACTIVE_ROLE_HINTS)
    return {
        "ok": scope_ok and role_ok,
        "missing_scopes": missing_scopes,
        "missing_roles": missing_roles,
        "product_gate": product_gate,
        "note": "product_gate indicates LinkedIn product approval constraints external to OAuth scopes.",
    }


def _get_tool_requirements(tool_name: str) -> dict[str, Any]:
    for item in _load_tool_catalog():
        if item.get("tool") == tool_name:
            return item
    return {
        "tool": tool_name,
        "writes": False,
        "required_scopes": [],
        "required_roles": [],
        "product_gate": None,
    }


def _enforce_tool_capability(tool_name: str) -> None:
    requirements = _get_tool_requirements(tool_name)
    check = _validate_capabilities(
        required_scopes=requirements.get("required_scopes", []),
        required_roles=requirements.get("required_roles", []),
        product_gate=requirements.get("product_gate"),
    )
    if not check["ok"]:
        raise RuntimeError(
            "Tool '{}' blocked by capability gate. missing_scopes={} missing_roles={} product_gate={}".format(
                tool_name,
                check["missing_scopes"],
                check["missing_roles"],
                check["product_gate"],
            )
        )


def _parse_json_object(raw_json: str, field_name: str) -> dict[str, Any]:
    try:
        decoded = json.loads(raw_json or "{}")
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{field_name} must be valid JSON: {exc}")
    if not isinstance(decoded, dict):
        raise RuntimeError(f"{field_name} must decode to a JSON object")
    return decoded


class _StaticApiKeyTokenVerifier:
    """Simple bearer token verifier backed by MCP_API_KEY."""

    def __init__(self, api_key: str):
        self.api_key = api_key

    async def verify_token(self, token: str):
        if token != self.api_key:
            return None
        return AccessToken(token=token, client_id="mcp-api-key", scopes=["mcp"])  # type: ignore[misc]


mcp = FastMCP(
    "linkedin-mcp",
    token_verifier=_StaticApiKeyTokenVerifier(MCP_API_KEY) if MCP_API_KEY else None,
)


@mcp.tool()
def auth_set_access_token(
    access_token: str,
    scopes_csv: str = "",
    member_urn: str = "",
    expires_at: str = "",
    role_hints_csv: str = "",
    source: str = "manual",
) -> dict[str, Any]:
    """Set active LinkedIn access token and optional capability hints."""
    global _SESSION, _ACTIVE_ROLE_HINTS
    scopes = {s.strip() for s in scopes_csv.split(",") if s.strip()}
    _ACTIVE_ROLE_HINTS = {r.strip() for r in role_hints_csv.split(",") if r.strip()}
    _SESSION = SessionState(
        access_token=access_token,
        scopes=scopes,
        member_urn=member_urn or None,
        expires_at=expires_at or None,
        source=source,
    )
    return {
        "ok": True,
        "authenticated": True,
        "scope_count": len(scopes),
        "role_hint_count": len(_ACTIVE_ROLE_HINTS),
        "set_at": _now_iso(),
    }


@mcp.tool()
def auth_start(
    client_id: str = "",
    redirect_uri: str = "",
    scopes_csv: str = "openid,profile",
    open_browser: bool = False,
    auto_listen_callback: bool = True,
) -> dict[str, Any]:
    """Start OAuth authorization by generating URL and optional localhost callback listener."""
    final_client_id = client_id.strip() or os.getenv("LINKEDIN_CLIENT_ID", "").strip()
    final_redirect_uri = redirect_uri.strip() or os.getenv("LINKEDIN_REDIRECT_URI", "").strip()
    if not final_client_id:
        raise RuntimeError("client_id is required (argument or LINKEDIN_CLIENT_ID env var)")
    if not final_redirect_uri:
        raise RuntimeError("redirect_uri is required (argument or LINKEDIN_REDIRECT_URI env var)")

    _expire_pending_oauth()
    state_value = secrets.token_urlsafe(24)
    scope_list = [s.strip() for s in scopes_csv.split(",") if s.strip()]
    now = datetime.now(UTC)
    expires = now.timestamp() + OAUTH_CALLBACK_TIMEOUT_SECONDS
    pending = OAuthPendingState(
        state=state_value,
        client_id=final_client_id,
        redirect_uri=final_redirect_uri,
        scopes=scope_list,
        created_at=now.isoformat(),
        expires_at=datetime.fromtimestamp(expires, UTC).isoformat(),
    )
    with _PENDING_OAUTH_LOCK:
        _PENDING_OAUTH[state_value] = pending

    params = {
        "response_type": "code",
        "client_id": final_client_id,
        "redirect_uri": final_redirect_uri,
        "state": state_value,
        "scope": " ".join(scope_list),
    }
    auth_url = f"{OAUTH_AUTH_URL}?{urlencode(params)}"

    listener = {"started": False}
    if auto_listen_callback:
        listener = _start_callback_listener(state_value=state_value, redirect_uri=final_redirect_uri)
        with _PENDING_OAUTH_LOCK:
            current = _PENDING_OAUTH.get(state_value)
            if current and listener.get("started"):
                current.listener_started = True
                current.listener_address = listener.get("listener_address")

    browser_opened = False
    if open_browser:
        browser_opened = webbrowser.open(auth_url)

    return {
        "ok": True,
        "state": state_value,
        "authorization_url": auth_url,
        "browser_opened": browser_opened,
        "listener": listener,
        "expires_at": pending.expires_at,
        "next": "Complete consent in browser, then call auth_poll(state) and auth_finish(state, client_secret).",
    }


@mcp.tool()
def auth_poll(state: str) -> dict[str, Any]:
    """Poll pending OAuth state for callback status and auth code availability."""
    _expire_pending_oauth()
    with _PENDING_OAUTH_LOCK:
        pending = _PENDING_OAUTH.get(state)
    if pending is None:
        return {"ok": False, "state": state, "found": False}
    return {
        "ok": True,
        "found": True,
        "state": state,
        "has_code": pending.authorization_code is not None,
        "error": pending.error,
        "error_description": pending.error_description,
        "listener_started": pending.listener_started,
        "listener_address": pending.listener_address,
        "expires_at": pending.expires_at,
    }


@mcp.tool()
def auth_finish(state: str, client_secret: str = "", code: str = "") -> dict[str, Any]:
    """Exchange authorization code for token and activate session."""
    final_client_secret = client_secret.strip() or os.getenv("LINKEDIN_CLIENT_SECRET", "").strip()
    if not final_client_secret:
        raise RuntimeError("client_secret is required (argument or LINKEDIN_CLIENT_SECRET env var)")

    _expire_pending_oauth()
    with _PENDING_OAUTH_LOCK:
        pending = _PENDING_OAUTH.get(state)
    if pending is None:
        raise RuntimeError("OAuth state not found or expired. Start again with auth_start.")
    if pending.error:
        raise RuntimeError(f"OAuth callback returned error: {pending.error} ({pending.error_description or 'no details'})")

    final_code = code.strip() or (pending.authorization_code or "")
    if not final_code:
        raise RuntimeError("Authorization code not available yet. Call auth_poll or provide code directly.")

    token_response = _request_form(
        OAUTH_TOKEN_URL,
        {
            "grant_type": "authorization_code",
            "code": final_code,
            "redirect_uri": pending.redirect_uri,
            "client_id": pending.client_id,
            "client_secret": final_client_secret,
        },
    )
    if not token_response["ok"]:
        return {
            "ok": False,
            "state": state,
            "token_exchange": token_response,
        }

    data = token_response.get("data", {})
    access_token = data.get("access_token")
    if not access_token:
        raise RuntimeError("Token exchange succeeded without access_token in response.")

    expires_in = data.get("expires_in")
    expires_at: str | None = None
    if isinstance(expires_in, int):
        expires_at = datetime.fromtimestamp(time.time() + expires_in, UTC).isoformat()

    granted_scope_raw = str(data.get("scope", "")).strip()
    granted_scopes = {s.strip() for s in granted_scope_raw.replace(",", " ").split() if s.strip()} or set(pending.scopes)

    global _SESSION
    _SESSION = SessionState(
        access_token=access_token,
        scopes=granted_scopes,
        expires_at=expires_at,
        refresh_token=data.get("refresh_token"),
        token_type=data.get("token_type"),
        source="oauth_code",
    )

    with _PENDING_OAUTH_LOCK:
        _PENDING_OAUTH.pop(state, None)

    return {
        "ok": True,
        "authenticated": True,
        "scope_count": len(granted_scopes),
        "expires_at": expires_at,
        "has_refresh_token": bool(data.get("refresh_token")),
    }


@mcp.tool()
def auth_refresh(client_id: str = "", client_secret: str = "", refresh_token: str = "") -> dict[str, Any]:
    """Refresh access token using refresh token from session or argument."""
    final_client_id = client_id.strip() or os.getenv("LINKEDIN_CLIENT_ID", "").strip()
    final_client_secret = client_secret.strip() or os.getenv("LINKEDIN_CLIENT_SECRET", "").strip()
    if not final_client_id:
        raise RuntimeError("client_id is required (argument or LINKEDIN_CLIENT_ID env var)")
    if not final_client_secret:
        raise RuntimeError("client_secret is required (argument or LINKEDIN_CLIENT_SECRET env var)")

    session = _require_session()
    final_refresh = refresh_token.strip() or (session.refresh_token or "")
    if not final_refresh:
        raise RuntimeError("No refresh token available. Re-authenticate with auth_start/auth_finish.")

    token_response = _request_form(
        OAUTH_TOKEN_URL,
        {
            "grant_type": "refresh_token",
            "refresh_token": final_refresh,
            "client_id": final_client_id,
            "client_secret": final_client_secret,
        },
    )
    if not token_response["ok"]:
        return {"ok": False, "token_exchange": token_response}

    data = token_response.get("data", {})
    access_token = data.get("access_token")
    if not access_token:
        raise RuntimeError("Refresh exchange succeeded without access_token in response.")

    expires_in = data.get("expires_in")
    expires_at: str | None = None
    if isinstance(expires_in, int):
        expires_at = datetime.fromtimestamp(time.time() + expires_in, UTC).isoformat()

    granted_scope_raw = str(data.get("scope", "")).strip()
    granted_scopes = {s.strip() for s in granted_scope_raw.replace(",", " ").split() if s.strip()} or session.scopes

    session.access_token = access_token
    session.expires_at = expires_at
    session.scopes = granted_scopes
    session.refresh_token = data.get("refresh_token") or final_refresh
    session.token_type = data.get("token_type") or session.token_type
    session.source = "oauth_refresh"

    return {
        "ok": True,
        "authenticated": True,
        "scope_count": len(session.scopes),
        "expires_at": session.expires_at,
        "has_refresh_token": bool(session.refresh_token),
    }


@mcp.tool()
def auth_set_role_hints(role_hints_csv: str) -> dict[str, Any]:
    """Update role hints used by capability gating."""
    global _ACTIVE_ROLE_HINTS
    _ACTIVE_ROLE_HINTS = {r.strip() for r in role_hints_csv.split(",") if r.strip()}
    return {"ok": True, "role_hints": sorted(_ACTIVE_ROLE_HINTS)}


@mcp.tool()
def auth_status() -> dict[str, Any]:
    """Return current session status."""
    if _SESSION is None:
        return {"authenticated": False}
    safe = asdict(_SESSION)
    safe["access_token"] = "***redacted***"
    safe["scopes"] = sorted(_SESSION.scopes)
    return {
        "authenticated": True,
        "session": safe,
        "role_hints": sorted(_ACTIVE_ROLE_HINTS),
        "pending_oauth_states": sorted(_PENDING_OAUTH.keys()),
    }


@mcp.tool()
def auth_clear() -> dict[str, Any]:
    """Clear active session from memory."""
    global _SESSION, _ACTIVE_ROLE_HINTS
    _SESSION = None
    _ACTIVE_ROLE_HINTS = set()
    with _PENDING_OAUTH_LOCK:
        _PENDING_OAUTH.clear()
    return {"ok": True, "authenticated": False}


@mcp.tool()
def list_tool_catalog() -> dict[str, Any]:
    """List tool capability metadata used by approval-aware clients."""
    return {"tools": _load_tool_catalog()}


@mcp.tool()
def list_endpoint_manifest() -> dict[str, Any]:
    """List endpoint coverage scaffold for drift tracking."""
    return {"endpoints": _load_json_resource("endpoint_manifest.json")}


@mcp.tool()
def list_capabilities() -> dict[str, Any]:
    """Return effective capabilities for current session hints."""
    if _SESSION is None:
        return {"authenticated": False, "capabilities": []}

    tools = _load_tool_catalog()
    capabilities: list[dict[str, Any]] = []
    for item in tools:
        check = _validate_capabilities(
            required_scopes=item.get("required_scopes", []),
            required_roles=item.get("required_roles", []),
            product_gate=item.get("product_gate"),
        )
        capabilities.append(
            {
                "tool": item["tool"],
                "writes": item.get("writes", False),
                "available": check["ok"],
                "missing_scopes": check["missing_scopes"],
                "missing_roles": check["missing_roles"],
                "product_gate": check["product_gate"],
            }
        )
    return {
        "authenticated": True,
        "scopes": sorted(_SESSION.scopes),
        "role_hints": sorted(_ACTIVE_ROLE_HINTS),
        "capabilities": capabilities,
    }


@mcp.tool()
def can_execute_tool(tool_name: str) -> dict[str, Any]:
    """Check whether a tool is available under current scope and role hints."""
    if _SESSION is None:
        return {"authenticated": False, "tool": tool_name, "available": False}
    requirements = _get_tool_requirements(tool_name)
    check = _validate_capabilities(
        required_scopes=requirements.get("required_scopes", []),
        required_roles=requirements.get("required_roles", []),
        product_gate=requirements.get("product_gate"),
    )
    return {
        "authenticated": True,
        "tool": tool_name,
        "writes": requirements.get("writes", False),
        "required_scopes": requirements.get("required_scopes", []),
        "required_roles": requirements.get("required_roles", []),
        "product_gate": requirements.get("product_gate"),
        "available": check["ok"],
        "missing_scopes": check["missing_scopes"],
        "missing_roles": check["missing_roles"],
    }


@mcp.tool()
def linkedin_get(path: str, query_json: str = "{}", api_version: str = "") -> dict[str, Any]:
    """Raw authenticated GET helper."""
    params = _parse_json_object(query_json, "query_json")
    return _request("GET", path, params=params, api_version=api_version or None)


@mcp.tool()
def linkedin_post(path: str, body_json: str = "{}", api_version: str = "") -> dict[str, Any]:
    """Raw authenticated POST helper."""
    body = _parse_json_object(body_json, "body_json")
    return _request("POST", path, body=body, api_version=api_version or None)


@mcp.tool()
def whoami(path: str = "/v2/userinfo") -> dict[str, Any]:
    """Resolve current principal using a configurable profile endpoint."""
    _enforce_tool_capability("whoami")
    return _request("GET", path)


@mcp.tool()
def get_member_profile(member_urn: str = "") -> dict[str, Any]:
    """Get member profile using /v2/userinfo or member-specific endpoint if provided."""
    _enforce_tool_capability("get_member_profile")
    if member_urn:
        return _request("GET", "/v2/people/(id:{})".format(member_urn))
    return _request("GET", "/v2/userinfo")


@mcp.tool()
def list_accessible_organizations(path: str = "/v2/organizationAcls") -> dict[str, Any]:
    """List organizations where current user has admin-like roles."""
    _enforce_tool_capability("list_accessible_organizations")
    return _request("GET", path)


@mcp.tool()
def create_post(
    author_urn: str,
    commentary: str,
    visibility: str = "PUBLIC",
    distribution_feed: str = "MAIN_FEED",
    execute: bool = False,
) -> dict[str, Any]:
    """Create a simple text post. Preview by default; set execute=true to send."""
    _enforce_tool_capability("create_post")
    payload = {
        "author": author_urn,
        "commentary": commentary,
        "visibility": visibility,
        "distribution": {"feedDistribution": distribution_feed},
        "lifecycleState": "PUBLISHED",
        "isReshareDisabledByAuthor": False,
    }
    if not execute:
        return {"ok": True, "dry_run": True, "path": "/rest/posts", "method": "POST", "body": payload}
    return _request("POST", "/rest/posts", body=payload)


@mcp.tool()
def get_post(post_urn: str) -> dict[str, Any]:
    """Get a post by URN."""
    _enforce_tool_capability("get_post")
    return _request("GET", f"/rest/posts/{post_urn}")


@mcp.tool()
def delete_post(post_urn: str, execute: bool = False) -> dict[str, Any]:
    """Delete a post by URN. Preview by default."""
    _enforce_tool_capability("delete_post")
    if not execute:
        return {"ok": True, "dry_run": True, "path": f"/rest/posts/{post_urn}", "method": "DELETE"}
    return _request("DELETE", f"/rest/posts/{post_urn}")


@mcp.tool()
def list_comments(path: str, query_json: str = "{}") -> dict[str, Any]:
    """List comments for a resource path, e.g. /rest/socialActions/{urn}/comments."""
    _enforce_tool_capability("list_comments")
    params = _parse_json_object(query_json, "query_json")
    return _request("GET", path, params=params)


@mcp.tool()
def create_comment(path: str, body_json: str, execute: bool = False) -> dict[str, Any]:
    """Create comment at provided endpoint path. Preview by default."""
    _enforce_tool_capability("create_comment")
    body = _parse_json_object(body_json, "body_json")
    if not execute:
        return {"ok": True, "dry_run": True, "path": path, "method": "POST", "body": body}
    return _request("POST", path, body=body)


@mcp.tool()
def list_reactions(path: str, query_json: str = "{}") -> dict[str, Any]:
    """List reactions for a resource path, e.g. /rest/socialActions/{urn}/reactions."""
    _enforce_tool_capability("list_reactions")
    params = _parse_json_object(query_json, "query_json")
    return _request("GET", path, params=params)


@mcp.tool()
def create_reaction(path: str, body_json: str, execute: bool = False) -> dict[str, Any]:
    """Create reaction at provided endpoint path. Preview by default."""
    _enforce_tool_capability("create_reaction")
    body = _parse_json_object(body_json, "body_json")
    if not execute:
        return {"ok": True, "dry_run": True, "path": path, "method": "POST", "body": body}
    return _request("POST", path, body=body)


@mcp.tool()
def delete_reaction(path: str, execute: bool = False) -> dict[str, Any]:
    """Delete reaction using full endpoint path. Preview by default."""
    _enforce_tool_capability("delete_reaction")
    if not execute:
        return {"ok": True, "dry_run": True, "path": path, "method": "DELETE"}
    return _request("DELETE", path)


@mcp.tool()
def initialize_media_upload(path: str, body_json: str, execute: bool = False) -> dict[str, Any]:
    """Initialize media upload workflow for image/video assets. Preview by default."""
    _enforce_tool_capability("initialize_media_upload")
    body = _parse_json_object(body_json, "body_json")
    if not execute:
        return {"ok": True, "dry_run": True, "path": path, "method": "POST", "body": body}
    return _request("POST", path, body=body)


@mcp.tool()
def finalize_media_upload(path: str, body_json: str, execute: bool = False) -> dict[str, Any]:
    """Finalize media upload workflow for image/video assets. Preview by default."""
    _enforce_tool_capability("finalize_media_upload")
    body = _parse_json_object(body_json, "body_json")
    if not execute:
        return {"ok": True, "dry_run": True, "path": path, "method": "POST", "body": body}
    return _request("POST", path, body=body)


@mcp.tool()
def list_ad_accounts(path: str = "/rest/adAccounts") -> dict[str, Any]:
    """List ad accounts (approval-gated capability)."""
    _enforce_tool_capability("list_ad_accounts")
    return _request("GET", path)


@mcp.tool()
def list_campaign_groups(path: str = "/rest/adCampaignGroups", query_json: str = "{}") -> dict[str, Any]:
    """List ad campaign groups."""
    _enforce_tool_capability("list_campaign_groups")
    params = _parse_json_object(query_json, "query_json")
    return _request("GET", path, params=params)


@mcp.tool()
def create_campaign_group(path: str = "/rest/adCampaignGroups", body_json: str = "{}", execute: bool = False) -> dict[str, Any]:
    """Create campaign group. Preview by default."""
    _enforce_tool_capability("create_campaign_group")
    body = _parse_json_object(body_json, "body_json")
    if not execute:
        return {"ok": True, "dry_run": True, "path": path, "method": "POST", "body": body}
    return _request("POST", path, body=body)


@mcp.tool()
def list_campaigns(path: str = "/rest/adCampaigns", query_json: str = "{}") -> dict[str, Any]:
    """List ad campaigns."""
    _enforce_tool_capability("list_campaigns")
    params = _parse_json_object(query_json, "query_json")
    return _request("GET", path, params=params)


@mcp.tool()
def create_campaign(path: str = "/rest/adCampaigns", body_json: str = "{}", execute: bool = False) -> dict[str, Any]:
    """Create ad campaign. Preview by default."""
    _enforce_tool_capability("create_campaign")
    body = _parse_json_object(body_json, "body_json")
    if not execute:
        return {"ok": True, "dry_run": True, "path": path, "method": "POST", "body": body}
    return _request("POST", path, body=body)


@mcp.tool()
def update_campaign(path: str, body_json: str, execute: bool = False) -> dict[str, Any]:
    """Update ad campaign fields. Preview by default."""
    _enforce_tool_capability("update_campaign")
    body = _parse_json_object(body_json, "body_json")
    if not execute:
        return {"ok": True, "dry_run": True, "path": path, "method": "PATCH", "body": body}
    return _request("PATCH", path, body=body)


@mcp.tool()
def get_ad_analytics(path: str = "/rest/adAnalytics", query_json: str = "{}") -> dict[str, Any]:
    """Fetch ad analytics with custom query payload."""
    _enforce_tool_capability("get_ad_analytics")
    params = _parse_json_object(query_json, "query_json")
    return _request("GET", path, params=params)


def _bootstrap_from_env() -> None:
    token = os.getenv("LINKEDIN_ACCESS_TOKEN", "").strip()
    if not token:
        return
    scopes_csv = os.getenv("LINKEDIN_DEFAULT_SCOPES", "")
    member_urn = os.getenv("LINKEDIN_MEMBER_URN", "")
    role_hints_csv = os.getenv("LINKEDIN_ROLE_HINTS", "")
    auth_set_access_token(
        access_token=token,
        scopes_csv=scopes_csv,
        member_urn=member_urn,
        role_hints_csv=role_hints_csv,
        source="env",
    )


def main() -> None:
    _bootstrap_from_env()
    mcp.run()
