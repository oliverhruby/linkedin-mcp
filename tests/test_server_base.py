"""Structural and wiring tests for the linkedin-mcp server.

These validate the tool registry, capability gating, header/request building and
the consistency of `tool_catalog.json` with the actual `@mcp.tool()` definitions —
no network required.
"""

from __future__ import annotations

import json

import pytest

import linkedin_mcp as server
from _util import (
    MIN_TOOL_COUNT,
    all_catalog_names,
    all_registered_names,
    is_write_tool,
)


def test_registered_tools_meet_minimum():
    names = all_registered_names()
    assert len(names) >= MIN_TOOL_COUNT


def test_catalog_names_match_registered_tools():
    catalog = all_catalog_names()
    registered = all_registered_names()
    missing_from_registry = [n for n in catalog if n not in registered]
    assert missing_from_registry == [], f"Catalog tools missing from registry: {missing_from_registry}"


def test_catalog_names_have_no_stale_entries():
    catalog = set(all_catalog_names())
    registered = set(all_registered_names())
    stale = sorted(registered - catalog)
    assert stale == [], f"Registered tools missing from catalog: {stale}"


def test_every_catalog_entry_has_expected_keys():
    for item in server._load_tool_catalog():
        assert "tool" in item, f"catalog entry missing 'tool': {item}"
        assert isinstance(item.get("writes", False), bool)
        assert isinstance(item.get("required_scopes", []), list)
        assert isinstance(item.get("required_roles", []), list)


def test_endpoint_manifest_entries_are_implemented():
    manifest = server._load_json_resource("endpoint_manifest.json")
    assert isinstance(manifest, list)
    implemented = {e.get("tool") for e in manifest if e.get("status") == "implemented"}
    catalog = set(all_catalog_names())
    unknown = [e.get("tool") for e in manifest if e.get("tool") not in catalog]
    assert unknown == [], f"Manifest references unknown tools: {unknown}"
    # Every implementing tool must exist in the catalog.
    assert implemented.issubset(catalog)


def test_write_tools_marked_in_catalog():
    # Representative write tools must be flagged as such (drives preview gating).
    for name in ("create_post", "delete_post", "create_comment", "create_reaction",
                 "auth_set_access_token", "linkedin_post"):
        assert is_write_tool(name), f"Expected {name} to be marked writes=True"


def test_require_session_raises_when_unauthenticated():
    with pytest.raises(RuntimeError):
        server._require_session()


def test_build_headers_with_session():
    server.auth_set_access_token(access_token="tok", scopes_csv="openid")
    headers = server._build_headers()
    assert headers["Authorization"] == "Bearer tok"
    assert headers["Content-Type"] == "application/json"


def test_build_headers_respects_api_version():
    server.auth_set_access_token(access_token="tok")
    headers = server._build_headers(api_version="202406")
    assert headers["LinkedIn-Version"] == "202406"


def test_capability_gate_blocks_missing_scope():
    server.auth_set_access_token(access_token="tok", scopes_csv="openid")
    with pytest.raises(RuntimeError, match="create_post"):
        server._enforce_tool_capability("create_post")  # requires w_member_social


def test_capability_gate_passes_with_matching_scope():
    server.auth_set_access_token(access_token="tok", scopes_csv="openid,w_member_social")
    server._enforce_tool_capability("create_post")
    # no raise


def test_can_execute_tool_reports_availability():
    server.auth_set_access_token(access_token="tok", scopes_csv="openid,w_member_social")
    result = server.can_execute_tool("create_post")
    assert result["available"] is True
    assert result["authenticated"] is True


def test_can_execute_tool_unavailable_without_scope():
    server.auth_set_access_token(access_token="tok", scopes_csv="openid")
    result = server.can_execute_tool("create_post")
    assert result["available"] is False
    assert "w_member_social" in result["missing_scopes"]


def test_linkedin_get_prepends_slash_and_sends_request(fake_client, authed):
    authed()
    result = server.linkedin_get(path="rest/posts", query_json='{"count": 5}')
    assert result["ok"] is True
    assert result["method"] == "GET"
    assert result["path"] == "/rest/posts"
    last = fake_client.all_calls[-1]
    assert last["method"] == "GET"
    assert last["kwargs"]["params"] == {"count": 5}
    assert last["kwargs"]["headers"]["Authorization"].startswith("Bearer")


def test_linkedin_post_parses_body(fake_client, authed):
    authed()
    result = server.linkedin_post(path="/rest/posts", body_json='{"commentary": "hi"}')
    assert result["method"] == "POST"
    last = fake_client.all_calls[-1]
    assert last["kwargs"]["json"] == {"commentary": "hi"}


def test_invalid_json_raises():
    server.auth_set_access_token(access_token="tok")
    with pytest.raises(RuntimeError, match="body_json"):
        server.linkedin_post(path="/x", body_json="not json")
