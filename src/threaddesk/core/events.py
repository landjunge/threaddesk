from __future__ import annotations

from collections import defaultdict
from typing import Any, Callable

Listener = Callable[[str, dict[str, Any]], None]


class EventBus:
    def __init__(self) -> None:
        self._listeners: dict[str, list[Listener]] = defaultdict(list)

    def on(self, name: str, fn: Listener) -> None:
        self._listeners[name].append(fn)

    def emit(self, name: str, payload: dict[str, Any] | None = None) -> None:
        data = payload or {}
        for fn in list(self._listeners.get(name, [])):
            fn(name, data)
        for fn in list(self._listeners.get("*", [])):
            fn(name, data)
