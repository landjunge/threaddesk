"""Confirmed migration review and import boundary."""

from pathlib import Path

from test_atomic_import import write_import_bundle
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
