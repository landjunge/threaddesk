"""Read-only migration preview boundary for the local UI."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from threaddesk.services.migration.bundle import validate_bundle
from threaddesk.services.migration.diff import DryRunPlanner
from threaddesk.storage.protocols import Store


BLOCKING_DIFFS = frozenset({"conflict", "open", "possible_duplicate"})


class MigrationPreviewService:
    """Validate and plan a bundle without changing ThreadDesk data."""

    def __init__(self, store: Store, *, planner: DryRunPlanner | None = None) -> None:
        self.store = store
        self.planner = planner or DryRunPlanner()

    def inspect(self, bundle_path: Path) -> dict[str, Any]:
        bundle = validate_bundle(bundle_path)
        plan = self.planner.plan(
            bundle,
            existing_nodes=self.store.list_nodes(),
            source_records=self.store.list_source_records("notion"),
        )
        blockers = sorted(
            {item.diff.value for item in plan.proposals if item.diff.value in BLOCKING_DIFFS}
            | ({"open_relation"} if any(
                relation.mapping_state == "open" for relation in plan.relations
            ) else set())
        )
        return {
            "bundle_sha256": bundle.bundle_sha256,
            "counts": dict(plan.counts),
            "blockers": blockers,
            "can_confirm_import": not blockers,
            "proposals": [
                {"source_id": item.source_id, "title": item.draft.title,
                 "diff": item.diff.value, "reason": item.reason,
                 "target_id": item.target_id}
                for item in plan.proposals
            ],
            "relations": len(plan.relations), "exclusions": len(plan.exclusions),
        }
