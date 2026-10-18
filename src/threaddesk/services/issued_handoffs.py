"""Issued-source and run bindings; no job queue, dispatch or secret material."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from pathlib import Path

from threaddesk.core.errors import ManagementError
from threaddesk.core.models import Snapshot, ThreadContext, new_id, now_iso
from threaddesk.core.secrets import reject_secrets
from threaddesk.services.handoff_contract import build
from threaddesk.services.thread_management import ID

MAX_FILES = 32
MAX_FILE_BYTES = 1024 * 1024
MAX_TOTAL_BYTES = 4 * 1024 * 1024


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode()
    ).hexdigest()


def source_roots():
    try:
        configured = json.loads(os.environ.get("THREADDESK_SOURCE_ROOTS", "[]"))
        if (
            not isinstance(configured, list)
            or len(configured) > 16
            or any(
                not isinstance(item, str) or not Path(item).is_absolute()
                for item in configured
            )
        ):
            raise ValueError()
        return tuple(Path(item).resolve(strict=True) for item in configured)
    except (ValueError, OSError) as exc:
        raise ManagementError(
            "source_configuration",
            "THREADDESK_SOURCE_ROOTS muss eine begrenzte Liste vorhandener absoluter Operatorpfade sein.",
        ) from exc


def _read_reference(reference, roots, max_bytes=MAX_FILE_BYTES):
    """Hash one regular file below a configured root without following symlinks."""
    if not roots:
        return {
            "reference": reference,
            "verification": "unsupported",
            "reason": "source_roots_not_configured",
        }, 0
    if (
        not hasattr(os, "O_NOFOLLOW")
        or not hasattr(os, "O_DIRECTORY")
        or os.open not in os.supports_dir_fd
    ):
        return {
            "reference": reference,
            "verification": "unsupported",
            "reason": "nofollow_unavailable",
        }, 0
    candidate = Path(reference)
    if ".." in candidate.parts:
        return {
            "reference": reference,
            "verification": "unsupported",
            "reason": "source_outside_scope",
        }, 0
    choices = []
    for root in roots:
        path = candidate if candidate.is_absolute() else root / candidate
        if path.is_relative_to(root):
            choices.append((root, path.relative_to(root)))
    if len(choices) != 1:
        return {
            "reference": reference,
            "verification": "unsupported",
            "reason": "source_ambiguous_or_outside_scope",
        }, 0
    root, relative = choices[0]
    descriptors = []
    try:
        descriptors.append(os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW))
        for part in relative.parts[:-1]:
            descriptors.append(
                os.open(
                    part,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                    dir_fd=descriptors[-1],
                )
            )
        if not relative.parts:
            raise OSError("not a file")
        descriptor = os.open(
            relative.parts[-1],
            os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
            dir_fd=descriptors[-1],
        )
        descriptors.append(descriptor)
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_size > max_bytes:
            raise OSError("not a bounded regular file")
        body = bytearray()
        while len(body) <= max_bytes:
            chunk = os.read(descriptor, min(65536, max_bytes + 1 - len(body)))
            if not chunk:
                break
            body.extend(chunk)
        after = os.fstat(descriptor)
        if len(body) > max_bytes or (
            before.st_size,
            before.st_mtime_ns,
            before.st_ino,
        ) != (after.st_size, after.st_mtime_ns, after.st_ino):
            raise OSError("source changed or exceeded limit")
        return {
            "reference": reference,
            "verification": "verified",
            "sha256": hashlib.sha256(body).hexdigest(),
            "size": len(body),
            "root_ref": hashlib.sha256(str(root).encode()).hexdigest(),
        }, len(body)
    except OSError:
        return {
            "reference": reference,
            "verification": "unverified",
            "reason": "source_unreadable_unsafe_or_over_limit",
        }, 0
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def capture_sources(files, roots):
    values, total = [], 0
    for index, reference in enumerate(files[:MAX_FILES]):
        if index >= MAX_FILES or total >= MAX_TOTAL_BYTES:
            values.append(
                {
                    "reference": reference,
                    "verification": "unsupported",
                    "reason": "source_count_or_total_limit",
                }
            )
            continue
        item, size = _read_reference(
            reference, roots, min(MAX_FILE_BYTES, MAX_TOTAL_BYTES - total)
        )
        if total + size > MAX_TOTAL_BYTES:
            item = {
                "reference": reference,
                "verification": "unsupported",
                "reason": "source_total_limit",
            }
        else:
            total += size
        values.append(item)
    if len(files) > MAX_FILES:
        values.append(
            {
                "reference": "<omitted>",
                "verification": "unsupported",
                "reason": "source_count_limit",
                "omitted_count": len(files) - MAX_FILES,
            }
        )
    return values


class IssuedHandoffs:
    def __init__(self, svc):
        self.svc, self.store = svc, svc.store
        self.roots = source_roots()

    def register(self, payload, thread, *, operation_id=None, request_hash=None):
        snapshot = Snapshot(
            new_id(),
            thread.id,
            now_iso(),
            "issued-handoff:" + payload["handoff_id"],
            ThreadContext.from_dict(thread.context.to_dict()),
        )
        self.store.save_snapshot(snapshot)
        source = {
            "thread_revision": thread.revision,
            "snapshot_id": snapshot.id,
            "content_hash": digest(thread.to_dict()),
            "source_refs": capture_sources(thread.context.files, self.roots),
        }
        payload = {**payload, "source": source}
        record = {
            "handoff": payload,
            "content_hash": digest(payload),
            "source": source,
            "operation_id": operation_id,
            "request_hash": request_hash,
            "binding": None,
            "issued_at": now_iso(),
        }
        self.store.save_issued_handoff(payload["handoff_id"], record)
        return record

    def get(self, *, handoff_id=None, operation_id=None):
        if (handoff_id is None) == (operation_id is None):
            raise ManagementError(
                "validation_error",
                "Genau handoff_id oder operation_id ist erforderlich.",
            )
        identity = handoff_id if handoff_id is not None else operation_id
        if not isinstance(identity, str) or not ID.fullmatch(identity):
            raise ManagementError("validation_error", "Ungültige Übergabekennung.")
        if handoff_id is not None:
            return self.store.get_issued_handoff(handoff_id)
        return next(
            (
                item
                for item in self.store.list_issued_handoffs()
                if item.get("operation_id") == operation_id
            ),
            None,
        )

    def issue(self, args):
        if set(args) - {"operation_id", "id", "expected_revision", "target"} or not {
            "operation_id",
            "id",
            "expected_revision",
        } <= set(args):
            raise ManagementError("validation_error", "Ungültige Übergabeanfrage.")
        if (
            any(
                not isinstance(args[key], str) or not ID.fullmatch(args[key])
                for key in ("operation_id", "id")
            )
            or type(args["expected_revision"]) is not int
        ):
            raise ManagementError(
                "validation_error",
                "Exakte IDs und erwartete Threadrevision sind erforderlich.",
            )
        target = args.get("target", "generic")
        if target not in ("generic", "grok", "codex", "claude", "gnom-hub-v1"):
            raise ManagementError("validation_error", "Unbekanntes Zielsystem.")
        request_hash = digest({**args, "target": target})
        with self.store.transaction():
            existing = self.get(operation_id=args["operation_id"])
            if existing:
                if existing["request_hash"] != request_hash:
                    raise ManagementError(
                        "operation_conflict",
                        "Übergabekennung wurde mit anderem Auftrag verwendet.",
                    )
                return {
                    **existing["handoff"],
                    "duplicate": True,
                    "content_hash": existing["content_hash"],
                }
            thread = self.store.get_thread(args["id"])
            if thread.revision != args["expected_revision"]:
                raise ManagementError(
                    "revision_conflict",
                    "Thread wurde zwischenzeitlich geändert.",
                    expected_revision=args["expected_revision"],
                    actual_revision=thread.revision,
                )
            self.svc._admit("handoff", thread.id)
            payload = build(thread, target_system=target)
            record = self.register(
                payload,
                thread,
                operation_id=args["operation_id"],
                request_hash=request_hash,
            )
        self.svc._record("handoff", thread.id)
        return {
            **record["handoff"],
            "duplicate": False,
            "content_hash": record["content_hash"],
        }

    def bind(self, args):
        required = {
            "handoff_id",
            "handoff_revision",
            "task_id",
            "bridge_task_id",
            "run_id",
            "worker",
            "expected_thread_revision",
            "principal_ref",
            "operator_scope",
            "request_hash",
        }
        optional = {"parent_task_id", "subtask_id", "session_id", "actor_claim"}
        if set(args) - required - optional or not required <= set(args):
            raise ManagementError(
                "validation_error", "Unvollständige oder unbekannte Laufbindung."
            )
        if any(
            not isinstance(args[key], str)
            or not args[key].strip()
            or len(args[key]) > 512
            for key in (required - {"handoff_revision", "expected_thread_revision"})
            | (set(args) & optional)
        ):
            raise ManagementError("validation_error", "Ungültige Laufkennung.")
        if any(
            type(args[key]) is not int
            for key in ("handoff_revision", "expected_thread_revision")
        ):
            raise ManagementError("validation_error", "Ungültige Revision.")
        if not re.fullmatch(r"[a-f0-9]{64}", args["request_hash"]):
            raise ManagementError(
                "validation_error", "request_hash muss ein SHA256-Fingerabdruck sein."
            )
        reject_secrets(json.dumps(args, ensure_ascii=False))
        with self.store.transaction():
            record = self.get(handoff_id=args["handoff_id"])
            if record is None:
                raise ManagementError(
                    "not_found", "Übergabe wurde hier nicht ausgestellt."
                )
            handoff = record["handoff"]
            if (
                args["handoff_revision"] != handoff["revision"]
                or args["task_id"] != handoff["task_id"]
                or args["expected_thread_revision"]
                != record["source"]["thread_revision"]
            ):
                raise ManagementError(
                    "binding_conflict", "Übergabe-/Quellzuordnung stimmt nicht überein."
                )
            if record["binding"] is not None:
                if record["binding"] != args:
                    raise ManagementError(
                        "binding_conflict",
                        "Übergabe ist bereits an einen anderen Lauf gebunden.",
                    )
                return {"binding": record["binding"], "duplicate": True}
            current = self.store.get_thread(handoff["thread_id"])
            if current.revision != record["source"]["thread_revision"]:
                raise ManagementError(
                    "revision_conflict",
                    "Auftragsgrundlage hat sich vor Laufbindung geändert.",
                )
            record["binding"] = dict(args)
            self.store.save_issued_handoff(handoff["handoff_id"], record)
            return {"binding": record["binding"], "duplicate": False}

    def check_return(self, payload, *, strict=False):
        if not ID.fullmatch(payload["handoff_id"]):
            if strict:
                raise ManagementError(
                    "unissued_handoff",
                    "Rückgabe gehört zu keiner hier ausgestellten Übergabe.",
                )
            return {
                "binding_status": "legacy_unbound",
                "source_verification": "unknown",
            }
        record = self.get(handoff_id=payload["handoff_id"])
        if record is None:
            if strict:
                raise ManagementError(
                    "unissued_handoff",
                    "Rückgabe gehört zu keiner hier ausgestellten Übergabe.",
                )
            return {
                "binding_status": "legacy_unbound",
                "source_verification": "unknown",
            }
        handoff, binding = record["handoff"], record["binding"]
        if binding is None and strict:
            raise ManagementError(
                "unbound_run",
                "Noch kein angenommener Lauf ist an diese Übergabe gebunden.",
            )
        if any(
            payload[key] != expected
            for key, expected in {
                "handoff_revision": handoff["revision"],
                "thread_id": handoff["thread_id"],
                "task_id": handoff["task_id"],
                **(
                    {"run_id": binding["run_id"], "worker": binding["worker"]}
                    if binding
                    else {}
                ),
            }.items()
        ):
            raise ManagementError(
                "return_binding_conflict",
                "Rückgabe gehört zu einem anderen Auftrag oder Lauf.",
            )
        current = self.store.get_thread(handoff["thread_id"])
        if (
            current.revision != record["source"]["thread_revision"]
            or digest(current.to_dict()) != record["source"]["content_hash"]
        ):
            raise ManagementError(
                "return_stale", "Auftragsgrundlage wurde seit der Übergabe geändert."
            )
        current_sources = capture_sources(current.context.files, self.roots)
        for issued, actual in zip(record["source"]["source_refs"], current_sources):
            if issued["verification"] == "verified" and actual != issued:
                raise ManagementError(
                    "return_stale_source",
                    "Gebundener Dateiinhalt hat sich geändert oder ist nicht mehr prüfbar.",
                )
        if binding is None:
            return {
                "binding_status": "issued_unbound",
                "source_verification": "unknown",
            }
        return {
            "binding_status": "issued_bound",
            "source_verification": "verified"
            if all(item["verification"] == "verified" for item in current_sources)
            else "partial_unverified",
            "bridge_task_id": binding["bridge_task_id"],
            "principal_ref": binding["principal_ref"],
            "operator_scope": binding["operator_scope"],
        }

    def question(self, args, *, answering=False):
        required = {"handoff_id", "handoff_revision", "run_id", "question_id", "text"}
        if answering:
            required.add("answer_id")
        if (
            set(args) != required
            or any(
                not isinstance(args.get(key), str) or not args[key].strip()
                for key in required - {"handoff_revision"}
            )
            or type(args.get("handoff_revision")) is not int
        ):
            raise ManagementError(
                "validation_error", "Ungültige zugeordnete Frage oder Antwort."
            )
        if (
            not ID.fullmatch(args["question_id"])
            or (answering and not ID.fullmatch(args["answer_id"]))
            or len(args["text"]) > 10000
        ):
            raise ManagementError(
                "validation_error", "Frage-/Antwortkennung oder Textlänge ist ungültig."
            )
        reject_secrets(args["text"])
        with self.store.transaction():
            record = self.get(handoff_id=args["handoff_id"])
            if record is None or record["binding"] is None:
                raise ManagementError(
                    "unbound_run", "Frage gehört zu keinem gebundenen Lauf."
                )
            if (
                args["handoff_revision"] != record["handoff"]["revision"]
                or args["run_id"] != record["binding"]["run_id"]
            ):
                raise ManagementError(
                    "binding_conflict", "Frage-/Antwortbezug stimmt nicht überein."
                )
            questions = record.setdefault("questions", [])
            existing = next(
                (
                    item
                    for item in questions
                    if item["question_id"] == args["question_id"]
                ),
                None,
            )
            if not answering and existing is not None:
                if existing["text"] != args["text"]:
                    raise ManagementError(
                        "question_conflict", "Fragekennung hat bereits anderen Inhalt."
                    )
                return {"question": existing, "duplicate": True}
            if (
                answering
                and existing is not None
                and existing.get("answer") is not None
            ):
                answer = existing["answer"]
                if (
                    answer["answer_id"] != args["answer_id"]
                    or answer["text"] != args["text"]
                ):
                    raise ManagementError(
                        "answer_conflict", "Frage wurde bereits anders beantwortet."
                    )
                return {
                    "question": existing,
                    "duplicate": True,
                    "delivery_status": "recorded_for_run",
                }
            current = self.store.get_thread(record["handoff"]["thread_id"])
            if current.revision != record["source"]["thread_revision"]:
                raise ManagementError(
                    "return_stale",
                    "Auftragsgrundlage wurde seit der Übergabe geändert.",
                )
            if answering:
                if existing is None or existing["status"] != "awaiting_answer":
                    raise ManagementError(
                        "question_not_waiting",
                        "Keine passende wartende Frage vorhanden.",
                    )
                existing["answer"] = {
                    "answer_id": args["answer_id"],
                    "text": args["text"],
                    "recorded_at": now_iso(),
                }
                existing["status"] = "answer_recorded"
                item = existing
            else:
                if len(questions) >= 100:
                    raise ManagementError(
                        "question_limit", "Grenze von 100 Fragen je Übergabe erreicht."
                    )
                item = {
                    "question_id": args["question_id"],
                    "run_id": args["run_id"],
                    "handoff_revision": args["handoff_revision"],
                    "text": args["text"],
                    "status": "awaiting_answer",
                    "answer": None,
                    "recorded_at": now_iso(),
                }
                questions.append(item)
            self.store.save_issued_handoff(args["handoff_id"], record)
            from threaddesk.services.whiteboard import append

            append(
                self.store,
                record["handoff"]["thread_id"],
                actor="Mensch" if answering else record["binding"]["worker"],
                actor_type="human" if answering else "system",
                entry_type="note" if answering else "question",
                content=args["text"],
                task_id=record["handoff"]["task_id"],
                handoff_id=args["handoff_id"],
                run_id=args["run_id"],
                external_key=f"handoff:{args['handoff_id']}:{'answer:' + args['answer_id'] if answering else 'question:' + args['question_id']}",
                metadata={
                    "question_id": args["question_id"],
                    "binding_status": "issued_bound",
                    "adapter_delivery_verified": False,
                },
            )
            return {
                "question": item,
                "duplicate": False,
                "delivery_status": "recorded_for_run"
                if answering
                else "awaiting_answer",
            }
