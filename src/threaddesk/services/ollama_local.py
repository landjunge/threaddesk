"""Talk only to a local Ollama. Never pull a model and never leave the machine."""

from __future__ import annotations

import json
from typing import Any, Callable
from urllib import error, request

from threaddesk.core.errors import InvalidState

HOST = "http://127.0.0.1:11434"
PATHS = frozenset({"/api/tags", "/api/chat"})
Transport = Callable[..., dict[str, Any]]


class OllamaError(InvalidState):
    pass


def local_url(path: str) -> str:
    if path not in PATHS:
        raise OllamaError("ollama_forbidden")
    return HOST + path


def default_transport(url: str, body: dict[str, Any] | None = None, timeout: float = 2.0) -> dict[str, Any]:
    if not url.startswith(HOST + "/"):
        raise OllamaError("ollama_forbidden")
    data = None if body is None else json.dumps(body).encode("utf-8")
    call = request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"} if data else {},
        method="POST" if data is not None else "GET",
    )
    try:
        with request.urlopen(call, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except (error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        raise OllamaError("ollama_unavailable") from exc


def list_models(transport: Transport | None = None, timeout: float = 0.4) -> list[str]:
    call = transport or default_transport
    payload = call(local_url("/api/tags"), None, timeout)
    names = []
    for item in payload.get("models") or []:
        name = item.get("name") if isinstance(item, dict) else None
        if isinstance(name, str) and name.strip():
            names.append(name.strip())
    return names


def complete(model: str, prompt: str, transport: Transport | None = None, timeout: float = 90.0) -> str:
    call = transport or default_transport
    payload = call(
        local_url("/api/chat"),
        {"model": model, "stream": False, "messages": [{"role": "user", "content": prompt}]},
        timeout,
    )
    message = payload.get("message") if isinstance(payload, dict) else None
    text = message.get("content") if isinstance(message, dict) else ""
    if not isinstance(text, str) or not text.strip():
        raise OllamaError("ollama_empty")
    return text.strip()
