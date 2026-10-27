"""Metadata-only exchange for existing bindings, including trashed projects.

No file client is constructed, no file tree is inventoried, no offline policy
changes and no remote project is created. The existing metadata replica owns
uncertain-request replay, content merge and lifecycle conflict resolution.
"""
from __future__ import annotations

import hashlib

from threaddesk.core.errors import ManagementError
from threaddesk.services.trash import _hash
from threaddesk.server_sync.store import _id


def replica_state(book, thread_id, config):
    identity = config['url'] + '\0' + config['project_id'] + '\0' + hashlib.sha256(config['token'].encode()).hexdigest()
    return identity, book.root / 'replicas' / thread_id / hashlib.sha256(identity.encode()).hexdigest()


def synchronize_lifecycle(core, thread_id):
    from threaddesk.server_sync.desktop import BindingBook, _BOOK_LOCK, _RUN_LOCKS, _http_client
    from threaddesk.server_sync.metadata import MetadataReplica
    import threading

    core.store.get_thread(thread_id, include_trashed=True)
    book = BindingBook(core)
    with _BOOK_LOCK:
        lock = _RUN_LOCKS.setdefault((str(book.workspace), thread_id), threading.Lock())
    if not lock.acquire(blocking=False):
        raise ManagementError('sync_busy', 'Another operation owns this project binding.')
    replica = None
    config = None
    try:
        config = book.load(thread_id)
        if not config or not config.get('project_id'):
            raise ManagementError('sync_binding_required', 'An existing bound remote project is required.')
        pid = _id(config['project_id'])
        identity, directory = replica_state(book, thread_id, config)
        replica = MetadataReplica(core, thread_id, directory / 'metadata', remote_identity=identity)
        if config.get('bootstrap_document') is not None:
            replica.seed_base(config['bootstrap_document'])
        with _http_client(base_url=config['url'], timeout=10, follow_redirects=False, trust_env=False) as http:
            result = replica.sync_once(http, pid, config['token'])
        document = result['document']
        status = {'state': 'conflict' if result['state'] == 'conflict' else 'metadata_only',
                  'mode': 'lifecycle_metadata', 'metadata_state': result['state'],
                  'metadata_conflict_count': len(result.get('conflicts', [])),
                  'document_digest': _hash(document), 'lifecycle': document.get('lifecycle'),
                  'unchanged': bool(result.get('unchanged')), 'files_transferred': False}
        book.update(thread_id, {'bootstrap_document': None}, config_id=config['config_id'])
        book.record(thread_id, config['config_id'], status)
        from threaddesk.services.library_refresh import refresh_existing
        refresh_existing(core.store)
        return status
    except ManagementError as exc:
        if config is not None:
            book.record(thread_id, config['config_id'], {'state':'blocked',
                'mode':'lifecycle_metadata', 'error':exc.code, 'files_transferred':False})
        raise
    except Exception as exc:
        if config is not None:
            book.record(thread_id, config['config_id'], {'state':'disconnected',
                'mode':'lifecycle_metadata', 'error':type(exc).__name__, 'files_transferred':False})
        raise ManagementError('sync_unconfirmed', 'Metadata lifecycle exchange could not be confirmed.',
                              error_type=type(exc).__name__) from exc
    finally:
        if replica is not None:
            replica.close()
        lock.release()
