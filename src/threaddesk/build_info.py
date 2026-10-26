"""Read the identity embedded during packaging; never run Git in the app."""

import json
from pathlib import Path
import re

from threaddesk import __version__


def _packaged_identity():
    try:
        data = json.loads(Path(__file__).with_name("_build_info.json").read_text(encoding="utf-8"))
        if (data["version"] != __version__
                or not re.fullmatch(r"[0-9a-f]{40}", data["source_commit"])
                or not isinstance(data["dirty"], bool)
                or not isinstance(data["build_id"], str)):
            return None
        return data
    except (OSError, ValueError, KeyError, TypeError):
        return None


_identity = _packaged_identity()
SOURCE_COMMIT = _identity["source_commit"] if _identity else ""
BUILD_ID = _identity["build_id"] if _identity else "source"
BUILD_LABEL = f"v{__version__} · " + (
    SOURCE_COMMIT[:7] + ("+lokal" if _identity["dirty"] else "")
    if _identity else "Quellstand"
)
BUILD_DESCRIPTION = (
    f"ThreadDesk {__version__} · Commit {SOURCE_COMMIT} · Build {BUILD_ID}"
    if _identity else f"ThreadDesk {__version__} · nicht paketierter Quellstand"
)
