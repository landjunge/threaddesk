"""Optional, read-only bridge to the pinned Agent Authority observer preview."""

from __future__ import annotations

import os
import re
import sys
from importlib import metadata

from threaddesk.storage.portable_backup import base_root, selected_profile
from threaddesk.storage.workspace_backup import BackupError

VERSION = "0.3.0a2"
THREAD_ID = re.compile(r"[0-9a-f]{12}\Z")


class PreviewUnavailable(Exception):
    """A fixed translation key; never carries archive or operating-system text."""


def render_preview(thread_id: str) -> str:
    """Read only the selected JSON profile; never construct a store or service."""
    if not THREAD_ID.fullmatch(thread_id):
        raise PreviewUnavailable("authority.invalid_thread")
    if sys.version_info < (3, 12):
        raise PreviewUnavailable("authority.unavailable")
    try:
        version = metadata.version("agent-authority-lab")
    except metadata.PackageNotFoundError as exc:
        raise PreviewUnavailable("authority.unavailable") from exc
    if version != VERSION:
        raise PreviewUnavailable("authority.unavailable")
    try:
        from agent_authority.html_report import render_html
        from agent_authority.report import build_report
        from agent_authority.whiteboard import read_whiteboard
    except ImportError as exc:
        raise PreviewUnavailable("authority.unavailable") from exc
    try:
        root, backend = selected_profile(base_root())
    except (BackupError, OSError) as exc:
        raise PreviewUnavailable("authority.profile_unavailable") from exc
    if (backend or os.environ.get("THREADDESK_STORAGE") or "json") != "json":
        raise PreviewUnavailable("authority.backend_unavailable")
    return render_html(build_report(read_whiteboard(root, thread_id), limit=20))
