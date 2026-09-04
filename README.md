# linkedin-mcp

A Model Context Protocol (MCP) server that exposes a practical, capability-aware
LinkedIn API toolset to AI agents such as opencode, Claude, Cursor, and other
MCP clients.

The project follows the same design philosophy as `oliverhruby/edupage-mcp`:

- thin wrapper over upstream APIs
- explicit scope/role/product gating per tool
- safe write defaults (`execute=false`)
- coverage manifest for drift tracking

---

## Table of Contents

- [Why this LinkedIn MCP server?](#why-this-linkedin-mcp-server)
- [What it provides](#what-it-provides)
- [Getting started](#getting-started)
  - [Prerequisites](#prerequisites)
  - [LinkedIn app registration](#linkedin-app-registration)
  - [1. Install](#1-install)
  - [2. Configure environment](#2-configure-environment)
  - [3. Register with your MCP client](#3-register-with-your-mcp-client)
- [OAuth popup flow](#oauth-popup-flow)
- [Prompt examples](#prompt-examples)
- [Capability-aware gating](#capability-aware-gating)
- [Tool reference](#tool-reference)
- [Safety notes](#safety-notes)
- [Developer guide](#developer-guide)
  - [Architecture overview](#architecture-overview)
  - [Key files](#key-files)
  - [Coverage drift strategy](#coverage-drift-strategy)
- [Limitations](#limitations)
- [License](#license)

---

## Why this LinkedIn MCP server?

Existing LinkedIn integrations are often either too narrow (only profile/post),
or not approval-aware (tools fail at runtime because scopes/roles are missing).

This project is focused on:

- practical breadth across identity, org, content, and ads modules
- explicit capability checks before calls
- predictable MCP behavior for both read and write tools

---

## What it provides

Current scaffold includes:

- OAuth code flow for interactive browser login (`auth_start` -> `auth_finish`)
- token bootstrap and refresh helpers
- per-tool capability matrix in `src/linkedin_mcp/tool_catalog.json`
- raw authenticated helpers for fast endpoint expansion
- wrapped tools for profile, org ACLs, posts, comments, reactions, media upload, and ads

---

## Getting started

You need an MCP-capable client (opencode, Claude Desktop, Cursor, etc.).

### LinkedIn app registration

1. Open the LinkedIn Developer portal and create a new app.
2. In app auth settings, add an OAuth redirect URL, for example `http://127.0.0.1:8765/callback`.
3. Copy `Client ID` and `Client Secret` into your environment.
4. Under products/scopes, request only what you need now (start with sign-in scopes).
5. Ensure the redirect URL in app settings exactly matches `LINKEDIN_REDIRECT_URI`.

### 1. Install

**Option A - local editable install (recommended for development)**

Requirements: Python 3.10+.

```bash
pip install -e .
linkedin-mcp
```

**Option B - uvx from source folder**

Requirements: `uv` (`uvx`) and a local clone of this repository.

```bash
uvx --from . linkedin-mcp
```

### 2. Configure environment

Copy `.env.example` and set values (or export directly in shell).

Required variables (and usually the only ones you need):

- `LINKEDIN_CLIENT_ID`
- `LINKEDIN_CLIENT_SECRET`
- `LINKEDIN_REDIRECT_URI` (example: `http://127.0.0.1:8765/callback`)

### 3. Register with your MCP client

Example for opencode (`~/.config/opencode/opencode.json`):

```jsonc
{
  "mcp": {
    "linkedin": {
      "type": "local",
      "enabled": true,
      "command": ["uvx", "--from", "git+https://github.com/your-org/linkedin-mcp.git", "linkedin-mcp"],
      "env": {
        "LINKEDIN_CLIENT_ID": "{env:LINKEDIN_CLIENT_ID}",
        "LINKEDIN_CLIENT_SECRET": "{env:LINKEDIN_CLIENT_SECRET}",
        "LINKEDIN_REDIRECT_URI": "{env:LINKEDIN_REDIRECT_URI}"
      }
    }
  }
}
```

Restart your MCP client after config changes.

---

## OAuth popup flow

Standard local interactive flow:

1. `auth_start` (set `open_browser=true` for convenience)
2. User signs in and consents in browser
3. Local callback listener captures code (`auth_poll` shows `has_code=true`)
4. `auth_finish` exchanges code for token
5. `auth_status` and `list_capabilities` verify active permissions

Use localhost callbacks for local MCP mode (example:
`http://127.0.0.1:8765/callback`).

---

## Prompt examples

| User prompt | Likely tool call(s) | Expected response |
|---|---|---|
| "Start LinkedIn login" | `auth_start` | Authorization URL + state + listener details |
| "Did the callback arrive?" | `auth_poll` | Whether code is available |
| "Finish auth" | `auth_finish` | Authenticated session with scopes |
| "What can this account do?" | `list_capabilities` | Per-tool availability with missing scopes/roles |
| "Create a post preview" | `create_post execute=false` | Dry-run request payload |
| "Create the post now" | `create_post execute=true` | API write result |

---

## Capability-aware gating

Each tool declares requirements in `src/linkedin_mcp/tool_catalog.json`:

- `required_scopes`
- `required_roles`
- `product_gate`
- `writes`

Runtime behavior:

- `list_capabilities` reports effective access across all tools
- `can_execute_tool` reports access for one tool
- protected tools fail fast with explicit missing scopes/roles

---

## Tool reference

| Tool | Description | Writes? |
|---|---|---|
| `auth_start` | Build OAuth URL and optional local callback listener | ✅ session |
| `auth_poll` | Poll pending OAuth callback state |  |
| `auth_finish` | Exchange auth code for access token | ✅ session |
| `auth_refresh` | Refresh access token | ✅ session |
| `auth_set_access_token` | Manual token bootstrap | ✅ session |
| `auth_set_role_hints` | Set local role hints used for gating | ✅ session |
| `auth_status` | Show active session metadata |  |
| `auth_clear` | Clear in-memory session and pending OAuth states | ✅ session |
| `list_tool_catalog` | Show tool capability metadata |  |
| `list_endpoint_manifest` | Show endpoint coverage scaffold |  |
| `list_capabilities` | Show effective per-tool availability |  |
| `can_execute_tool` | Check one tool against current capabilities |  |
| `linkedin_get` | Raw authenticated GET helper |  |
| `linkedin_post` | Raw authenticated POST helper | ✅ |
| `whoami` | Resolve current principal profile endpoint |  |
| `get_member_profile` | Fetch member profile |  |
| `list_accessible_organizations` | Fetch organization ACL visibility |  |
| `create_post` | Create post (`execute=false` preview by default) | ✅ |
| `get_post` | Fetch post by URN |  |
| `delete_post` | Delete post (`execute=false` preview by default) | ✅ |
| `list_comments` | Fetch comments for social action path |  |
| `create_comment` | Create comment (`execute=false` preview by default) | ✅ |
| `list_reactions` | Fetch reactions for social action path |  |
| `create_reaction` | Create reaction (`execute=false` preview by default) | ✅ |
| `delete_reaction` | Delete reaction (`execute=false` preview by default) | ✅ |
| `initialize_media_upload` | Initialize media upload workflow (`execute=false` preview by default) | ✅ |
| `finalize_media_upload` | Finalize media upload workflow (`execute=false` preview by default) | ✅ |
| `list_ad_accounts` | List ad accounts (approval gated) |  |
| `list_campaign_groups` | List ad campaign groups |  |
| `create_campaign_group` | Create ad campaign group (`execute=false` preview by default) | ✅ |
| `list_campaigns` | List ad campaigns |  |
| `create_campaign` | Create ad campaign (`execute=false` preview by default) | ✅ |
| `update_campaign` | Update ad campaign (`execute=false` preview by default) | ✅ |
| `get_ad_analytics` | Fetch ad analytics (approval gated) |  |

---

## Safety notes

- Write tools are explicit and default to dry-run where feasible.
- Capability checks prevent many avoidable permission failures.
- API behavior still depends on LinkedIn app approvals and user/org roles.

---

## Developer guide

### Architecture overview

```text
MCP client (opencode / Claude / Cursor)
        | stdio JSON-RPC
        v
linkedin-mcp (FastMCP server)
        | thin wrappers + capability checks
        v
LinkedIn APIs (OAuth + REST)
```

### Key files

| File | Role |
|---|---|
| `src/linkedin_mcp/__init__.py` | Server implementation, tools, session/auth state |
| `src/linkedin_mcp/__main__.py` | `python -m linkedin_mcp` entrypoint |
| `src/linkedin_mcp/tool_catalog.json` | Tool capability declarations |
| `src/linkedin_mcp/endpoint_manifest.json` | Endpoint coverage tracking scaffold |
| `.env.example` | Local environment template |

### Coverage drift strategy

- Keep `endpoint_manifest.json` as the source of expected endpoint coverage.
- Add/adjust wrappers and update status (`implemented`, `planned`) together.
- Add a CI check later to enforce manifest/tool consistency.

---

## Limitations

- This is a scaffold-first implementation, not complete LinkedIn API coverage.
- LinkedIn API availability depends on app-level approvals and account roles.
- Token persistence is currently in-memory; restart requires re-auth or env token.

---

## License

[MIT](LICENSE)
