"""MCP read-effect annotations are explicit, not inferred from tool names."""

from threaddesk.services.mcp import McpBridge, TOOLS


def test_tools_advertise_only_reviewed_read_only_calls():
    # Listing must preserve the original schemas, names and function availability.
    listed = McpBridge(None).list_tools()
    assert listed is TOOLS
    by_name = {tool["name"]: tool for tool in listed}
    for name in (
        "list_threads", "get_thread", "current_thread", "get_reentry",
        "list_snapshots", "thread_operation_status", "check_gate",
    ):
        assert by_name[name]["annotations"]["readOnlyHint"] is True
        assert by_name[name]["annotations"]["destructiveHint"] is False

    # A function that writes, changes current context, saves HTML, or dispatches
    # another operation must not accidentally become a proxy read.
    for name in (
        "thread_manage", "knowledge_manage", "add_note", "switch_thread",
        "save_snapshot", "dashboard", "issue_handoff", "generate_prompt",
    ):
        assert by_name[name].get("annotations", {}).get("readOnlyHint") is not True
