"""Verify that the LinkedIn MCP tool catalog and endpoint manifest
are consistent with the registered @mcp.tool() definitions.

Checks:
  - Every registered tool has a tool_catalog entry.
  - Every tool_catalog entry has a registered tool (no stale entries).
  - Every endpoint_manifest entry has status == "implemented".
  - Every endpoint_manifest tool reference exists in the tool catalog.

Exit code 0 = all checks pass.  Exit 1 = drift detected.
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "linkedin_mcp"
INIT_FILE = SRC / "__init__.py"
CATALOG_FILE = SRC / "tool_catalog.json"
MANIFEST_FILE = SRC / "endpoint_manifest.json"


def extract_registered_tools() -> set[str]:
    """Extract function names decorated with @mcp.tool() from __init__.py."""
    text = INIT_FILE.read_text(encoding="utf-8")
    tools: set[str] = set()
    for m in re.finditer(r"@mcp\.tool\(\)\s*\n\s*def\s+(\w+)\s*\(", text):
        tools.add(m.group(1))
    return tools


def load_catalog() -> set[str]:
    data = json.loads(CATALOG_FILE.read_text(encoding="utf-8"))
    return {entry["tool"] for entry in data}


def load_manifest() -> list[dict]:
    return json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))


def main() -> int:
    registered = extract_registered_tools()
    catalog = load_catalog()
    manifest = load_manifest()

    print(f"Registered tools:  {len(registered)}")
    print(f"Tool catalog:      {len(catalog)}")
    print(f"Manifest entries:  {len(manifest)}")

    failed = False

    # Registered tools not in catalog (missing documentation)
    missing = sorted(registered - catalog)
    if missing:
        print("\nERROR: registered tools missing from tool_catalog.json:")
        for name in missing:
            print(f"  - {name}")
        failed = True

    # Catalog entries with no registered tool (stale)
    stale = sorted(catalog - registered)
    if stale:
        print("\nERROR: tool_catalog.json entries with no registered tool:")
        for name in stale:
            print(f"  - {name}")
        failed = True

    # Manifest entries referencing unknown tools
    manifest_tools = {entry.get("tool", "") for entry in manifest}
    unknown_manifest = sorted(manifest_tools - registered)
    if unknown_manifest:
        print("\nERROR: endpoint_manifest.json references tools not in code:")
        for name in unknown_manifest:
            print(f"  - {name}")
        failed = True

    # Manifest entries not marked "implemented"
    not_implemented = [
        entry for entry in manifest
        if entry.get("status") != "implemented"
    ]
    if not_implemented:
        print("\nERROR: endpoint_manifest.json entries not marked 'implemented':")
        for entry in not_implemented:
            print(f"  - {entry.get('tool', '?')}: status={entry.get('status', '?')}")
        failed = True

    if failed:
        print("\nFAILED: coverage drift detected.")
        return 1

    print("\nOK: all checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())