"""Literal search normalization; user input is never an FTS expression."""

from __future__ import annotations

import unicodedata


def folded(value: str, *, german=True) -> str:
    value = value.casefold()
    if german:
        value = value.translate(str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue"}))
    value = "".join(
        char
        for char in unicodedata.normalize("NFKD", value)
        if not unicodedata.combining(char)
    )
    return " ".join(value.split())


def searchable(values) -> str:
    text = " ".join(str(value or "") for value in values)
    german, plain = folded(text), folded(text, german=False)
    return german if german == plain else german + "\n" + plain


def terms(query):
    if (
        not isinstance(query, str)
        or len(query.encode("utf-8")) > 512
        or any(ord(c) < 32 for c in query)
    ):
        raise ValueError("invalid_search_query")
    values = folded(query).split()
    if len(values) > 16:
        raise ValueError("invalid_search_query")
    return values
