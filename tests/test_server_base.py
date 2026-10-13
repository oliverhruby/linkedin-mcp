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


def test_create_post_preview_has_no_reshare_context_by_default(authed):
    authed()
    result = server.create_post(author_urn="urn:li:person:test", commentary="hi")
    assert result["dry_run"] is True
    assert "reshareContext" not in result["body"]


def test_create_post_reshare_sets_parent(authed):
    authed()
    result = server.create_post(
        author_urn="urn:li:person:test",
        commentary="worth a read",
        reshare_of="urn:li:ugcPost:123",
    )
    assert result["dry_run"] is True
    assert result["body"]["reshareContext"] == {"parent": "urn:li:ugcPost:123"}


def test_create_post_reshare_rejects_activity_urn(fake_client, authed):
    authed()
    fake_client.all_calls = []
    with pytest.raises(RuntimeError, match="reshare_of"):
        server.create_post(
            author_urn="urn:li:person:test",
            commentary="x",
            reshare_of="urn:li:activity:7513503467760402432",
            execute=True,
        )
    assert fake_client.all_calls == []


def test_create_post_with_document_sets_media(authed):
    authed()
    result = server.create_post(
        author_urn="urn:li:person:test",
        commentary="carousel",
        media_urn="urn:li:document:abc",
        media_title="Temporal in production",
    )
    assert result["body"]["content"] == {
        "media": {"id": "urn:li:document:abc", "title": "Temporal in production"}
    }


def test_create_post_document_requires_title(authed):
    authed()
    with pytest.raises(RuntimeError, match="media_title"):
        server.create_post(author_urn="urn:li:person:test", commentary="x", media_urn="urn:li:document:abc")


def test_create_post_rejects_media_with_reshare(authed):
    authed()
    with pytest.raises(RuntimeError, match="reshare_of"):
        server.create_post(
            author_urn="urn:li:person:test",
            commentary="x",
            reshare_of="urn:li:share:1",
            media_urn="urn:li:image:abc",
        )


def test_update_post_encodes_urn_and_sends_partial_update(fake_client, authed):
    authed()
    preview = server.update_post(post_urn="urn:li:share:42", commentary="fixed typo")
    assert preview["dry_run"] is True
    assert preview["path"] == "/rest/posts/urn%3Ali%3Ashare%3A42"
    assert fake_client.all_calls == []

    server.update_post(post_urn="urn:li:share:42", commentary="fixed typo", execute=True)
    last = fake_client.all_calls[-1]
    assert last["method"] == "POST"
    assert last["url"].endswith("/rest/posts/urn%3Ali%3Ashare%3A42")
    assert last["kwargs"]["headers"]["X-RestLi-Method"] == "PARTIAL_UPDATE"
    assert last["kwargs"]["json"] == {"patch": {"$set": {"commentary": "fixed typo"}}}


def test_update_comment_sends_actor_and_patch(fake_client, authed):
    authed()
    server.update_comment(
        post_urn="urn:li:share:42", comment_id="7", message="Thanks, Atesh!",
        actor_urn="urn:li:person:test", execute=True,
    )
    last = fake_client.all_calls[-1]
    assert last["url"].endswith("/rest/socialActions/urn%3Ali%3Ashare%3A42/comments/7")
    assert last["kwargs"]["params"] == {"actor": "urn:li:person:test"}
    assert last["kwargs"]["headers"]["X-RestLi-Method"] == "PARTIAL_UPDATE"
    assert last["kwargs"]["json"] == {"patch": {"message": {"$set": {"text": "Thanks, Atesh!"}}}}


def test_delete_comment_previews_then_deletes(fake_client, authed):
    authed()
    preview = server.delete_comment(post_urn="urn:li:share:42", comment_id="7", actor_urn="urn:li:person:test")
    assert preview["dry_run"] is True
    assert fake_client.all_calls == []
    server.delete_comment(post_urn="urn:li:share:42", comment_id="7", actor_urn="urn:li:person:test", execute=True)
    assert fake_client.all_calls[-1]["method"] == "DELETE"


def test_upload_media_file_rejects_non_linkedin_host(tmp_path, authed):
    authed()
    f = tmp_path / "slide.pdf"
    f.write_bytes(b"%PDF-1.4")
    for bad in ("https://evil.example.com/upload", "http://www.linkedin.com/upload", "https://linkedin.com.evil.io/x"):
        with pytest.raises(RuntimeError, match="upload_url"):
            server.upload_media_file(upload_url=bad, file_path=str(f), execute=True)


def test_upload_media_file_rejects_missing_file(authed):
    authed()
    with pytest.raises(RuntimeError, match="file_path"):
        server.upload_media_file(upload_url="https://www.linkedin.com/dms-uploads/x", file_path="/no/such/file.pdf")


def test_upload_media_file_previews_then_puts_bytes(tmp_path, fake_client, authed):
    authed()
    f = tmp_path / "slide.pdf"
    f.write_bytes(b"%PDF-1.4 test")
    url = "https://www.linkedin.com/dms-uploads/abc"
    preview = server.upload_media_file(upload_url=url, file_path=str(f))
    assert preview == {"ok": True, "dry_run": True, "url": url, "method": "PUT", "file_path": str(f), "bytes": 13}
    assert fake_client.all_calls == []

    result = server.upload_media_file(upload_url=url, file_path=str(f), execute=True)
    assert result["ok"] is True
    last = fake_client.all_calls[-1]
    assert last["method"] == "PUT"
    assert last["url"] == url
    assert last["kwargs"]["content"] == b"%PDF-1.4 test"
    assert last["kwargs"]["headers"]["Authorization"].startswith("Bearer")
