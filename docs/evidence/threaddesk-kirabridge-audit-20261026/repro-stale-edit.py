"""Read-only source audit; writes only synthetic data below a fresh /tmp directory.
Run from the audited repo with PYTHONPATH=src:tests and its test-capable Python.
"""
from pathlib import Path
import tempfile, os, json
root = Path(tempfile.mkdtemp(prefix='td-stale-edit-repro-'))
os.environ['HOME'] = str(root / 'home')
os.environ['THREADDESK_HOME'] = str(root / 'workspace')
from threaddesk.api.service import ThreadService
from threaddesk.ui.server import create_app
from http_ui_client import UIClient
for backend in ['json', 'sqlite']:
    os.environ['THREADDESK_STORAGE'] = backend
    os.environ['THREADDESK_HOME'] = str(root / backend)
    svc = ThreadService()
    thread = svc.create('Stale edit isolated')
    svc.set_note('original', thread.id)
    # Both tabs bootstrap before either edit, at revision 2.
    client_a, client_b = UIClient(create_app()), UIClient(create_app())
    before = ThreadService().get(thread.id).revision
    first = client_a.post(f'/threads/{thread.id}/note', data={'text': 'fresh edit A'})
    middle = ThreadService().get(thread.id)
    stale = client_b.post(f'/threads/{thread.id}/note', data={'text': 'stale edit B'})
    after = ThreadService().get(thread.id)
    print(json.dumps({'backend': backend, 'first_status': first.status_code,
        'stale_status': stale.status_code, 'before_revision': before,
        'mid_revision': middle.revision, 'after_revision': after.revision,
        'fresh_note': middle.context.notes, 'final_note': after.context.notes}, ensure_ascii=False))
