from __future__ import annotations

from threaddesk.core.errors import InvalidState, NotFound
from threaddesk.core.events import EventBus
from threaddesk.core.models import STATUSES, Snapshot, Thread, ThreadContext, new_id, new_thread, now_iso
from threaddesk.core.secrets import reject_secrets
from threaddesk.services.prompt_generator import generate as generate_prompt
from threaddesk.storage.json_store import JsonStore


class ThreadService:
    def __init__(self, store: JsonStore | None = None, bus: EventBus | None = None) -> None:
        self.store = store or JsonStore()
        self.bus = bus or EventBus()

    def create(self, title: str, description: str = "") -> Thread:
        title = reject_secrets(title).strip()
        description = reject_secrets(description)
        if not title:
            raise InvalidState("Titel fehlt.")
        thread = new_thread(title, description)
        self.store.save_thread(thread)
        self.store.set_current_id(thread.id)
        self.bus.emit("thread.created", {"id": thread.id})
        self.bus.emit("thread.switched", {"id": thread.id})
        return thread

    def list(self, include_archived: bool = False) -> list[Thread]:
        return self.store.list_threads(include_archived=include_archived)

    def get(self, key: str) -> Thread:
        return self.store.get_thread(self._resolve(key))

    def current(self) -> Thread | None:
        cid = self.store.get_current_id()
        if not cid:
            return None
        try:
            return self.store.get_thread(cid)
        except NotFound:
            return None

    def switch(self, key: str) -> Thread:
        thread = self.get(key)
        self.store.set_current_id(thread.id)
        self.bus.emit("thread.switched", {"id": thread.id})
        return thread

    def rename(self, key: str, title: str) -> Thread:
        title = reject_secrets(title).strip()
        if not title:
            raise InvalidState("Titel fehlt.")
        thread = self.get(key)
        thread.title = title
        thread.updated_at = now_iso()
        self.store.save_thread(thread)
        self.bus.emit("thread.renamed", {"id": thread.id})
        return thread

    def _target(self, key: str | None = None) -> Thread:
        thread = self.get(key) if key else self.current()
        if thread is None:
            raise InvalidState("Kein aktiver Thread. td switch <id>")
        return thread

    def set_note(self, text: str, key: str | None = None, append: bool = False) -> Thread:
        reject_secrets(text)
        thread = self._target(key)
        if append and thread.context.notes:
            thread.context.notes = thread.context.notes.rstrip() + "\n" + text
        else:
            thread.context.notes = text
        thread.updated_at = now_iso()
        self.store.save_thread(thread)
        self.bus.emit("thread.updated", {"id": thread.id})
        return thread

    def set_description(self, text: str, key: str | None = None) -> Thread:
        reject_secrets(text)
        thread = self._target(key)
        thread.description = text.strip()
        thread.updated_at = now_iso()
        self.store.save_thread(thread)
        self.bus.emit("thread.updated", {"id": thread.id})
        return thread

    def set_status(self, status: str, key: str | None = None) -> Thread:
        status = status.strip().lower()
        if status == "archived":
            raise InvalidState("Zum Archivieren: td archive")
        if status not in STATUSES:
            raise InvalidState(f"Status muss einer von {', '.join(STATUSES)} sein.")
        thread = self._target(key)
        if thread.status == "archived":
            raise InvalidState("Archivierter Thread: erst td unarchive.")
        thread.status = status
        thread.updated_at = now_iso()
        self.store.save_thread(thread)
        self.bus.emit("thread.updated", {"id": thread.id})
        return thread

    def add_file(self, path: str, key: str | None = None) -> Thread:
        reject_secrets(path)
        path = path.strip()
        if not path:
            raise InvalidState("Pfad fehlt.")
        thread = self._target(key)
        if path not in thread.context.files:
            thread.context.files.append(path)
        thread.updated_at = now_iso()
        self.store.save_thread(thread)
        self.bus.emit("thread.updated", {"id": thread.id})
        return thread

    def remove_file(self, path: str, key: str | None = None) -> Thread:
        thread = self._target(key)
        thread.context.files = [p for p in thread.context.files if p != path]
        thread.updated_at = now_iso()
        self.store.save_thread(thread)
        self.bus.emit("thread.updated", {"id": thread.id})
        return thread

    def archive(self, key: str) -> Thread:
        thread = self.get(key)
        thread.status = "archived"
        thread.updated_at = now_iso()
        self.store.save_thread(thread)
        if self.store.get_current_id() == thread.id:
            self.store.set_current_id(None)
        self.bus.emit("thread.archived", {"id": thread.id})
        return thread

    def unarchive(self, key: str) -> Thread:
        thread = self.get(key)
        if thread.status != "archived":
            raise InvalidState("Thread ist nicht archiviert.")
        thread.status = "paused"
        thread.updated_at = now_iso()
        self.store.save_thread(thread)
        self.bus.emit("thread.updated", {"id": thread.id})
        return thread

    def delete(self, key: str) -> None:
        thread = self.get(key)
        if thread.status != "archived":
            raise InvalidState("Nur archivierte Threads löschen (erst td archive).")
        self.store.delete_thread(thread.id)
        if self.store.get_current_id() == thread.id:
            self.store.set_current_id(None)
        self.bus.emit("thread.deleted", {"id": thread.id})

    def snapshot(self, label: str = "", key: str | None = None) -> Snapshot:
        reject_secrets(label)
        thread = self.get(key) if key else self.current()
        if thread is None:
            raise InvalidState("Kein aktiver Thread.")
        snap = Snapshot(
            id=new_id(),
            thread_id=thread.id,
            created_at=now_iso(),
            label=label.strip(),
            context=ThreadContext.from_dict(thread.context.to_dict()),
        )
        self.store.save_snapshot(snap)
        thread.current_snapshot_id = snap.id
        thread.updated_at = now_iso()
        self.store.save_thread(thread)
        self.bus.emit("snapshot.saved", {"id": snap.id, "thread_id": thread.id})
        return snap

    def snapshots(self, key: str | None = None) -> list[Snapshot]:
        thread = self.get(key) if key else self.current()
        if thread is None:
            raise InvalidState("Kein aktiver Thread.")
        return self.store.list_snapshots(thread.id)

    def prompt(
        self,
        target: str = "grok",
        variant: str = "detailed",
        key: str | None = None,
        save: bool = False,
    ) -> str:
        thread = self._target(key)
        text = generate_prompt(thread, target=target, variant=variant)
        reject_secrets(text)
        if save:
            thread.context.prompts.append(
                {
                    "id": new_id(),
                    "created_at": now_iso(),
                    "target": target,
                    "variant": variant,
                    "text": text,
                }
            )
            thread.updated_at = now_iso()
            self.store.save_thread(thread)
            self.bus.emit("prompt.saved", {"thread_id": thread.id, "target": target})
        return text

    def prompts(self, key: str | None = None) -> list[dict]:
        return list(self._target(key).context.prompts)

    def restore(self, snap_id: str) -> Thread:
        snap = self.store.get_snapshot(snap_id)
        thread = self.store.get_thread(snap.thread_id)
        thread.context = ThreadContext.from_dict(snap.context.to_dict())
        thread.current_snapshot_id = snap.id
        thread.updated_at = now_iso()
        self.store.save_thread(thread)
        self.store.set_current_id(thread.id)
        self.bus.emit("snapshot.loaded", {"id": snap.id, "thread_id": thread.id})
        self.bus.emit("thread.switched", {"id": thread.id})
        return thread

    def _resolve(self, key: str) -> str:
        key = (key or "").strip()
        if not key:
            raise NotFound("Thread-ID fehlt.")
        if key.isdigit():
            rows = self.list(include_archived=False)
            idx = int(key)
            if 1 <= idx <= len(rows):
                return rows[idx - 1].id
        try:
            self.store.get_thread(key)
            return key
        except NotFound:
            pass
        all_threads = self.store.list_threads(include_archived=True)
        by_id = [t for t in all_threads if t.id.startswith(key)]
        if len(by_id) == 1:
            return by_id[0].id
        needle = key.lower()
        by_title = [t for t in all_threads if needle in t.title.lower()]
        if len(by_title) == 1:
            return by_title[0].id
        if not by_id and not by_title:
            raise NotFound(f"Thread nicht gefunden: {key}")
        hits = by_id or by_title
        raise InvalidState(
            "Mehrdeutig: " + ", ".join(f"{t.id} ({t.title})" for t in hits)
        )
