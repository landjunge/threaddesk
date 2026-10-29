"""Verified owned exports, without arbitrary destination paths or execution."""
from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path

from threaddesk.core.errors import ManagementError


def read_verified_file(path, *, limit=128 * 1024 * 1024, sha256=None):
    """Reuse the backup reader's descriptor/path/size race protections."""
    from threaddesk.storage.workspace_backup import BackupError, _SourceTree
    path = Path(path).absolute()
    try:
        with _SourceTree(path.parent) as source:
            info = source.info(path.name)
            body = source.read(path.name, info, limit=limit)
    except (OSError, ValueError, BackupError) as exc:
        raise ManagementError("artifact_unavailable", "The selected regular file cannot be verified") from exc
    if sha256 is not None and hashlib.sha256(body).hexdigest() != sha256:
        raise ManagementError("artifact_conflict", "Generated artifact has different contents")
    return body


def publish(store, body, suffix, *, prefix="export"):
    if isinstance(body, str):
        body = body.encode("utf-8")
    if not isinstance(body, bytes) or len(body) > 128 * 1024 * 1024:
        raise ManagementError("artifact_limit", "Generated artifact exceeds its budget")
    digest = hashlib.sha256(body).hexdigest()
    name = "command-" + prefix + "-" + digest + "." + suffix
    target = store.artifact_path(name)
    if target.exists() or target.is_symlink():
        read_verified_file(target, sha256=digest)
    else:
        handle, temporary = tempfile.mkstemp(prefix=".command-artifact-", dir=target.parent)
        try:
            with os.fdopen(handle, "wb") as output:
                os.fchmod(output.fileno(), 0o600)
                output.write(body)
                output.flush()
                os.fsync(output.fileno())
            try:
                os.link(temporary, target)
            except FileExistsError:
                read_verified_file(target, sha256=digest)
        finally:
            Path(temporary).unlink()
    return {"filename": name, "path": str(target), "size": len(body), "sha256": digest,
            "download_path": "/api/command-artifacts/" + name, "executed": False}


def portable_bytes(path):
    from threaddesk.storage.portable_backup import LEGACY_LIMIT, inspect_backup
    body = read_verified_file(path, limit=LEGACY_LIMIT)
    return body, inspect_backup(body)


def verify_portable(path):
    from threaddesk.storage.portable_backup import inspect_backup
    from threaddesk.storage.workspace_backup import BackupError
    try:
        return inspect_backup(Path(path))
    except BackupError as exc:
        raise ManagementError("artifact_unavailable", str(exc)) from exc


def publish_file(store, source, *, prefix="backup"):
    """Publish a large generated ZIP through the same owned artifact contract."""
    from threaddesk.storage.portable_backup import LIMIT
    from threaddesk.storage.portable_stream import copy_hash, input_file
    from threaddesk.storage.workspace_backup import BackupError, _publish_new
    temporary = None
    try:
        with input_file(Path(source), limit=LIMIT) as (incoming, _):
            digest = copy_hash(incoming, limit=LIMIT)
            name = "command-" + prefix + "-" + digest['sha256'] + ".zip"
            target = store.artifact_path(name)
            if target.exists() or target.is_symlink():
                with input_file(target, limit=LIMIT) as (existing, _):
                    if copy_hash(existing, limit=LIMIT) != digest:
                        raise ManagementError("artifact_conflict", "Generated artifact has different contents")
            else:
                fd, temporary = tempfile.mkstemp(prefix=".command-artifact-", dir=target.parent)
                with os.fdopen(fd, 'wb') as output:
                    os.fchmod(output.fileno(), 0o600)
                    incoming.seek(0)
                    if copy_hash(incoming, output, limit=LIMIT) != digest:
                        raise ManagementError("artifact_conflict", "Generated artifact changed during publication")
                    output.flush()
                    os.fsync(output.fileno())
        if temporary is not None:
            with input_file(Path(temporary), limit=LIMIT) as (captured, _):
                if copy_hash(captured, limit=LIMIT) != digest:
                    raise ManagementError("artifact_conflict", "Generated artifact copy failed readback")
            try:
                _publish_new(Path(temporary), target)
            except FileExistsError:
                with input_file(target, limit=LIMIT) as (existing, _):
                    if copy_hash(existing, limit=LIMIT) != digest:
                        raise ManagementError("artifact_conflict", "Generated artifact has different contents")
        return {"filename": name, "path": str(target), "size": digest['size'], "sha256": digest['sha256'],
                "download_path": "/api/command-artifacts/" + name, "executed": False}
    except BackupError as exc:
        raise ManagementError("artifact_unavailable", str(exc)) from exc
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)


def download_file(path, sha256):
    """Own an immutable checked download copy until the HTTP response completes."""
    from threaddesk.storage.portable_backup import LIMIT
    from threaddesk.storage.portable_stream import copy_hash, input_file
    from threaddesk.storage.workspace_backup import BackupError
    staging = tempfile.TemporaryDirectory(prefix='threaddesk-command-download-')
    target = Path(staging.name) / 'download'
    try:
        with input_file(Path(path), limit=LIMIT) as (incoming, _), target.open('xb') as output:
            target.chmod(0o600)
            digest = copy_hash(incoming, output, limit=LIMIT)
        if digest['sha256'] != sha256:
            raise ManagementError('artifact_conflict', 'Generated artifact has different contents')
        with input_file(target, limit=LIMIT) as (captured, _):
            if copy_hash(captured, limit=LIMIT) != digest:
                raise ManagementError('artifact_conflict', 'Generated download copy failed readback')
        return target, staging
    except (OSError, BackupError, ManagementError) as exc:
        staging.cleanup()
        if isinstance(exc, ManagementError):
            raise
        raise ManagementError('artifact_unavailable', 'The selected regular file cannot be verified') from exc


def export(store, args):
    from threaddesk.services.knowledge_export import KnowledgeExportService
    from threaddesk.services.knowledge_package import KnowledgePackageService
    from threaddesk.services.knowledge_visual_export import encode_pdf, encode_svg
    data = dict(args)
    format_name, language = data.pop("format"), data.pop("language", "de")
    service = KnowledgeExportService(store)
    payload = service.build(**data)
    if format_name == "json":
        body, suffix = service.encode(payload), "json"
    elif format_name == "markdown":
        body, suffix = service.encode_markdown(payload, language=language), "md"
    elif format_name == "csv":
        body, suffix = service.encode_csv(payload), "csv"
    elif format_name == "xlsx":
        body, suffix = service.encode_xlsx(payload), "xlsx"
    elif format_name == "svg":
        body, suffix = encode_svg(payload, language=language), "svg"
    elif format_name == "pdf":
        body, suffix = encode_pdf(payload, language=language), "pdf"
    else:
        body, suffix = KnowledgePackageService(store).encode(payload, language=language), "zip"
    return {**publish(store, body, suffix), "format": format_name,
            "private_content_included": data.get("include_private", False)}
