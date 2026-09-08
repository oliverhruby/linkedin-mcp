"""Tool sweep: invoke every registered data/network tool through FastMCP.

This is the linkedin-mcp analogue of msgraph-mcp's `test_tools_sweep.py`. It proves
that, given a session with all defined scopes/roles, every non-auth tool can be
called through the real FastMCP argument validation and returns a result without
raising, with no network or credentials involved.

Write tools (flagged `writes=True`) are exercised in their default `execute=False`
dry-run mode, the safe path callers see by default. Read/HTTP tools hit the shared
fake transport and must not error.

`auth_*` tools are deliberately excluded here: they mutate global session state
mid-loop (e.g. `auth_clear` nulls `_SESSION`), which would contaminate every
subsequent tool. They are fully covered by their own dedicated suite in
`test_auth.py`.
"""

from __future__ import annotations

from typing import Any

import linkedin_mcp as server
from _util import all_catalog_names, is_write_tool, required_dummy_args
from conftest import FakeHttpClient

# Auth/session tools: stateful, excluded from the generic sweep (see test_auth.py).
AUTH_TOOLS = {
    "auth_clear",
    "auth_finish",
    "auth_poll",
    "auth_refresh",
    "auth_set_access_token",
    "auth_set_role_hints",
    "auth_start",
    "auth_status",
}


async def _sweep_call(name: str, args: dict) -> Any:
    return await server.mcp._tool_manager.call_tool(name, args, convert_result=False)


async def test_every_data_tool_responds_without_error(authed):
    authed()
    failures: list[str] = []
    for name in all_catalog_names():
        if name in AUTH_TOOLS:
            continue
        args = required_dummy_args(name)
        try:
            result = await _sweep_call(name, args)
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{name}({args}) raised {type(exc).__name__}: {exc}")
            continue

        # Mutating tools must return a dry-run preview (no side effects).
        if is_write_tool(name) and isinstance(result, dict) and result.get("dry_run") is True:
            continue
        if isinstance(result, dict):
            continue
        failures.append(f"{name} returned non-dict result: {result!r}")

    assert failures == [], "\n".join(failures)


async def test_read_tools_touch_the_client(authed):
    authed()
    # These read tools should produce an HTTP request (not a dry-run preview).
    http_read_tools = [
        "linkedin_get", "linkedin_post", "whoami", "get_member_profile",
        "list_accessible_organizations", "get_post", "list_comments",
        "list_reactions", "list_ad_accounts", "list_campaign_groups",
        "list_campaigns", "get_ad_analytics",
    ]
    FakeHttpClient.all_calls = []
    for name in http_read_tools:
        result = await _sweep_call(name, required_dummy_args(name))
        assert isinstance(result, dict)
        assert result.get("ok") is True, f"{name} did not succeed: {result}"
    assert FakeHttpClient.all_calls, "expected read tools to hit the fake transport"


async def test_write_tools_preview_by_default(authed):
    authed()
    # Even without any transport configured, write tools must return a dry-run
    # preview and MUST NOT perform a network call.
    write_no_side_effect = [
        "create_post", "delete_post", "create_comment", "create_reaction",
        "delete_reaction", "initialize_media_upload", "finalize_media_upload",
        "create_campaign_group", "create_campaign", "update_campaign",
    ]
    FakeHttpClient.all_calls = []
    for name in write_no_side_effect:
        result = await _sweep_call(name, required_dummy_args(name))
        assert isinstance(result, dict)
        assert result.get("dry_run") is True, f"{name} expected dry_run, got {result}"
    assert FakeHttpClient.all_calls == [], "dry-run write tools must not hit the network"


def test_registered_set_matches_catalog():
    from _util import all_registered_names
    assert set(all_registered_names()) == set(all_catalog_names())
