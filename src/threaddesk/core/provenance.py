"""Source-neutral provenance records for reviewed imports."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class Provenance:
    source_system: str
    source_id: str
    source_url: str
    source_path: str
    source_type: str
    source_last_edited_at: str
    source_hash: str
    bundle_id: str
    mapping_rule: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Provenance":
        return cls(**{field: str(data[field]) for field in cls.__dataclass_fields__})


@dataclass(frozen=True)
class SourceRecord:
    """Last reviewed source-to-target state used for a later diff."""

    source_system: str
    source_id: str
    target_id: str
    source_hash: str
    target_hash: str
    bundle_id: str
    imported_at: str
    mapping_rule: str

    @property
    def key(self) -> tuple[str, str]:
        return self.source_system, self.source_id

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SourceRecord":
        return cls(**{field: str(data[field]) for field in cls.__dataclass_fields__})
