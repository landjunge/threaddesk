from __future__ import annotations

from collections import defaultdict
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
import logging
from typing import Any, Callable

Listener = Callable[[str, dict[str, Any]], None]
logger = logging.getLogger(__name__)


class EventBus:
    def __init__(self) -> None:
        self._listeners: dict[str, list[Listener]] = defaultdict(list)
        self._pending: ContextVar[list | None] = ContextVar(
            "threaddesk_pending_events", default=None
        )

    def on(self, name: str, fn: Listener) -> None:
        self._listeners[name].append(fn)

    def emit(self, name: str, payload: dict[str, Any] | None = None) -> None:
        data = payload or {}
        pending = self._pending.get()
        if pending is not None:
            pending.append((name, deepcopy(data)))
            return
        self._deliver(name, data)

    def _deliver(self, name: str, data: dict[str, Any], *, committed=False) -> None:
        for fn in [*self._listeners.get(name, []), *self._listeners.get("*", [])]:
            try:
                fn(name, data)
            except Exception:
                if not committed:
                    raise
                # Persistence already succeeded. A subscriber failure cannot
                # undo it, nor prevent the remaining subscribers being notified.
                logger.exception("Event listener failed after commit: %s", name)

    @contextmanager
    def defer_until_commit(self):
        """Publish only after the enclosed storage transaction exits normally.

        Use as ``with bus.defer_until_commit(), store.transaction():`` so the
        store commits before this context publishes. Nested scopes merge on
        success and discard their own events on failure. This is an in-memory
        notification boundary, not a durable delivery/outbox guarantee.
        """
        parent = self._pending.get()
        pending: list[tuple[str, dict[str, Any]]] = []
        token = self._pending.set(pending)
        try:
            yield
        finally:
            self._pending.reset(token)
        if parent is not None:
            parent.extend(pending)
        else:
            for name, data in pending:
                self._deliver(name, data, committed=True)
