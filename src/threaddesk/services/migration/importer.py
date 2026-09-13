"""Atomic commit and verified rollback for reviewed migration plans."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import tempfile
from typing import Callable

from threaddesk.core.import_models import DiffKind, DryRunResult, ImportProposal
from threaddesk.core.models import GraphEvent, KnowledgeNode, Relation, new_id, now_iso
from threaddesk.core.provenance import SourceRecord
from threaddesk.core.errors import NotFound
from threaddesk.services.migration.bundle import ValidatedBundle
from threaddesk.services.migration.diff import node_target_hash
from threaddesk.storage.artifacts import ContentAddressedArtifacts, PublishedArtifact
from threaddesk.storage.sqlite_store import SQLiteStore
from threaddesk.storage.workspace_backup import WorkspaceBackup


class AtomicImportError(RuntimeError):
    pass


class ImportBlocked(AtomicImportError):
    pass


class ImportOutcomeUncertain(AtomicImportError):
    def __init__(self, batch_id: str) -> None:
        self.batch_id = batch_id
        super().__init__(f"import_outcome_uncertain:{batch_id}")


class AtomicImportService:
    """Commit a reviewed plan; file selection and dry-run never call this class."""

    def __init__(
        self,
        store: SQLiteStore,
        *,
        backup: WorkspaceBackup | None = None,
        fault: Callable[[str], None] | None = None,
        disk_free: Callable[[Path], int] | None = None,
    ) -> None:
        self.store = store
        self.workspace_path = store.workspace_path
        self.backup = backup or WorkspaceBackup(self.workspace_path / "backups")
        self.fault = fault
        self.disk_free = disk_free or (lambda path: shutil.disk_usage(path).free)
        self.artifacts = ContentAddressedArtifacts(self.workspace_path)

    def _fault(self, stage: str) -> None:
        if self.fault:
            self.fault(stage)

    @staticmethod
    def _batch_id(bundle_sha256: str) -> str:
        return f"notion-{bundle_sha256[:24]}"

    def _existing_committed(self, batch_id: str):
        try:
            batch = self.store.get_import_batch(batch_id)
        except NotFound:
            return None
        return batch if batch.get("status") == "committed" else None

    @staticmethod
    def _blockers(plan: DryRunResult) -> list[str]:
        blocked = {
            proposal.diff.value
            for proposal in plan.proposals
            if proposal.diff in {
                DiffKind.CONFLICT,
                DiffKind.OPEN,
                DiffKind.POSSIBLE_DUPLICATE,
            }
        }
        if any(relation.mapping_state == "open" for relation in plan.relations):
            blocked.add("open_relation")
        return sorted(blocked)

    def _check_space(self, bundle: ValidatedBundle, plan: DryRunResult) -> None:
        database_size = (
            self.store.database_path.stat().st_size
            if self.store.database_path.exists()
            else 0
        )
        content_size = sum(
            len(item.draft.details.encode("utf-8")) for item in plan.proposals
        )
        required = bundle.path.stat().st_size * 2 + database_size + content_size + 1024 * 1024
        if self.disk_free(self.workspace_path) < required:
            raise AtomicImportError("disk_space")

    @staticmethod
    def _copy_verified(source: Path, target: Path, expected_hash: str) -> bool:
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if target.exists():
            if hashlib.sha256(target.read_bytes()).hexdigest() != expected_hash:
                raise AtomicImportError("existing_file_checksum")
            return False
        temporary = target.with_suffix(target.suffix + ".partial")
        shutil.copyfile(source, temporary)
        if hashlib.sha256(temporary.read_bytes()).hexdigest() != expected_hash:
            temporary.unlink()
            raise AtomicImportError("copied_file_checksum")
        temporary.chmod(0o600)
        temporary.replace(target)
        return True

    @staticmethod
    def _materialize(proposal: ImportProposal, existing: KnowledgeNode | None, timestamp: str) -> KnowledgeNode:
        node = proposal.draft.to_node()
        if existing is None:
            node.created_at = timestamp
            node.updated_at = timestamp
            return node
        node.id = existing.id
        node.created_at = existing.created_at
        node.updated_at = timestamp
        node.revision = existing.revision + 1
        if proposal.diff is DiffKind.ARCHIVE:
            node.status = "archived"
        return node

    def commit(self, bundle: ValidatedBundle, plan: DryRunResult) -> dict:
        if plan.bundle_sha256 != bundle.bundle_sha256:
            raise ImportBlocked("bundle_plan_mismatch")
        bundle.ensure_unchanged()
        batch_id = self._batch_id(bundle.bundle_sha256)
        existing_batch = self._existing_committed(batch_id)
        if existing_batch is not None:
            return existing_batch
        blockers = self._blockers(plan)
        if blockers:
            raise ImportBlocked("unresolved:" + ",".join(blockers))
        self._check_space(bundle, plan)

        backup_path: Path | None = None
        staging: Path | None = None
        published_artifacts: list[PublishedArtifact] = []
        created_files: list[Path] = []
        batch_written = False
        committed = False
        try:
            self._fault("before_backup")
            backup_path = self.backup.create(self.store)
            batch = {
                "id": batch_id,
                "status": "received",
                "bundle_sha256": bundle.bundle_sha256,
                "bundle_id": str(bundle.manifest["export_id"]),
                "backup_path": str(backup_path),
            }
            self.store.save_import_batch(batch_id, batch)
            batch_written = True
            self._fault("after_backup")

            staging = Path(
                tempfile.mkdtemp(prefix=f".import-stage-{batch_id}-", dir=self.workspace_path)
            )
            staged_bundle = staging / "bundle.tdbundle"
            shutil.copyfile(bundle.path, staged_bundle)
            if hashlib.sha256(staged_bundle.read_bytes()).hexdigest() != bundle.bundle_sha256:
                raise AtomicImportError("staged_bundle_checksum")
            artifact_staging = staging / "artifacts"
            staged_by_source = {}
            for proposal in plan.proposals:
                if proposal.diff not in {DiffKind.NEW, DiffKind.UPDATE, DiffKind.ARCHIVE}:
                    continue
                if proposal.draft.details:
                    staged_by_source[proposal.source_id] = self.artifacts.stage(
                        proposal.draft.details.encode("utf-8"), artifact_staging
                    )
            report = {
                "kind": "threaddesk.import-report",
                "version": 1,
                "batch_id": batch_id,
                "bundle_sha256": bundle.bundle_sha256,
                "proposals": [
                    {
                        "source_id": item.source_id,
                        "diff": item.diff.value,
                        "reason": item.reason,
                        "target_id": item.target_id,
                    }
                    for item in plan.proposals
                ],
                "relations": len(plan.relations),
                "exclusions": len(plan.exclusions),
            }
            staged_report = staging / "report.json"
            staged_report.write_text(
                json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            self.store.save_import_batch(batch_id, {**batch, "status": "staged"})
            self._fault("after_stage")

            bundle_path = self.workspace_path / "imports" / f"{bundle.bundle_sha256}.tdbundle"
            if self._copy_verified(staged_bundle, bundle_path, bundle.bundle_sha256):
                created_files.append(bundle_path)
            report_hash = hashlib.sha256(staged_report.read_bytes()).hexdigest()
            report_path = self.workspace_path / f"import-report-{batch_id}.json"
            if self._copy_verified(staged_report, report_path, report_hash):
                created_files.append(report_path)
            unique_staged = {staged.name: staged for staged in staged_by_source.values()}
            for staged in unique_staged.values():
                published_artifacts.append(self.artifacts.publish(staged))
            self._fault("after_publish")

            committing = {
                **batch,
                "status": "committing",
                "bundle_path": str(bundle_path),
                "report_path": str(report_path),
            }
            self.store.save_import_batch(batch_id, committing)
            timestamp = now_iso()
            counts = {"created": 0, "updated": 0, "archived": 0, "relations": 0}
            actual_ids: dict[str, str] = {}
            artifacts_by_hash = {item.sha256: item for item in published_artifacts}
            existing_relations = {
                relation.id: relation for relation in self.store.list_relations()
            }
            first_write = True
            with self.store.transaction():
                for proposal in plan.proposals:
                    if proposal.diff is DiffKind.NOOP:
                        actual_ids[proposal.draft.id] = proposal.target_id or proposal.draft.id
                        continue
                    if proposal.diff is DiffKind.ARCHIVE and proposal.target_id is None:
                        continue
                    if proposal.diff not in {DiffKind.NEW, DiffKind.UPDATE, DiffKind.ARCHIVE}:
                        continue
                    existing = (
                        self.store.get_node(proposal.target_id)
                        if proposal.target_id is not None
                        else None
                    )
                    node = self._materialize(proposal, existing, timestamp)
                    self.store.save_node(node)
                    actual_ids[proposal.draft.id] = node.id
                    action = {
                        DiffKind.NEW: "created",
                        DiffKind.UPDATE: "updated",
                        DiffKind.ARCHIVE: "archived",
                    }[proposal.diff]
                    counts[action] += 1
                    self.store.append_graph_event(
                        GraphEvent(
                            id=new_id(),
                            name=f"import.node.{action}",
                            entity_id=node.id,
                            entity_type="node",
                            revision=node.revision,
                            occurred_at=timestamp,
                            payload={"batch_id": batch_id, "source_id": proposal.source_id},
                        )
                    )
                    self.store.save_source_record(
                        SourceRecord(
                            source_system=proposal.provenance.source_system,
                            source_id=proposal.source_id,
                            target_id=node.id,
                            source_hash=proposal.provenance.source_hash,
                            target_hash=node_target_hash(node),
                            bundle_id=proposal.provenance.bundle_id,
                            imported_at=timestamp,
                            mapping_rule=proposal.provenance.mapping_rule,
                        )
                    )
                    staged = staged_by_source.get(proposal.source_id)
                    if staged is not None:
                        artifact = artifacts_by_hash[staged.name]
                        self.store.save_artifact(artifact.to_record())
                        self.store.replace_node_artifact(
                            {
                                "node_id": node.id,
                                "sha256": artifact.sha256,
                                "role": "content",
                                "source_id": proposal.source_id,
                                "batch_id": batch_id,
                            }
                        )
                    if first_write:
                        first_write = False
                        self._fault("during_transaction")

                for mapped_relation in plan.relations:
                    source_id = actual_ids.get(mapped_relation.draft.source_id)
                    target_id = actual_ids.get(mapped_relation.draft.target_id)
                    if source_id is None or target_id is None:
                        continue
                    relation = Relation(
                        id=mapped_relation.draft.id,
                        source_id=source_id,
                        target_id=target_id,
                        kind=mapped_relation.draft.kind,
                        created_at=timestamp,
                        source=mapped_relation.draft.source,
                        metadata=dict(mapped_relation.draft.metadata),
                    )
                    previous_relation = existing_relations.get(relation.id)
                    if previous_relation is not None and all(
                        getattr(previous_relation, field) == getattr(relation, field)
                        for field in ("source_id", "target_id", "kind", "source", "metadata")
                    ):
                        continue
                    self.store.save_relation(relation)
                    counts["relations"] += 1
                    self.store.append_graph_event(
                        GraphEvent(
                            id=new_id(),
                            name="import.relation.created",
                            entity_id=relation.id,
                            entity_type="relation",
                            revision=relation.revision,
                            occurred_at=timestamp,
                            payload={"batch_id": batch_id},
                        )
                    )
                completed = {
                    **committing,
                    "status": "committed",
                    "committed_at": timestamp,
                    "counts": counts,
                }
                self.store.save_import_batch(batch_id, completed)
                self._fault("before_commit")
            committed = True
            try:
                self._fault("after_commit")
            except Exception as exc:
                raise ImportOutcomeUncertain(batch_id) from exc
            return completed
        except ImportOutcomeUncertain:
            raise
        except Exception as exc:
            if committed:
                raise ImportOutcomeUncertain(batch_id) from exc
            for artifact in published_artifacts:
                ContentAddressedArtifacts.cleanup_if_created(artifact)
            for path in created_files:
                if path.exists():
                    path.unlink()
            if batch_written and backup_path is not None:
                self.store.save_import_batch(
                    batch_id,
                    {
                        "id": batch_id,
                        "status": "rolled_back",
                        "bundle_sha256": bundle.bundle_sha256,
                        "bundle_id": str(bundle.manifest["export_id"]),
                        "backup_path": str(backup_path),
                        "error": type(exc).__name__,
                    },
                )
            if isinstance(exc, AtomicImportError):
                raise
            raise AtomicImportError(f"atomic_import_failed:{type(exc).__name__}") from exc
        finally:
            if staging is not None and staging.exists():
                shutil.rmtree(staging)

    def restore(self, batch_id: str, target: Path) -> Path:
        batch = self.store.get_import_batch(batch_id)
        backup_path = batch.get("backup_path")
        if not backup_path:
            raise AtomicImportError("backup_missing")
        return self.backup.restore_verified(Path(backup_path), Path(target))

    def recover_on_start(self) -> list[dict]:
        return self.backup.recover_on_start(
            self.store, self.workspace_path / "recovery"
        )
