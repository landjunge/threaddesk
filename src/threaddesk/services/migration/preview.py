"""Read-only previews and confirmed imports for the local migration UI."""
from __future__ import annotations
from pathlib import Path
import shutil
from typing import Any
from threaddesk.services.migration.bundle import validate_bundle
from threaddesk.services.migration.conflicts import (
    allowed_actions,
    conflict_token,
    resolve_conflicts,
)
from threaddesk.services.migration.diff import DryRunPlanner
from threaddesk.services.migration.importer import AtomicImportService
from threaddesk.storage.protocols import Store
from threaddesk.storage.sqlite_store import SQLiteStore

BLOCKING_DIFFS = frozenset({"conflict", "open", "possible_duplicate"})

class MigrationPreviewService:
    """Validate and plan a bundle without changing ThreadDesk data."""
    def __init__(self, store: Store, *, planner: DryRunPlanner | None = None) -> None:
        self.store = store
        self.planner = planner or DryRunPlanner()

    def plan(self, bundle_path: Path) -> tuple[Any, dict[str, Any]]:
        bundle = validate_bundle(bundle_path)
        existing_nodes = tuple(self.store.list_nodes())
        nodes_by_id = {node.id: node for node in existing_nodes}
        plan = self.planner.plan(bundle, existing_nodes=existing_nodes,
            source_records=self.store.list_source_records("notion"))
        blockers = sorted({item.diff.value for item in plan.proposals
            if item.diff.value in BLOCKING_DIFFS} | ({"open_relation"} if any(
            relation.mapping_state == "open" for relation in plan.relations) else set()))
        return bundle, {"bundle_sha256": bundle.bundle_sha256, "counts": dict(plan.counts),
            "blockers": blockers, "can_confirm_import": not blockers,
            "proposals": [{"source_id": item.source_id, "title": item.draft.title,
                "diff": item.diff.value, "reason": item.reason, "target_id": item.target_id,
                "source_version": {"title": item.draft.title, "status": item.draft.status,
                    "details": item.draft.details} if item.diff.value == "conflict" else None,
                "local_version": ({"title": nodes_by_id[item.target_id].title,
                    "status": nodes_by_id[item.target_id].status,
                    "details": nodes_by_id[item.target_id].details}
                    if item.diff.value == "conflict" and item.target_id in nodes_by_id else None),
                "conflict_token": conflict_token(bundle.bundle_sha256, item, nodes_by_id)
                    if item.diff.value == "conflict" else None,
                "allowed_actions": list(allowed_actions(item))}
                for item in plan.proposals], "relations": len(plan.relations),
            "exclusions": len(plan.exclusions)}

    def inspect(self, bundle_path: Path) -> dict[str, Any]:
        _, result = self.plan(bundle_path)
        return result

class MigrationReviewService:
    """Stores a reviewed bundle; a second explicit request may commit it."""
    def __init__(self, store: SQLiteStore, *, planner: DryRunPlanner | None = None) -> None:
        self.store = store
        self.preview = MigrationPreviewService(store, planner=planner)
        self.review_root = store.workspace_path / "migration-reviews"

    def _path(self, bundle_sha256: str) -> Path:
        if len(bundle_sha256) != 64 or any(char not in "0123456789abcdef" for char in bundle_sha256):
            raise ValueError("bundle_sha256")
        return self.review_root / f"{bundle_sha256}.tdbundle"

    def stage(self, bundle_path: Path) -> dict[str, Any]:
        bundle, result = self.preview.plan(bundle_path)
        target = self._path(bundle.bundle_sha256)
        self.review_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if not target.exists():
            temporary = target.with_suffix(".partial")
            shutil.copyfile(bundle.path, temporary)
            temporary.chmod(0o600)
            temporary.replace(target)
        staged, reviewed = self.preview.plan(target)
        if staged.bundle_sha256 != bundle.bundle_sha256:
            raise ValueError("review_hash")
        return {**reviewed, "review_sha256": staged.bundle_sha256,
                "can_confirm_import": not reviewed["blockers"]}

    def commit(
        self,
        bundle_sha256: str,
        *,
        resolutions: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        path = self._path(bundle_sha256)
        bundle, result = self.preview.plan(path)
        if bundle.bundle_sha256 != bundle_sha256:
            raise ValueError("review_hash")
        if any(blocker != "conflict" for blocker in result["blockers"]):
            raise ValueError("review_blocked")
        existing_nodes = tuple(self.store.list_nodes())
        plan = self.preview.planner.plan(bundle, existing_nodes=existing_nodes,
            source_records=self.store.list_source_records("notion"))
        resolved = resolve_conflicts(
            plan,
            existing_nodes=existing_nodes,
            resolutions=resolutions,
        )
        return AtomicImportService(self.store).commit(bundle, resolved)

    def recover(self, batch_id: str) -> Path:
        """Create a verified recovery copy; it never overwrites the live workspace."""
        target = self.store.workspace_path / "recovery" / batch_id
        return AtomicImportService(self.store).restore(batch_id, target)
