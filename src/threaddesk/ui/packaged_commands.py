"""Shared structured command entry for both standalone desktop packages."""
from __future__ import annotations


def dispatch(arguments):
    """Return a CLI exit code, or None when normal desktop startup is requested."""
    if not arguments:
        return None
    flags = {"--command-file": "--request-file", "--command": "--request"}
    if len(arguments) == 2 and arguments[0] in flags:
        from threaddesk.ui.cli import main
        return main(["command", flags[arguments[0]], arguments[1]])
    if arguments == ["--command-catalog"]:
        from threaddesk.ui.cli import main
        return main(["command", "--catalog"])
    return None
