"""Confirmed migration review and import boundary."""

from pathlib import Path

import pytest

from test_atomic_import import write_import_bundle
from threaddesk.services.migration import AtomicImportService, DryRunPlanner, validate_bundle
from threaddesk.services.migration.preview import MigrationReviewService
from threaddesk.storage.sqlite_store import SQLiteStore


def test_review_stages_bundle_without_importing_then_commits_once(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "workspace")
    bundle = write_import_bundle(tmp_path / "notion.tdbundle")
    review = MigrationReviewService(store)

    dry_run = review.stage(bundle)

    assert dry_run["can_confirm_import"] is True
    assert dry_run["review_sha256"] == dry_run["bundle_sha256"]
    assert store.list_nodes() == []
    assert (store.workspace_path / "migration-reviews" / f"{dry_run['bundle_sha256']}.tdbundle").is_file()

    result = review.commit(dry_run["review_sha256"])

    assert result["status"] == "committed"
    assert len(store.list_nodes()) == 2
    assert review.commit(dry_run["review_sha256"]) == result


def _create_conflict(tmp_path: Path):
    store = SQLiteStore(tmp_path / "workspace")
    first = write_import_bundle(tmp_path / "first.tdbundle")
    validated = validate_bundle(first)
    plan = DryRunPlanner().plan(
        validated,
        existing_nodes=store.list_nodes(),
        source_records=store.list_source_records("notion"),
    )
    AtomicImportService(store).commit(validated, plan)
    local = next(item for item in store.list_nodes() if item.kind == "project")
    local.details = "Local work that must survive."
    local.revision += 1
    store.save_node(local)
    changed = write_import_bundle(
        tmp_path / "changed.tdbundle",
        export_id="export-2",
        project_title="ThreadDesk changed in Notion",
    )
    return store, local.id, changed


def _conflict_choice(dry_run: dict, action: str) -> dict:
    conflict = next(
        proposal for proposal in dry_run["proposals"]
        if proposal["diff"] == "conflict"
    )
    return {
        conflict["source_id"]: {
            "action": action,
            "token": conflict["conflict_token"],
        }
    }


def test_conflict_requires_an_explicit_resolution(tmp_path: Path) -> None:
    store, _, changed = _create_conflict(tmp_path)
    review = MigrationReviewService(store)
    dry_run = review.stage(changed)

    assert dry_run["blockers"] == ["conflict"]
    assert dry_run["can_confirm_import"] is False
    conflict = next(item for item in dry_run["proposals"] if item["diff"] == "conflict")
    assert conflict["local_version"]["details"] == "Local work that must survive."
    assert conflict["source_version"]["title"] == "ThreadDesk changed in Notion"
    assert len(_conflict_choice(dry_run, "keep_local")) == 1

    with pytest.raises(ValueError, match="resolution_missing"):
        review.commit(dry_run["review_sha256"], resolutions={})


def test_keep_local_acknowledges_source_without_overwriting_local_work(
    tmp_path: Path,
) -> None:
    store, target_id, changed = _create_conflict(tmp_path)
    review = MigrationReviewService(store)
    dry_run = review.stage(changed)

    result = review.commit(
        dry_run["review_sha256"],
        resolutions=_conflict_choice(dry_run, "keep_local"),
    )

    assert result["status"] == "committed"
    assert store.get_node(target_id).details == "Local work that must survive."
    assert "import.conflict.kept_local" in {
        event.name for event in store.list_graph_events()
    }
    repeated = review.stage(changed)
    assert repeated["blockers"] == []
    assert {item["diff"] for item in repeated["proposals"]} == {"noop"}


def test_take_source_overwrites_only_after_explicit_resolution(tmp_path: Path) -> None:
    store, target_id, changed = _create_conflict(tmp_path)
    review = MigrationReviewService(store)
    dry_run = review.stage(changed)

    review.commit(
        dry_run["review_sha256"],
        resolutions=_conflict_choice(dry_run, "take_source"),
    )

    node = store.get_node(target_id)
    assert node.title == "ThreadDesk changed in Notion"
    assert node.details == "# ThreadDesk changed in Notion\n\nOriginal project text.\n"


def test_conflict_resolution_token_expires_after_another_local_change(
    tmp_path: Path,
) -> None:
    store, target_id, changed = _create_conflict(tmp_path)
    review = MigrationReviewService(store)
    dry_run = review.stage(changed)
    resolutions = _conflict_choice(dry_run, "take_source")

    node = store.get_node(target_id)
    node.details = "A newer local edit."
    node.revision += 1
    store.save_node(node)

    with pytest.raises(ValueError, match="resolution_stale"):
        review.commit(dry_run["review_sha256"], resolutions=resolutions)

    assert store.get_node(target_id).details == "A newer local edit."
