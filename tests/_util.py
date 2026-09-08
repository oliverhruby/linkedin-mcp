"""Shared test helpers for the linkedin-mcp offline unit suite.

These helpers are intentionally test-only: they introspect the registered
tool catalog and the FastMCP tool manager to build dummy call arguments so the
tool sweep can invoke every registered tool deterministically (no network).
"""

from __future__ import annotations

import json
from typing import Any

import linkedin_mcp as server

ALL_SCOPES = {
    "openid",
    "profile",
    "rw_organization_admin",
    "w_member_social",
    "r_member_social",
    "r_ads",
    "rw_ads",
    "r_ads_reporting",
}
ALL_ROLES = {"organization_admin", "ad_account_manager"}

MIN_TOOL_COUNT = 25


def all_registered_names() -> list[str]:
    tool_manager = server.mcp._tool_manager
    return sorted(t.name for t in tool_manager.list_tools())


def all_catalog_names() -> list[str]:
    return sorted(item["tool"] for item in server._load_tool_catalog())


def registered_functions() -> dict[str, Any]:
    return {
        name: getattr(server, name)
        for name in all_catalog_names()
        if callable(getattr(server, name, None))
    }


def is_write_tool(name: str) -> bool:
    for item in server._load_tool_catalog():
        if item.get("tool") == name:
            return bool(item.get("writes", False))
    return False


def dummy_value(param_name: str, _param_type: Any = str) -> Any:
    """Return a minimal plausible value for a named tool parameter."""
    defaults = {
        "path": "/rest/campaigns",
        "body_json": "{}",
        "query_json": "{}",
        "author_urn": "urn:li:person:test",
        "commentary": "test post",
        "visibility": "PUBLIC",
        "distribution_feed": "MAIN_FEED",
        "execute": False,
        "state": "dummy-state",
        "client_id": "test-client-id",
        "client_secret": "test-client-secret",
        "redirect_uri": "http://127.0.0.1:9999/callback",
        "scopes_csv": "openid,profile",
        "open_browser": False,
        "auto_listen_callback": False,
        "code": "test-code",
        "refresh_token": "test-refresh-token",
        "role_hints_csv": "organization_admin,ad_account_manager",
        "member_urn": "urn:li:person:test",
        "expires_at": "2030-01-01T00:00:00+00:00",
        "source": "manual",
        "access_token": "test-access-token",
        "post_urn": "urn:li:share:test",
        "member_urn or member-specific endpoint": "urn:li:person:test",
        "api_version": "202406",
        "tool_name": "create_post",
        "msa_or_manual": "",
        "scopes_csv (comma-separated)": "openid,profile",
    }
    return defaults.get(param_name, "test-value")


def required_dummy_args(tool_name: str) -> dict[str, Any]:
    """Build an args dict containing every parameter of a registered tool."""
    tool_manager = server.mcp._tool_manager
    tool = next((t for t in tool_manager.list_tools() if t.name == tool_name), None)
    if tool is None:
        return {}

    args: dict[str, Any] = {}
    try:
        schema = (getattr(tool, "parameters", None)
                  or getattr(tool, "inputSchema", None)
                  or {})
        if isinstance(schema, dict):
            schema = schema  # type: ignore[no-redef]
        else:
            schema = getattr(schema, "model_dump", lambda: {})()  # type: ignore[union-attr]
        properties = schema.get("properties", {})
    except Exception:  # noqa: BLE001
        return {}

    for param_name in properties.keys():
        param_type = properties[param_name].get("type", "string")
        dummy = dummy_value(param_name, param_type)
        if dummy is not None:
            args[param_name] = dummy
    return args


def json_content(data: Any) -> Any:
    """Round-trip through JSON to mimic the tool's serialized output."""
    return json.loads(json.dumps(data))


def capabilities_default() -> None:
    """Set a session with all scopes/roles so capability gates pass."""
    server.auth_set_access_token(
        access_token="test-access-token",
        scopes_csv=",".join(sorted(ALL_SCOPES)),
        member_urn="urn:li:person:test",
        role_hints_csv=",".join(sorted(ALL_ROLES)),
        source="test",
    )
