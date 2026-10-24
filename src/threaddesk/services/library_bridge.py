"""Boundary toward KiraBridge.

The permitted KiraBridge catalog exposes file, session, and terminal
operations. It does not expose a library speech operation. This module does
not call the bridge and does not grant a new permission. A spoken transcript
becomes an ordinary local library command.
"""
from __future__ import annotations

LOCAL_COMMANDS = ("find", "open", "organize")


def contract() -> dict:
    return {
        "bridge_speech_operations": [],
        "local_commands": list(LOCAL_COMMANDS),
        "executes_programs": False,
        "reads_originals": False,
    }
