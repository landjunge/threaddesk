from __future__ import annotations

import re

from threaddesk.core.errors import SecretRejected

# Reject obvious key material so it never lands in thread files.
_SECRET = re.compile(
    r"(?i)(api[_-]?key|secret|password|token|bearer)\s*[:=]\s*\S+"
    r"|sk-[A-Za-z0-9]{16,}"
    r"|ghp_[A-Za-z0-9]{20,}"
)


def reject_secrets(text: str) -> str:
    if text and _SECRET.search(text):
        raise SecretRejected("Keine API-Keys oder Passwörter in Thread-Dateien.")
    return text
