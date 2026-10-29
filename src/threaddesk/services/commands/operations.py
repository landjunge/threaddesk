"""Explicit operational commands reuse existing local domain contracts."""
from __future__ import annotations

from threaddesk.services.commands.model import CommandSpec
from threaddesk.services.commands.schemas import (
    BOOL,
    ID,
    PAGE,
    TEXT,
    array,
    choice,
    obj,
    page,
)


def specifications():
    def spec(identity, fields, required, handler, *, effect="read", target=None):
        return CommandSpec(identity, identity.split(".")[0], identity.replace(".", " "), obj(fields, required),
                           handler, effect=effect, scope="workspace.read" if effect == "read" else "workspace.write",
                           revision_target=target,
                           backends=("sqlite",) if identity.startswith("migration.") and identity != "migration.preview" else ("json", "sqlite"))
    yield spec("room.status", {}, (), lambda svc, a: _rooms(svc).view())
    yield spec("library.resume", {"import_operation_id": ID}, ("import_operation_id",), _resume, effect="external")
    for action, fields, required, method in (
        ("create", {"name": TEXT}, ("name",), "create_room"),
        ("select", {"room_id": ID}, ("room_id",), "select_room"),
        ("invite", {"role": choice("member", "read_only")}, (), "invite"),
        ("join", {"code": TEXT, "peer_base": TEXT, "own_base": TEXT}, ("code", "peer_base", "own_base"), "join"),
        ("sync", {}, (), "sync"),
    ):
        yield spec("room." + action, fields, required,
                   lambda svc, a, selected=method: getattr(_rooms(svc), selected)(**a), effect="external")
    yield spec("server_sync.status", {"thread_id": ID}, ("thread_id",),
               lambda svc, a: _bindings(svc).view(a["thread_id"]))
    yield CommandSpec("server_sync.owner_reference", "server_sync", "Amend explicit local owner file authority",
                      obj({"thread_id": ID, "path": {**TEXT, "minLength": 1}, "allowed": BOOL},
                          ("thread_id", "path", "allowed")), _owner_reference,
                      effect="external", scope="workspace.write", revision_target="thread_id",
                      allowed_transports=("local", "cli"))
    configure = {"thread_id": ID, "url": TEXT, "project_id": TEXT, "root": TEXT, "token": TEXT,
                 "approved_roots": array(TEXT), "owner_references": array(TEXT),
                 "automatic": BOOL, "offline_enabled": BOOL}
    yield spec("server_sync.configure", configure, ("thread_id", "url", "project_id", "root", "token"),
               _configure, effect="external", target="thread_id")
    yield spec("server_sync.run", {"thread_id": ID}, ("thread_id",), _sync, effect="external", target="thread_id")
    yield spec("server_sync.lifecycle_sync", {"thread_id": ID}, ("thread_id",), _lifecycle_sync,
               effect="external", target="thread_in_trash:thread_id")
    yield spec("server_sync.offline", {"thread_id": ID, "enabled": BOOL}, ("thread_id", "enabled"),
               _offline, effect="external", target="thread_id")
    yield spec("server_sync.resolve", {"thread_id": ID, "conflict_id": TEXT, "expected": {}, "chosen": {},
                                       "resolution_id": ID}, ("thread_id", "conflict_id", "expected", "chosen", "resolution_id"),
               _resolve, effect="external", target="thread_in_trash:thread_id")
    yield spec("hausmeister.status", {}, (), lambda svc, a: _house(svc).status())
    yield spec("hausmeister.jobs", PAGE, (), lambda svc, a: page(_house(svc).jobs(), a))
    for action, fields, required, method in (
        ("probe", {}, (), "probe_models"),
        ("enable", {"enabled": BOOL}, ("enabled",), "set_enabled"),
        ("model", {"model": TEXT}, ("model",), "set_model"),
        ("enqueue", {"thread_id": ID, "order": TEXT, "task_id": ID}, ("thread_id", "order"), "enqueue"),
        ("run", {"thread_id": ID, "order": TEXT, "task_id": ID}, ("thread_id", "order"), "run_now"),
    ):
        yield spec("hausmeister." + action, fields, required,
                   lambda svc, a, selected=method: getattr(_house(svc), selected)(**a),
                   effect="external", target="thread_id" if "thread_id" in fields else None)
    yield spec("profiles.list", {}, (), _profiles)
    yield spec("profiles.activate", {"name": TEXT}, ("name",), _activate, effect="external")
    yield spec("profiles.original", {}, (), _original, effect="external")
    yield spec("backup.create", {}, (), _backup, effect="external")
    yield spec("backup.verify", {"path": TEXT}, ("path",), _verify_backup)
    yield spec("backup.restore", {"path": TEXT, "sha256": TEXT, "confirmation": choice("restore_as_new_profile")},
               ("path", "sha256", "confirmation"), _restore_backup, effect="external")
    yield spec("migration.preview", {"path": TEXT}, ("path",), _migration_preview)
    yield spec("migration.stage", {"path": TEXT}, ("path",), _migration_stage, effect="external")
    yield spec("migration.commit", {"bundle_sha256": TEXT, "resolutions": {"type": "object"},
                                     "confirmation": choice("import_reviewed_bundle")},
               ("bundle_sha256", "confirmation"), _migration_commit, effect="external")
    yield spec("migration.recover", {"batch_id": ID}, ("batch_id",), _migration_recover, effect="external")
    selection = {"node_ids": array(ID, 10000), "include_private": BOOL}
    yield spec("export.preview", {**selection, "as_of": {"type": "string", "maxLength": 64}}, (), _export_preview)
    yield spec("export.write", {**selection, "format": choice("json", "markdown", "csv", "xlsx", "svg", "pdf", "zip"),
                                 "language": choice("de", "en")}, ("format",), _export_write, effect="external")


def _rooms(svc):
    from threaddesk.services.room_sync import RoomBook
    return RoomBook(svc.store)


def _owner_reference(svc, args):
    from threaddesk.server_sync.desktop import record_owner_reference
    record_owner_reference(svc, args["thread_id"], args["path"], allowed=args["allowed"])
    return _bindings(svc).view(args["thread_id"])


def _resume(svc, args):
    from threaddesk.services.library_api import LibraryApplication
    return LibraryApplication(svc.store).call({"action": "resume", "operation_id": args["import_operation_id"]})


def _house(svc):
    from threaddesk.services.hausmeister import Hausmeister
    return Hausmeister(svc.store)


def _bindings(svc):
    from threaddesk.server_sync.desktop import BindingBook
    return BindingBook(svc)


def _configure(svc, args):
    args = dict(args)
    identity = args.pop("thread_id")
    _bindings(svc).save(identity, **args)
    return _bindings(svc).view(identity)


def _sync(svc, args):
    from threaddesk.server_sync.desktop import DesktopSyncManager
    return DesktopSyncManager(lambda: svc).run_once(svc, args["thread_id"])


def _offline(svc, args):
    _bindings(svc).update(args["thread_id"], {"offline_enabled": args["enabled"], "offline_pending": True})
    return _bindings(svc).view(args["thread_id"])


def _lifecycle_sync(svc, args):
    from threaddesk.server_sync.desktop import DesktopSyncManager
    return DesktopSyncManager(lambda: svc).reconcile_lifecycle(svc, args["thread_id"])


def _resolve(svc, a):
    from threaddesk.server_sync.metadata import resolve_conflict
    return resolve_conflict(svc, a["thread_id"], a["conflict_id"], a["expected"], a["chosen"], a["resolution_id"])


def _profiles(svc, args):
    from threaddesk.storage.portable_backup import profiles, selected_profile
    root = _profile_root(svc)
    current, _ = selected_profile(root)
    return {"profiles": profiles(root), "active": current.name}


def _activate(svc, args):
    from threaddesk.storage.portable_backup import activate_profile
    root = _profile_root(svc)
    activate_profile(root, args["name"])
    _reset_view_delivery(root)
    from threaddesk.storage.portable_backup import profiles, selected_profile
    current, _ = selected_profile(root)
    return {"profiles": profiles(root), "active": current.name}


def _original(svc, args):
    root = _profile_root(svc)
    marker = root / "active-profile.json"
    if marker.is_symlink():
        from threaddesk.core.errors import ManagementError
        raise ManagementError("profile_unavailable", "Profile selector is invalid")
    marker.unlink(missing_ok=True)
    _reset_view_delivery(root)
    return {"active": root.name, "restored_profile": False}


def _reset_view_delivery(root):
    from threaddesk.services.graph_view_control import GraphViewControlService
    from threaddesk.storage.json_store import JsonStore
    from threaddesk.storage.portable_backup import selected_profile
    from threaddesk.storage.sqlite_store import SQLiteStore
    path, backend = selected_profile(root)
    store = SQLiteStore(path) if backend == "sqlite" else JsonStore(path)
    try:
        GraphViewControlService(store).reset_runtime()
    finally:
        if hasattr(store, "connection"):
            store.connection.close()


def _backup(svc, args):
    import tempfile
    from pathlib import Path

    from threaddesk.services.commands.artifacts import publish_file
    from threaddesk.storage.portable_backup import export_backup
    with tempfile.TemporaryDirectory(prefix='threaddesk-command-backup-') as folder:
        path = Path(folder) / 'backup.zip'
        summary = export_backup(svc.store, path)
        return {**publish_file(svc.store, path), 'backup': summary}


def _verify_backup(svc, args):
    from threaddesk.services.commands.artifacts import verify_portable
    return verify_portable(args["path"])


def _restore_backup(svc, args):
    from pathlib import Path

    from threaddesk.core.errors import ManagementError
    from threaddesk.storage.portable_backup import restore_backup
    from threaddesk.storage.workspace_backup import BackupError
    try:
        restored = restore_backup(Path(args['path']), _profile_root(svc), expected_sha256=args['sha256'])
        return {'profile_path': str(restored), 'sha256': args['sha256']}
    except BackupError as exc:
        raise ManagementError('preview_conflict' if 'since preview' in str(exc) else 'artifact_unavailable', str(exc)) from exc


def _profile_root(svc):
    """Derive only from the bound store, never an unrelated global HOME."""
    from pathlib import Path

    from threaddesk.storage.portable_backup import selected_profile
    workspace = Path(svc.store.workspace_path).resolve()
    if workspace.parent.name == "profiles":
        candidate = workspace.parent.parent
        current, _ = selected_profile(candidate)
        if current.resolve() == workspace:
            return candidate
    return workspace


def _migration_preview(svc, args):
    from pathlib import Path

    from threaddesk.services.migration.preview import MigrationPreviewService
    return MigrationPreviewService(svc.store).inspect(Path(args["path"]))


def _review(svc):
    from threaddesk.services.migration.preview import MigrationReviewService
    from threaddesk.storage.sqlite_store import SQLiteStore
    if not isinstance(svc.store, SQLiteStore):
        from threaddesk.core.errors import ManagementError
        raise ManagementError("unsupported_backend", "Reviewed migration writes require a SQLite profile")
    return MigrationReviewService(svc.store)


def _migration_stage(svc, args):
    from pathlib import Path
    return _review(svc).stage(Path(args["path"]))


def _migration_commit(svc, a):
    return _review(svc).commit(a["bundle_sha256"], resolutions=a.get("resolutions"))


def _migration_recover(svc, a):
    return {"recovery_path": str(_review(svc).recover(a["batch_id"]))}


def _export_preview(svc, args):
    from threaddesk.services.knowledge_export import KnowledgeExportService
    values = dict(args)
    return KnowledgeExportService(svc.store).build(generated_at=values.pop("as_of", None), **values)


def _export_write(svc, args):
    from threaddesk.services.commands.artifacts import export
    return export(svc.store, args)
