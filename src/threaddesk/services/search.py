"""Optional, trusted-local search. No HTTP, Room, module or team registration."""
from __future__ import annotations

from collections import OrderedDict
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
from time import monotonic
from uuid import uuid4

from threaddesk.core.search import CALL_BYTES, CANDIDATES, FIELDS, RECORD_BYTES, SearchError, SearchHit, SearchPage
from threaddesk.storage.search_source import identifier, projection_digest


class LocalFileOwnerPolicy:
    """Explicit local entrypoint assumption, never authenticated team identity.

    A transport/module must not construct this policy from caller input. Future
    authority adapters must supply fresh authorization and an opaque generation.
    """
    def __init__(self, workspace):
        self.workspace = Path(workspace).resolve()
        self._generation = uuid4().hex

    def authorize(self, workspace):
        if not os.path.samefile(workspace, self.workspace):
            raise SearchError("authority_unavailable")
        if hasattr(os, "getuid") and self.workspace.stat().st_uid != os.getuid():
            raise SearchError("authority_unavailable")

    def generation(self):
        info = self.workspace.stat()
        return self._generation + ":%s:%s" % (info.st_dev, info.st_ino)

    def can_read_current(self, document):
        return True


class SearchService:
    def __init__(self, store, policy=None):
        self.store, self.policy = store, policy
        factory = getattr(store, "search_adapter", None)
        self.adapter = factory() if callable(factory) else None
        self._cursors = OrderedDict()

    def _authorize(self):
        if self.policy is None:
            raise SearchError("authority_unavailable")
        try:
            self.policy.authorize(self.store.workspace_path)
            generation = self.policy.generation()
            if not isinstance(generation, str) or not 1 <= len(generation) <= 256:
                raise SearchError("authority_unavailable")
            return generation
        except Exception as exc:
            raise SearchError("authority_unavailable") from exc

    def status(self):
        self._authorize()
        return self.adapter.state() if self.adapter else {"enabled": False, "status": "unsupported"}

    def set_enabled(self, enabled):
        self._authorize()
        if type(enabled) is not bool or self.adapter is None:
            raise SearchError("invalid_search_configuration")
        self._discard_all()
        return self.adapter.configure(enabled)

    def rebuild_batch(self):
        self._authorize()
        if self.adapter is None:
            raise SearchError("unsupported")
        self._discard_all()
        return self.adapter.rebuild()

    def _discard_all(self):
        while self._cursors:
            _, state = self._cursors.popitem(last=False)
            state["iterator"].close()

    def close(self):
        self._discard_all()
        close = getattr(self.adapter, "close", None)
        if close:
            close()

    def _keep(self, state):
        token = uuid4().hex
        self._cursors[token] = state
        while len(self._cursors) > 128:
            _, old = self._cursors.popitem(last=False)
            old["iterator"].close()
        return token

    def search(self, text, *, limit=20, cursor=None, project_id=None, include_archived=False):
        policy_generation = self._authorize()
        try:
            text_size = len(text.encode("utf-8")) if isinstance(text, str) else 513
        except UnicodeError:
            raise SearchError("invalid_search_query")
        if (not isinstance(text, str) or not text.strip() or text_size > 512
                or any(ord(ch) < 32 or 127 <= ord(ch) <= 159 for ch in text)
                or type(limit) is not int or not 1 <= limit <= 100
                or type(include_archived) is not bool):
            raise SearchError("invalid_search_query")
        if cursor is not None and (not isinstance(cursor, str) or len(cursor) > 64):
            raise SearchError("cursor_expired")
        terms = text.split()
        if len(terms) > 16:
            raise SearchError("invalid_search_query")
        if project_id is not None:
            identifier(project_id)
        signature = hashlib.sha256(json.dumps([terms, project_id, include_archived, limit]).encode()).hexdigest()
        now = monotonic()
        for key in list(self._cursors):
            if now - self._cursors[key]["created"] > 300:
                self._cursors.pop(key)["iterator"].close()
        source = self.status()
        if not source.get("enabled"):
            if cursor:
                self._discard_all()
                raise SearchError("generation_changed")
            return SearchPage(mode=source["status"], reasons=[source.get("reason", source["status"])])
        mode = source.get("mode", "bounded_scan")
        if cursor is not None:
            state = self._cursors.pop(cursor, None) if isinstance(cursor, str) else None
            if state is None:
                raise SearchError("cursor_expired")
            if (state["signature"], state["generation"], state["policy"], state["source_mode"]) != (
                    signature, source["generation"], policy_generation, mode):
                state["iterator"].close()
                raise SearchError("generation_changed")
        else:
            state = {"signature": signature, "generation": source["generation"],
                     "policy": policy_generation, "created": now, "mode": mode, "source_mode": mode,
                     "iterator": self.adapter.candidates(terms, project_id, include_archived,
                                                         indexed=mode == "fts5")}
        mode = state["mode"]
        page = SearchPage(mode=mode, generation=source["generation"],
                          match_semantics="FTS5 literal AND tokens, verified current field" if mode == "fts5"
                          else "literal AND case-insensitive substrings; one field hit per thread")
        iterator, exhausted = state["iterator"], False
        deadline = now + 0.1
        try:
            while len(page.hits) < limit and page.scanned < CANDIDATES and page.source_bytes <= CALL_BYTES - RECORD_BYTES - 16384:
                if monotonic() > deadline:
                    page.reasons.append("time_budget")
                    break
                start = monotonic()
                try:
                    exact_id, selected_field = next(iterator)
                except StopIteration:
                    exhausted = True
                    break
                except sqlite3.Error:
                    if cursor:
                        raise SearchError("index_changed")
                    iterator.close()
                    state["iterator"] = iterator = self.adapter.candidates(terms, project_id, include_archived, indexed=False)
                    page.mode = state["mode"] = "bounded_scan"
                    page.match_semantics = "literal AND case-insensitive substrings; one field hit per thread"
                    page.reasons.append("fts_unavailable")
                    continue
                finally:
                    page.kernel_seconds += monotonic() - start
                if exact_id is None:
                    page.reasons.append(selected_field)
                    break
                page.scanned += 1
                try:
                    doc = self.adapter.read(exact_id)
                    page.source_bytes += doc.source_bytes
                except Exception:
                    # Parsing/validation can fail after a full bounded read.
                    # Reserve its worst-case source cost, not zero bytes.
                    page.source_bytes += RECORD_BYTES + 16384
                    page.reasons.append("source_unreadable_or_over_limit")
                    continue
                if (not include_archived and doc.status == "archived") or (project_id is not None and doc.project_id != project_id):
                    continue
                if self._authorize() != policy_generation:
                    raise SearchError("generation_changed")
                try:
                    allowed = self.policy.can_read_current(doc)
                except Exception as exc:
                    raise SearchError("authority_unavailable") from exc
                if allowed is not True:
                    continue
                for name in (selected_field,) if selected_field else FIELDS:
                    value = getattr(doc, name)
                    matches = [re.search(re.escape(term), value, re.IGNORECASE) for term in terms]
                    if all(matches):
                        begin, end = matches[0].span()
                        page.hits.append(SearchHit(doc.thread_id, doc.revision, name, begin, end,
                                                  doc.title[:240], value[max(0, begin - 60):max(0, begin - 60) + 240],
                                                  projection_digest(doc)))
                        break
            current_source = self.status()
            source_key = lambda value: (value.get("generation"), value.get("enabled"),
                                        value.get("mode", "bounded_scan"))
            if self._authorize() != policy_generation or source_key(current_source) != source_key(source):
                raise SearchError("generation_changed")
            if page.scanned >= CANDIDATES:
                page.reasons.append("candidate_budget")
            if page.source_bytes > CALL_BYTES - RECORD_BYTES - 16384:
                page.reasons.append("byte_budget")
            if not self.adapter.managed_generation:
                page.reasons.append("json_external_writers_unverified")
            page.complete = exhausted and not page.reasons
            page.truncated = not page.complete
            page.reasons = sorted(set(page.reasons))
            if not exhausted:
                page.next_cursor = self._keep(state)
            else:
                iterator.close()
            return page
        except Exception:
            iterator.close()
            raise

    def resolve(self, hit):
        """Navigate to the original field only if its current revision still matches."""
        policy_generation = self._authorize()
        if hit.field not in FIELDS:
            raise SearchError("invalid_search_target")
        doc = self.adapter.read(hit.thread_id)
        try:
            allowed = self.policy.can_read_current(doc)
        except Exception as exc:
            raise SearchError("authority_unavailable") from exc
        if allowed is not True or self._authorize() != policy_generation:
            raise SearchError("authority_unavailable")
        if doc.revision != hit.thread_revision or projection_digest(doc) != hit.source_digest:
            raise SearchError("revision_changed")
        return getattr(doc, hit.field)
