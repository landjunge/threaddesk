"""Local content-search values. No transport, actor or team authority."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from threaddesk.core.errors import InvalidState

RECORD_BYTES = 1024 * 1024
CALL_BYTES = 8 * RECORD_BYTES
CANDIDATES = 500
FIELDS = ("title", "description", "notes")


class SearchError(InvalidState):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class SearchDocument:
    thread_id: str
    revision: int
    title: str
    description: str
    notes: str
    project_id: Optional[str]
    status: str
    source_bytes: int


@dataclass(frozen=True)
class SearchHit:
    thread_id: str
    thread_revision: int
    field: str
    start: int
    end: int
    title: str
    snippet: str
    source_digest: str = ""


@dataclass
class SearchPage:
    hits: list[SearchHit] = field(default_factory=list)
    mode: str = "disabled"
    generation: str = ""
    match_semantics: str = ""
    next_cursor: Optional[str] = None
    complete: bool = False
    truncated: bool = False
    reasons: list[str] = field(default_factory=list)
    scanned: int = 0
    source_bytes: int = 0
    kernel_seconds: float = 0.0
