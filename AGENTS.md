# AGENTS.md

Guidance for AI agents (and humans) working on this repository. This file is
about **maintaining the code** — it is *not* end-user runtime documentation
(that lives in [README.md](README.md)).

## What this project is

A stdio Model Context Protocol (MCP) server that provides a capability-aware
LinkedIn API toolset to AI agents (opencode, Claude, Cursor, etc).
Published to PyPI as **`linkedin-mcp-full`**; the GitHub repo is the canonical
source.

## Layout

| Path | Purpose |
|---|---|
| `src/linkedin_mcp/__init__.py` | **The whole server**: all tools + `main()`. |
| `src/linkedin_mcp/__main__.py` | `python -m linkedin_mcp` entry. |
| `pyproject.toml` | Packaging; console script `linkedin-mcp-full = "linkedin_mcp:main"`. |
| `src/linkedin_mcp/tool_catalog.json` | Tool capability metadata (scopes, write flags). |
| `src/linkedin_mcp/endpoint_manifest.json` | Endpoint coverage scaffold (status tracking). |
| `README.md` | End-user docs (install, usage, tools). |

## Conventions (keep these consistent)

- **One file.** All tools live in `__init__.py`. Keep it that way unless it
  becomes unmanageable.
- **Every tool** is decorated with `@mcp.tool()` and returns a JSON-serializable
  dict. Docstrings should clearly say if the tool mutates LinkedIn state.
- **Preview mode.** All write tools default to `execute=false` (dry-run).
  `execute=true` performs the actual write. This is enforced by convention:
  tools accepting an `execute` parameter must check `if not execute` and return
  the preview payload.
- **Capability gating.** Tools that require specific scopes or roles should
  check `list_capabilities` before executing. Missing permissions are surfaced
  as structured errors rather than raw HTTP 403s.
- **Auth modes.** Three paths: OAuth code flow (`auth_start`→`auth_finish`),
  API key (`MCP_API_KEY` env for HTTP transport), manual token
  (`LINKEDIN_ACCESS_TOKEN` env). The `_bootstrap_from_env()` function at
  startup picks up `LINKEDIN_ACCESS_TOKEN`, `LINKEDIN_DEFAULT_SCOPES`, and
  `LINKEDIN_MEMBER_URN` to set up a session without interactive OAuth.
- **JSON output.** Return plain JSON-serializable dicts. Don't return raw
  httpx response objects.

## Git commit policy

- Use **Conventional Commits** for every commit message.
- Format: `<type>(<scope>): <description>` (scope optional when not useful).
- Allowed types: `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`,
  `build`, `ci`, `chore`, `revert`.
- Keep the subject short and imperative (`add`, `fix`, `update`), with no
  trailing period.
- Before pushing, check recent history (`git log --oneline -10`) and rewrite
  non-conforming local commit subjects to conventional format.

## Dependency pinning

`pyproject.toml` pins `mcp<2`. Reason: `mcp 2.x` renamed `FastMCP` → `MCPServer`
and changed the API. We target the FastMCP v1 API. Keep `mcp<2`.

## Security scanning

- **Dependabot** (repo-level): security alerts + automated security updates for
  known CVEs are on by default for public repos and are enabled here.
  `.github/dependabot.yml` adds **weekly version-update PRs** for `pip` and
  `github-actions`. Do not remove the `ignore: mcp >=2.0.0` block (matches the
  intentional pin).
- **`pip-audit`** (`.github/workflows/security.yml`): scans the whole installed
  dependency tree — direct + transitive — against OSV on every push/PR to main
  and weekly. A run that finds a CVE **fails the workflow**; fix the pinned
  version in `pyproject.toml` and re-verify with `pip-audit` locally before
  releasing.
- **Quality gates** (`.github/workflows/quality-gates.yml`):
  - `python-sanity` compiles `src/linkedin_mcp/__init__.py` and verifies
    `pip install .` from source.
  - `python-tests` installs the package with `.[dev]` extras and runs the
    offline pytest suite (`tests/`).
  - `docker-mcp-smoke` builds the Docker image and performs an MCP stdio
    handshake (`initialize` + `tools/list`) against the container (expects >=30 tools).
- **Trivy container scan** (`.github/workflows/container-security.yml`): builds
  the Docker image and scans for vulnerabilities on every push/PR to main and
  weekly. The job fails on `HIGH`/`CRITICAL` findings (`ignore-unfixed: true`).
  Use `.trivyignore` only for temporary, documented exceptions.
- **Coverage drift** (`.github/workflows/coverage-drift.yml`): checks that
  every `@mcp.tool()` has a `tool_catalog.json` entry and that
  `endpoint_manifest.json` is consistent with registered tools.

`main` branch protection requires these checks:

- `quality-gates / python-sanity`
- `quality-gates / python-tests`
- `quality-gates / docker-mcp-smoke`
- `security / pip-audit`
- `container-security / trivy-image`
- `coverage-drift / coverage-drift`

Local check:

```bash
pip install pip-audit && pip-audit   # run inside the project venv
```

To run any workflow manually from `gh`:

```bash
gh workflow run security.yml --repo oliverhruby/linkedin-mcp
gh workflow run quality-gates.yml --repo oliverhruby/linkedin-mcp
gh workflow run container-security.yml --repo oliverhruby/linkedin-mcp
gh workflow run coverage-drift.yml --repo oliverhruby/linkedin-mcp
```

## Build / verify

```bash
# from repo root — install once
uv sync            # or: python -m venv .venv && .venv/bin/python -m pip install -e .

# sanity: compile + list tools over a real MCP handshake
python -m py_compile src/linkedin_mcp/__init__.py
python -m linkedin_mcp     # then drive an MCP client; tools/list should show all
```

There is an offline pytest suite under `tests/` that runs fully in-memory with
no network or credentials. It is the primary regression gate for the toolset and
runs in CI (`quality-gates / python-tests`). Run it locally with:

```bash
.venv\Scripts\python.exe -m pytest
```

### Testing conventions (linkedin-mcp)

Pattern follows **msgraph-mcp** (same layout): a fake HTTP transport plus a
"tool sweep" that drives every tool through the real FastMCP tool manager.

- **Fake transport** (`tests/conftest.py`): `server.httpx.Client` is
  monkeypatched to a shared `FakeHttpClient` that records every call and returns
  canned responses. No network, no real tokens.
- **Isolation** (`_isolate` autouse fixture): resets `_SESSION`,
  `_ACTIVE_ROLE_HINTS`, `_PENDING_OAUTH`, and the client call log between tests,
  and stubs `webbrowser.open` + `_start_callback_listener`.
- **Tool sweep** (`tests/test_tools_sweep.py`): with an all-scope/all-role
  session (`capabilities_default()` in `tests/_util.py`), every registered data/
  network tool is invoked via
  `await server.mcp._tool_manager.call_tool(name, args, convert_result=False)`
  and must return a dict without raising. Write tools must come back `dry_run`
  (they are exercised with `execute=False` by default and must NOT touch the
  transport). When adding a tool, add it to the sweep's `http_read_tools` or
  `write_no_side_effect` list as appropriate.
- **`auth_*` tools** are excluded from the sweep (they mutate global session
  state mid-loop); they are covered by their own suite in `tests/test_auth.py`.
- **Catalog wiring** (`tests/test_server_base.py`): asserts each registered tool
  exists in `tool_catalog.json`, write flags are consistent, and the capability
  gate + raw `linkedin_get`/`linkedin_post` behave as expected.
- **Dummy args** come from `required_dummy_args()` in `tests/_util.py`, which
  reads each tool's FastMCP `parameters` schema and fills a plausible value per
  parameter name.
- **Never hit the network in tests.** The suite must stay green with no Internet
  and no LinkedIn/OAuth credentials.

After adding/renaming a tool, update the README "Tool reference" table, the tool
count in the "What it provides" blurb, and run the pytest suite.

## Publishing (PyPI)

Publishing uses **OIDC trusted publishing** via GitHub Actions — no API token.
See comments at the top of `.github/workflows/publish.yml` for the one-time PyPI
registration (project `linkedin-mcp-full`, workflow name `publish.yml`).
GitHub Releases are created automatically:
- `auto-tag.yml` creates both the tag and release when pushing to `main`
  (also creates a release for any orphaned tag that has no release yet).
- `release.yml` is a fallback that creates a release on any tag push.

Container images are published to GHCR on tag push by
`.github/workflows/publish-container.yml`.

To release a new version:

1. Bump `version` in `pyproject.toml`.
2. Commit + push to `main`. The `auto-tag` workflow handles everything
   (tag, release, PyPI publish, GHCR push) automatically.
3. Or manually: `git tag v0.1.0 && git push --tags` triggers the tag-based
   workflows (`release`, `publish`, `publish-container`).

> If the `release` environment has a "required reviewers" gate, approve the run
> in the GitHub Actions UI. Local rebuilds (`python -m build` + `twine upload`)
> still work as a non-OIDC fallback.

Keep the README accurate (install, tools, counts).