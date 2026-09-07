# Contributing

Thanks for contributing to `linkedin-mcp`.

## Local setup

```bash
git clone https://github.com/oliverhruby/linkedin-mcp.git
cd linkedin-mcp
uv sync
```

Alternative setup:

```bash
python -m venv .venv
. .venv/bin/activate  # Windows: .venv\Scripts\activate
python -m pip install -e .
```

Quick checks:

```bash
python -m py_compile src/linkedin_mcp/__init__.py
python -m linkedin_mcp
```

## Architecture and implementation

### High-level design

```
MCP client (opencode / Claude / Cursor ...)
        |  stdio JSON-RPC
        v
linkedin-mcp-full (FastMCP server, mcp<2, console entry point linkedin-mcp-full)
        |  direct LinkedIn API calls
        v
LinkedIn REST API (HTTPS)
```

### Key files

- `src/linkedin_mcp/__init__.py`: entire MCP server (all tools + `main()`).
- `src/linkedin_mcp/__main__.py`: `python -m linkedin_mcp` entry.
- `pyproject.toml`: package metadata + console script.
- `src/linkedin_mcp/tool_catalog.json`: tool capability metadata.
- `src/linkedin_mcp/endpoint_manifest.json`: endpoint coverage scaffold.

### Auth modes

- **OAuth code flow**: `auth_start` → browser → `auth_poll` → `auth_finish`.
- **API key mode**: set `MCP_API_KEY` for HTTP transport with bearer token auth.
- **Manual bootstrap**: `LINKEDIN_ACCESS_TOKEN` env var or `auth_set_access_token`.

### Capability gating

Tools check `list_capabilities` before executing. Missing scopes or roles are
surfaced as structured errors rather than raw HTTP 403s.

### Preview mode (write tools)

All write tools default to `execute=false` (dry-run preview). Set
`execute=true` to perform the actual write.

### Serialization and errors

- Responses are JSON-serializable dicts.
- `_run()` catches exceptions and returns MCP-friendly error payloads.

### Dependency isolation

`mcp<2` is intentionally pinned. `uvx` and editable installs run in isolated
environments to avoid global package conflicts.

## Release process

Version source of truth is `pyproject.toml`.

- Tag format: `vX.Y.Z`
- PyPI publish: [.github/workflows/publish.yml](.github/workflows/publish.yml) (OIDC trusted publishing)
- GitHub release notes: [.github/workflows/release.yml](.github/workflows/release.yml) (auto-generated)
- GHCR image publish: [.github/workflows/publish-container.yml](.github/workflows/publish-container.yml)

Tag/version mismatch checks are enforced in publish and container workflows
via `scripts/check_tag_matches_version.py`.

## CI quality gates

`main` branch requires these checks (defined in the corresponding GitHub Actions workflow files):

- **[python-sanity](.github/workflows/quality-gates.yml)** – compile + install sanity
- **[docker-mcp-smoke](.github/workflows/quality-gates.yml)** – Docker build + MCP handshake (expects >=30 tools)
- **[security / pip-audit](.github/workflows/security.yml)** – dependency vulnerability scan
- **[container-security / trivy-image](.github/workflows/container-security.yml)** – container vulnerability scan
- **[coverage-drift](.github/workflows/coverage-drift.yml)** – tool catalog + endpoint manifest coverage check

## Coverage drift check

CI runs `scripts/check_coverage.py` to verify that every registered
`@mcp.tool()` has a corresponding `tool_catalog.json` entry and that
`endpoint_manifest.json` entries are consistent with registered tools.

Run locally:

```bash
python scripts/check_coverage.py
```

## Conventional Commits

All commit messages should follow the Conventional Commits specification
(<https://conventionalcommits.org/>). The format is:

```
<type>(<scope>): <short description>
```

**Types**

- `feat` – new feature (e.g. a new tool, a new API endpoint)
- `fix` – bug fix or regression
- `docs` – documentation only
- `refactor` – code change that neither adds nor fixes a bug
- `perf` – performance improvement
- `test` – adding or fixing tests
- `chore` – routine maintenance (bump version, config)
- `style` – formatting, missing semi-colons, etc.
- `build` – CI/CD changes, dependency updates
- `revert` – revert a previous commit

**Example messages**

```
feat(auth): add OAuth refresh flow
fix: handle missing org admin scope
docs: update README with auth setup
refactor: extract _linkedin_request helper
```

If a change is breaking, add a footer:

```
BREAKING CHANGE: the `create_post` tool now requires `execute=true` to publish.
```

**Why we use it**

- The GitHub Actions workflow that generates release notes splits commits into
  *Added*, *Changes* and *Upgrade* based on the commit type.
- It also makes auto-generated `CHANGELOG.md` files possible.