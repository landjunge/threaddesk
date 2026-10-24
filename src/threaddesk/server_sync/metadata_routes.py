"""Authenticated metadata routes, installed in the existing server boundary."""
from starlette.concurrency import run_in_threadpool
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from threaddesk.server_sync.metadata import document_etag, export_document, synchronize, list_conflicts, resolve_conflict


def install_routes(app,project_resolver,read_body):
    @app.get('/api/projects/{pid}/metadata')
    def metadata(pid:str,request:Request):
        _,core,lock=project_resolver(request,pid)
        with lock,core.store.transaction():
            document=export_document(core,pid)
        etag=document_etag(document)
        if request.headers.get('if-none-match') == etag:
            return Response(status_code=304,headers={'ETag':etag})
        return JSONResponse({'document':document},headers={'ETag':etag})

    @app.post('/api/projects/{pid}/metadata/sync')
    async def sync(pid:str,request:Request):
        value=await read_body(request,{'operation_id','base','document'})
        def operation():
            _,core,lock=project_resolver(request,pid)
            with lock:
                return synchronize(core,pid,**value)
        return await run_in_threadpool(operation)

    @app.get('/api/projects/{pid}/metadata/conflicts')
    def conflicts(pid:str,request:Request):
        _,core,lock=project_resolver(request,pid)
        with lock,core.store.transaction():
            return {'conflicts':list_conflicts(core,pid)}

    @app.post('/api/projects/{pid}/metadata/resolve')
    async def resolve(pid:str,request:Request):
        value=await read_body(request,{'conflict_id','expected_current','chosen_value','operation_id'})
        def operation():
            _,core,lock=project_resolver(request,pid)
            with lock:
                return resolve_conflict(core,pid,**value)
        return await run_in_threadpool(operation)
