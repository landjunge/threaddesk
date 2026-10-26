"""Bounded text transforms. HTML is text, never an active preview."""

from __future__ import annotations

import re
from html.parser import HTMLParser


def decode(raw: bytes) -> str:
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16", errors="replace")
    return raw.decode("utf-8-sig", errors="replace")


class _HTMLText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.values = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden += 1

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, value):
        if not self.hidden:
            self.values.append(value)


def html_text(raw: bytes) -> str:
    parser = _HTMLText()
    parser.feed(decode(raw))
    return " ".join(parser.values)


def rtf_text(raw: bytes) -> str:
    text = decode(raw)
    text = re.sub(
        r"\\'([0-9a-fA-F]{2})",
        lambda m: bytes([int(m[1], 16)]).decode("cp1252", errors="replace"),
        text,
    )
    text = re.sub(r"\\u(-?\d+)\??", lambda m: chr(int(m[1]) % 65536), text)
    text = re.sub(r"\\(?:par|line|tab)\b ?", " ", text)
    return re.sub(r"[{}]|\\[a-zA-Z]+-?\d* ?", "", text)
