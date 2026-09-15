"""First extracted thread read service behind the compatibility facade."""

from __future__ import annotations

from threaddesk.core.errors import NotFound
from threaddesk.core.models import Thread
from threaddesk.storage.protocols import ThreadStore


class ThreadReader:
    def __init__(self, store: ThreadStore) -> None:
        self.store = store

    def list(self, include_archived: bool = False) -> list[Thread]:
        return self.store.list_threads(include_archived=include_archived)

    def current(self) -> Thread | None:
        current_id = self.store.get_current_id()
        if not current_id:
            return None
        try:
            return self.store.get_thread(current_id)
        except NotFound:
            return None
