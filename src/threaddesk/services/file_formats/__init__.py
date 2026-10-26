"""Local, bounded format capabilities shared by import, search and preview.

Descriptors never imply that the user's operating system has an application.
Extractors read bytes only; they do not run documents, scripts, macros or URLs.
"""

from __future__ import annotations

from importlib.util import find_spec
from pathlib import Path

from .registry import FORMATS, descriptor


def describe(filename: str) -> dict:
    """Return independent management/index/preview/external-open capabilities."""
    result = descriptor(filename)
    if result["adapter"] == "pdf" and find_spec("pypdf") is None:
        result.update(index=False, index_reason="dependency_missing:pypdf")
    return result


def supported_formats() -> list[dict]:
    return [describe("file" + suffix) for suffix in sorted(FORMATS)]


def extract(path: Path, filename: str) -> dict:
    """Extract searchable text, with an explicit per-file outcome and limit."""
    from .extraction import extract_file

    return extract_file(Path(path), filename)


__all__ = ["describe", "extract", "supported_formats"]
