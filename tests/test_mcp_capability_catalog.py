"""README-linked capability table follows the actual local MCP catalog."""

import re
from pathlib import Path

from threaddesk.services.mcp import TOOLS


def test_documented_capability_table_contains_exact_actual_tool_set():
    text = (Path(__file__).resolve().parents[1] / "docs/MCP.md").read_text()
    table = text.split("| Existing MCP capability |", 1)[1].split("\n## ", 1)[0]
    documented = set(re.findall(r"`([a-z_]+)`", table))
    actual = {tool["name"] for tool in TOOLS}
    assert documented == actual
