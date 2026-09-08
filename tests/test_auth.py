"""Unit tests for the OAuth/session management tools.

The token-exchange form POST (`_request_form`) is served by the shared fake
transport, so no network is involved. Browser opening and the local callback
listener are stubbed by the autouse fixtures.
"""

from __future__ import annotations

import os

import pytest

import linkedin_mcp as server
from conftest import FakeHttpClient


def test_auth_status_unauthenticated():
    result = server.auth_status()
    assert result["authenticated"] is False


def test_auth_set_access_token_creates_session():
    result = server.auth_set_access_token(access_token="tok", scopes_csv="openid,profile")
    assert result["authenticated"] is True
    assert result["scope_count"] == 2
    session = server._require_session()
    assert session.access_token == "tok"
    assert session.scopes == {"openid", "profile"}


def test_auth_status_redacts_token():
    server.auth_set_access_token(access_token="super-secret", scopes_csv="openid")
    result = server.auth_status()
    assert result["authenticated"] is True
    assert result["session"]["access_token"] == "***redacted***"
    import json
    assert "super-secret" not in json.dumps(result)


def test_auth_clear_resets_session():
    server.auth_set_access_token(access_token="tok")
    result = server.auth_clear()
    assert result["authenticated"] is False
    assert server._SESSION is None


def test_auth_set_role_hints():
    result = server.auth_set_role_hints(role_hints_csv="org_admin,ad_manager")
    assert result["role_hints"] == ["ad_manager", "org_admin"]


def test_auth_start_requires_client_id(monkeypatch):
    monkeypatch.delenv("LINKEDIN_CLIENT_ID", raising=False)
    with pytest.raises(RuntimeError, match="client_id"):
        server.auth_start(client_id="", redirect_uri="http://127.0.0.1:1/cb")


def test_auth_start_requires_redirect_uri(monkeypatch):
    monkeypatch.delenv("LINKEDIN_REDIRECT_URI", raising=False)
    with pytest.raises(RuntimeError, match="redirect_uri"):
        server.auth_start(client_id="c", redirect_uri="")


def test_auth_start_builds_url_and_state():
    result = server.auth_start(
        client_id="client1",
        redirect_uri="http://127.0.0.1:9999/cb",
        scopes_csv="openid,profile",
        auto_listen_callback=False,
    )
    assert result["ok"] is True
    assert "client1" in result["authorization_url"]
    assert "response_type=code" in result["authorization_url"]
    assert result["state"]


def test_auth_poll_unknown_state():
    result = server.auth_poll(state="nope")
    assert result["found"] is False


def test_auth_poll_finds_pending():
    started = server.auth_start(
        client_id="client1",
        redirect_uri="http://127.0.0.1:9999/cb",
        auto_listen_callback=False,
    )
    result = server.auth_poll(state=started["state"])
    assert result["found"] is True
    assert result["has_code"] is False


def test_auth_finish_requires_secret(monkeypatch):
    started = server.auth_start(client_id="c", redirect_uri="http://127.0.0.1:9999/cb", auto_listen_callback=False)
    monkeypatch.delenv("LINKEDIN_CLIENT_SECRET", raising=False)
    with pytest.raises(RuntimeError, match="client_secret"):
        server.auth_finish(state=started["state"], client_secret="", code="code")


def test_auth_finish_exchanges_code(fake_client):
    started = server.auth_start(client_id="c", redirect_uri="http://127.0.0.1:9999/cb", auto_listen_callback=False)
    token_payload = {
        "access_token": "new-token",
        "expires_in": 3600,
        "scope": "openid profile",
        "refresh_token": "refresh-1",
        "token_type": "Bearer",
    }
    fake_client.default_payload = token_payload
    fake_client.default_status = 200

    result = server.auth_finish(state=started["state"], client_secret="secret", code="auth-code")
    assert result["ok"] is True
    assert result["authenticated"] is True
    assert result["has_refresh_token"] is True
    session = server._require_session()
    assert session.access_token == "new-token"
    assert session.source == "oauth_code"


def test_auth_finish_unknown_state_raises():
    with pytest.raises(RuntimeError, match="state"):
        server.auth_finish(state="missing", client_secret="secret", code="code")


def test_auth_refresh_mutates_session(fake_client):
    server.auth_set_access_token(
        access_token="old",
        scopes_csv="openid",
        source="oauth_code",
    )
    # give the session a refresh token
    server._require_session().refresh_token = "rt"
    fake_client.default_payload = {
        "access_token": "refreshed",
        "expires_in": 3600,
        "scope": "openid",
        "refresh_token": "rt2",
        "token_type": "Bearer",
    }
    result = server.auth_refresh(client_id="c", client_secret="secret", refresh_token="")
    assert result["ok"] is True
    session = server._require_session()
    assert session.access_token == "refreshed"
    assert session.source == "oauth_refresh"
