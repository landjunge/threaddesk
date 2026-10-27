"""Serialize small artifact registries with their existing store writer.

JSON stages artifact changes in its journal. SQLite serializes these writers
with BEGIN IMMEDIATE, but its existing filesystem artifacts are not rolled back
with SQL. This helper does not introduce a second lock or claim a mixed commit.
"""
from __future__ import annotations

from contextlib import contextmanager
from functools import wraps


@contextmanager
def owner_write(store):
    """Join this caller's transaction or acquire the store's normal writer."""
    if store.in_transaction:
        yield
    else:
        with store.transaction():
            yield


def registry_write(method):
    """Wrap the entire read/validate/modify/write sequence of a registry."""
    @wraps(method)
    def guarded(self, *args, **kwargs):
        with owner_write(self.store):
            return method(self, *args, **kwargs)
    return guarded
