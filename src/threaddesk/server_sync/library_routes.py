"""Tenant-bound library reads for the existing authenticated server boundary."""
from fastapi import HTTPException, Query, Request
from fastapi.responses import FileResponse

from threaddesk.core.errors import ThreadDeskError
from threaddesk.services.library_api import LibraryApplication
from threaddesk.services.library_files import LibraryFileService
from threaddesk.services.library_import import LibraryImportError


def install_routes(app, stores, project_resolver):
    @app.get('/api/projects/{pid}/library')
    def library(pid: str, request: Request, query: str = Query('', max_length=1000),
                limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0, le=100000)):
        _, core, lock = project_resolver(request, pid)
        with lock:
            core.store.get_thread(pid)  # Trashed projects cannot expose their library.
            if query:
                if offset > 10000:
                    raise HTTPException(422, 'Library search offset must not exceed 10000')
                library = LibraryApplication(core.store)
                arguments = {
                    'action': 'search', 'query': query, 'entity_type': 'file',
                    'thread_id': pid, 'limit': limit, 'offset': offset}
                result = library.call(arguments)
                rows = result.get('hits', [])
                following = offset + len(rows)
                # Owner search returns hits, not a count. One bounded probe
                # establishes another page without scanning the whole index.
                has_more = (len(rows) == limit and following <= 10000 and bool(
                    library.call({**arguments, 'limit': 1, 'offset': following}).get('hits')))
                total = None
                next_offset = following if has_more else None
                index = result.get('index', {})
            else:
                result = LibraryFileService(core.store).list(thread_id=pid, limit=limit, offset=offset)
                rows, total, next_offset = result['records'], result['total'], result['next_offset']
                index = None
            fields = ('id', 'filename', 'size', 'sha256', 'revision', 'snippet', 'extraction_status')
            records = []
            for row in rows:
                record_id = row.get('record_id') or row['id']
                records.append({**{key: row[key] for key in fields if key in row},
                                'id': record_id, 'download_path': f'/api/projects/{pid}/library/{record_id}'})
            return {'records': records, 'total': total, 'next_offset': next_offset, 'index': index}

    def download(request, record_id, pid=None):
        _, core, lock = stores(request.state.user)
        with lock:
            files = LibraryFileService(core.store)
            try:
                record = files.info(record_id)
                owner = record.get('thread_id')
                if not owner or pid is not None and owner != pid:
                    raise HTTPException(404, 'Library file not found')
                project_resolver(request, owner)
                core.store.get_thread(owner)
                blob, verified = files.importer.open_record(record_id)
            except LibraryImportError:
                raise HTTPException(409, 'Stored library copy failed integrity verification') from None
            except ThreadDeskError:
                raise HTTPException(404, 'Library file not found') from None
        # Downloads are always inert attachments, including uploaded HTML/SVG.
        return FileResponse(blob, media_type='application/octet-stream', filename=verified['filename'],
                            headers={'X-Content-Type-Options': 'nosniff', 'Cache-Control': 'no-store',
                                     'Content-Security-Policy': "default-src 'none'; sandbox"})

    @app.get('/api/projects/{pid}/library/{record_id}')
    def project_file(pid: str, record_id: str, request: Request):
        project_resolver(request, pid)
        return download(request, record_id, pid)

    @app.get('/library/files/{record_id}')
    def library_file(record_id: str, request: Request):
        # Preserve the existing MCP open_path on the public server too.
        return download(request, record_id)
