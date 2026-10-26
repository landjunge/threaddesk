"""Explicit, receipt-bound opening of a verified read-only named CAS copy."""
from __future__ import annotations

import hashlib
from pathlib import Path
import shutil
import subprocess
import tempfile

from threaddesk.core.models import now_iso
from threaddesk.services.library_files import state, validation
from threaddesk.services.library_files.launch_services import default_application
from threaddesk.services.library_files.preview import format_info


def _cached_copy(document, record):
    """Reuse only a private unchanged read-only copy, bounding repeated-open disk use."""
    temporary_root = Path(tempfile.gettempdir()).resolve()
    for operation in document["operations"].values():
        result = operation.get("result", {})
        if result.get("action") != "open" or result.get("record_id") != record["id"]:
            continue
        if result.get("sha256") != record["sha256"] or not result.get("opened_path"):
            continue
        path = Path(result["opened_path"])
        try:
            if (path.name != record["filename"] or not path.parent.name.startswith("threaddesk-open-")
                    or path.parent.parent.resolve() != temporary_root
                    or path.is_symlink() or path.parent.is_symlink()):
                continue
            info = path.stat()
            if info.st_nlink != 1 or info.st_mode & 0o222 or info.st_size != record["size"]:
                continue
            digest = hashlib.sha256()
            with path.open("rb") as incoming:
                while chunk := incoming.read(1024 * 1024):
                    digest.update(chunk)
            if digest.hexdigest() == record["sha256"]:
                return path
        except OSError:
            continue
    return None


def _named_copy(service, record, document):
    blob, _ = service.importer.open_record(record["id"])
    cached = _cached_copy(document, record)
    if cached is not None:
        return cached, False
    validation.filename(record["filename"])
    # Named read-only copies are disposable, not a second authoritative store.
    folder = Path(tempfile.mkdtemp(prefix="threaddesk-open-"))
    target = folder / record["filename"]
    try:
        with blob.open("rb") as source, target.open("xb") as output:
            digest = hashlib.sha256()
            count = 0
            while chunk := source.read(1024 * 1024):
                output.write(chunk)
                digest.update(chunk)
                count += len(chunk)
        if count != record["size"] or digest.hexdigest() != record["sha256"]:
            state.fail("file_integrity", "Dateikopie stimmt nicht mit dem gespeicherten Inhalt überein.")
        target.chmod(0o400)
        return target, True
    except BaseException:
        shutil.rmtree(folder)
        raise


def validate_open_request(arguments):
    if (not isinstance(arguments, dict)
            or set(arguments) != {"action", "id", "operation_id", "expected_revision"}
            or arguments.get("action") != "open"):
        state.fail("validation_error", "Ungültige Öffnungsanfrage.")
    validation.operation_id(arguments["operation_id"])
    validation.record_id(arguments["id"])
    revision = arguments["expected_revision"]
    if type(revision) is not int or revision < 1:
        state.fail("validation_error", "Positive erwartete Dateirevision erforderlich.")
    return dict(arguments)


def open_file(service, record_id, *, operation_id, expected_revision):
    request = validate_open_request({"action": "open", "id": record_id,
                                     "operation_id": operation_id,
                                     "expected_revision": expected_revision})
    request_hash = service._request_hash(request)
    with service.store.transaction():
        document = state.read_state(service.root)
        previous = document["operations"].get(operation_id)
        if previous:
            return service._replay(previous, request_hash)
        record = service.info(record_id)
        service._check_revision(record, expected_revision)
        if not format_info(record).get("external_open"):
            state.fail("external_open_blocked", "Dieser Dateityp wird nicht automatisch an ein Programm übergeben.")
        target, created = _named_copy(service, record, document)
        try:
            handler = (service.handler_resolver or default_application)(target)
            if (not isinstance(handler, str) or not handler.endswith(".app")
                    or not Path(handler).is_absolute()
                    or Path(handler).name.casefold() in {"terminal.app", "python launcher.app", "script editor.app"}):
                state.fail("external_open_blocked", "Das zugeordnete Programm ist kein erlaubter Dateibetrachter.")
        except BaseException:
            if created:
                shutil.rmtree(target.parent)
            raise
        receipt = {"operation_id": operation_id, "action": "open", "record_id": record_id,
                   "revision": record["revision"], "duplicate": False,
                   "status": "unknown", "application": handler,
                   "opened_path": str(target), "sha256": record["sha256"],
                   "launch_requested_at": now_iso(), "human_read_confirmed": False}
        # Commit the reservation BEFORE LaunchServices: a lost result never reopens.
        document["operations"][operation_id] = {"request_hash": request_hash, "result": receipt,
                                                "recorded_at": now_iso()}
        state.write_state(service.root, document)
    opener = service.opener or subprocess.run
    try:
        completed = opener(["/usr/bin/open", "-a", handler, "--", str(target)],
                           capture_output=True, text=True, timeout=15, check=False)
        status = "launch_requested" if completed.returncode == 0 else "failed"
        error = "" if completed.returncode == 0 else "external_open_failed"
    except subprocess.TimeoutExpired:
        status, error = "unknown", "external_open_timeout"
    except OSError:
        status, error = "failed", "external_open_unavailable"
    with service.store.transaction():
        document = state.read_state(service.root)
        saved = document["operations"][operation_id]
        saved["result"].update(status=status, error=error, completed_at=now_iso())
        state.write_state(service.root, document)
        return dict(saved["result"])
