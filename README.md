# LinkedIn MCP Server

[![GitHub release](https://img.shields.io/github/v/release/oliverhruby/linkedin-mcp.svg?label=release)](https://github.com/oliverhruby/linkedin-mcp/releases)
[![Quality gates](https://img.shields.io/github/actions/workflow/status/oliverhruby/linkedin-mcp/quality-gates.yml.svg?label=quality%20gates)](https://github.com/oliverhruby/linkedin-mcp/actions/workflows/quality-gates.yml)
[![Security](https://img.shields.io/github/actions/workflow/status/oliverhruby/linkedin-mcp/security.yml.svg?label=security)](https://github.com/oliverhruby/linkedin-mcp/actions/workflows/security.yml)
[![Container security](https://img.shields.io/github/actions/workflow/status/oliverhruby/linkedin-mcp/container-security.yml.svg?label=container%20security)](https://github.com/oliverhruby/linkedin-mcp/actions/workflows/container-security.yml)
[![Coverage drift](https://img.shields.io/github/actions/workflow/status/oliverhruby/linkedin-mcp/README.md?label=coverage%20drift)](https://github.com/oliverhruby/linkedin-mcp/actions/workflows/README.md)

## Project

| Repository | Description | Project |
|---|---|---|
| **youtube-mcp** | Full-coverage MCP server for the YouTube Data API, supporting search videos, channel stats, and analytics queries. Also manages playlist management, comment extraction, and reporting data queries for AI agents. | [oliverhruby/youtube-mcp](https://github.com/oliverhruby/youtube-mcp) |
| **edupage-mcp** | Full-feature EduPage MCP server for timetables, grades, homework, meal ordering, messages, multi-school discovery, role-aware student switching, and 2FA. | [oliverhruby/edupage-mcp](https://github.com/oliverhruby/edupage-mcp) |
| **linkedin-mcp** | A Model Context Protocol server that exposes a practical, capability-aware LinkedIn API toolset to AI agents such as opencode, Claude, Cursor, and other MCP clients. | [oliverhruby/linkedin-mcp](https://github.com/oliverhruby/linkedin-mcp) |

## Table of Contents

- [Why another LinkedIn MCP server](#why-another-linkedin-mcp-server)
- [What it provides](#what-it-provides)
- [Getting started](#getting-started)
- [Prompt examples](#prompt-examples)
- [Tool reference](#tool-reference)
- [Data & safety notes](#data--safety-notes)
- [Limitations](#limitations)
- [License](#license)

---

## Why another LinkedIn MCP server?

| Feature domain | stickerdaniel/linkedin-mcp-server | southleft/linkedin-mcp | **linkedin-mcp** |
|---|---|---|---|
| **OAuth code flow** | ✅ Browser-based auth code exchange | ✅ OAuth 2.0 code flow | ✅ Full `auth_start` → `auth_poll` → `auth_finish` with local callback |
| **Write preview mode** | ❌ (no dry-run default) | ❌ (no dry-run default) | ✅ All write tools default to `execute=false` preview; `execute=true` performs actual write |
| **Ads/campaign management** | ❌ Not supported | ❌ Not supported | ✅ `list_ad_accounts`, `list_campaign_groups`, `list_campaigns`, `create_campaign_group`, `create_campaign`, `update_campaign` |
| **Media upload workflow** | ❌ Not supported | ❌ Not supported | ✅ `initialize_media_upload` → `finalize_media_upload` workflow |
| **Comment/reaction tools** | ✅ Basic comment and reaction support | ✅ Basic comment and reaction support | ✅ `list_comments`, `create_comment`, `list_reactions`, `create_reaction` |
| **Direct messaging** | ✅ (with session browser) / ⚠️ ToS violation via browser scraping | ✅ (with session browser) / ⚠️ ToS violation via browser scraping | ❌ Not included (requires Sales Navigator/partner approval / `w_member_social` scope) |

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

You need an MCP-capable client (opencode, Claude Desktop, Cursor, etc).

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
      "command": ["uvx", "--from", "git+https://github.com/oliverhruby/linkedin-mcp.git", "linkedin-mcp"],
      "env": {
        "LINKEDIN_CLIENT_ID": "{env:LINKEDIN_CLIENT_ID}",
        "LINKEDIN_CLIENT_SECRET": "{env:LINKEDIN_CLIENT_SECRET}",
        "LINKEDIN_REDIRECT_URI": "{env:LINKEDIN_REDIRECT_URI}"
      }
    }
  }
}

Restart your MCP client after config changes.
```

---

## Prompt examples

| User prompt | Likely tool call(s) | Expected response |
|---|---|---|
| "Start LinkedIn login" | `auth_start` | Authorization URL + state + listener details |
| "Search for company updates" | `list_accessible_organizations` | Organization ACL visibility |
| "Create a post preview" | `create_post execute=false` | Dry-run request payload |
| "Create the post now" | `create_post execute=true` | API write result |
| "List my campaigns" | `list_campaigns` | Ad campaigns list |
| "Get ad analytics" | `get_ad_analytics` | Ad analytics data |
| "List my reactions" | `list_reactions` | Reactions for a social action |
| "Check account capabilities" | `list_capabilities` | Per-tool availability with missing scopes/roles |

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

## Data & safety notes

- Write tools are explicit and default to dry-run where feasible.
- Capability checks prevent many avoidable permission failures.
- API behavior still depends on LinkedIn app approvals and user/org roles.
- Write tools are explicit and default to dry-run where feasible.
- Capability checks prevent many avoidable permission failures.
- API behavior still depends on LinkedIn app approvals and user/org roles.

---

## Limitations

- This is a scaffold-first implementation, not complete LinkedIn API coverage.
- LinkedIn API availability depends on app-level approvals and account roles.
- Token persistence is currently in-memory; restart requires re-auth or env token.

---

## License

[MIT](LICENSE) © Oliver Hrubý