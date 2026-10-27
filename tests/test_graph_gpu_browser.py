"""Large graphs keep selection, saved state and fallback available offline."""
from __future__ import annotations

import os

import pytest
from playwright.sync_api import expect, sync_playwright

from test_desk_browser import Desk
from threaddesk.api.service import ThreadService
from threaddesk.storage.json_store import JsonStore


@pytest.fixture
def gpu_desk(tmp_path):
    store = JsonStore(tmp_path / 'workspace')
    svc = ThreadService(store=store)
    with store.transaction():
        nodes = [svc.create_node('project' if n % 8 == 0 else 'task', f'Graph Node {n:03d}') for n in range(140)]
        for n in range(1, len(nodes)):
            svc.connect(nodes[(n - 1) // 2].id, nodes[n].id, 'contains')
    desk = Desk(store.workspace_path);url = desk.start()
    try:
        yield url, nodes
    finally:
        desk.stop()


def test_gpu_view_keeps_labels_selection_saved_camera_and_worker_bounded(gpu_desk):
    url, nodes = gpu_desk
    with sync_playwright() as play:
        browser = play.chromium.launch(executable_path=os.environ.get('THREADDESK_CHROMIUM') or None)
        page = browser.new_page(viewport={'width':1440,'height':900})
        errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
        outgoing=[];page.on('request',lambda request:outgoing.append(request.url))
        page.goto(url+'/map',wait_until='networkidle')
        root = page.locator('[data-graph-endpoint]')
        expect(root).to_have_attribute('data-renderer','sigma')
        expect(page.locator('[data-map-gpu] canvas')).to_have_count(1)
        # A real pointer selects a GPU node; the DOM inspector remains shared.
        point=page.evaluate('''id=>document.querySelector('[data-graph-endpoint]').graphController.nodePoint(id)''',nodes[0].id)
        stage=page.locator('[data-map-stage]').bounding_box()
        page.mouse.click(stage['x']+point['x'],stage['y']+point['y'])
        expect(page.locator('[data-map-detail-title]')).to_have_text(nodes[0].title)
        page.locator('[data-map-tab="selection"]').click()
        page.locator('[data-map-fix-selected]').click()
        page.locator('[data-map-zoom-in]').click()
        before=page.evaluate("document.querySelector('[data-graph-endpoint]').graphController.snapshot()")
        assert before['selection']==[nodes[0].id]
        page.locator('.graph-view-tools > summary').click()
        page.locator('[data-map-view-title]').fill('GPU saved view')
        page.locator('[data-map-view-save]').click()
        expect(page.locator('[data-map-view-message]')).to_have_text('Ansicht gespeichert.')
        view_id=page.locator('[data-map-view]').input_value()
        page.locator('[data-map-arrange]').click()
        expect(root).to_have_attribute('data-layout-running','true')
        expect(root).to_have_attribute('data-layout-running','false',timeout=5000)
        after_layout=page.evaluate("document.querySelector('[data-graph-endpoint]').graphController.snapshot()")
        assert after_layout['positions'][nodes[0].id]==before['positions'][nodes[0].id]
        page.locator('[data-map-view-load]').click()
        expect(page.locator('[data-map-view-message]')).to_be_hidden()
        restored=page.evaluate("document.querySelector('[data-graph-endpoint]').graphController.snapshot()")
        assert restored['positions']==before['positions']
        assert abs(restored['camera']['x']-before['camera']['x'])<.01
        assert abs(restored['camera']['y']-before['camera']['y'])<.01
        assert abs(restored['camera']['scale']-before['camera']['scale'])<.001
        metrics=page.evaluate("document.querySelector('[data-graph-endpoint]').graphController.labelMetrics()")
        assert metrics['displayed'] > 0
        assert metrics['selected'][0]['size'] == 16
        for selector in ('[data-map-zoom-in]', '[data-map-zoom-out]'):
            page.evaluate("selector=>{for(let i=0;i<45;i++)document.querySelector(selector).click()}",selector)
            camera=page.evaluate("document.querySelector('[data-graph-endpoint]').graphController.snapshot().camera")
            assert .04 <= camera['scale'] <= 4
            with page.expect_response(lambda response:response.url.endswith('/api/graph/views') and response.request.method=='POST') as saved:
                page.locator('[data-map-view-save]').click()
            assert saved.value.ok,saved.value.text()
            expect(page.locator('[data-map-view-message]')).to_have_text('Ansicht gespeichert.')
        assert not errors, errors
        assert all(address.startswith(url) or address.startswith(('data:','blob:')) for address in outgoing),outgoing
        browser.close()


def test_repeated_layout_during_delayed_load_starts_one_worker(gpu_desk):
    import time
    url,_nodes=gpu_desk
    with sync_playwright() as play:
        browser=play.chromium.launch(executable_path=os.environ.get('THREADDESK_CHROMIUM') or None)
        page=browser.new_page(viewport={'width':1440,'height':900})
        page.add_init_script('''const NativeWorker=window.Worker;window.__workerBudget={active:0,max:0};
          window.Worker=class extends NativeWorker{constructor(...args){super(...args);this.__ended=false;window.__workerBudget.active++;window.__workerBudget.max=Math.max(window.__workerBudget.max,window.__workerBudget.active)}terminate(){if(!this.__ended){window.__workerBudget.active--;this.__ended=true}return super.terminate()}}''')
        def delayed(route):
            time.sleep(.25);route.continue_()
        page.route('**/static/forceatlas2-0.10.1.min.js',delayed)
        page.goto(url+'/map',wait_until='networkidle')
        root=page.locator('[data-graph-endpoint]');expect(root).to_have_attribute('data-renderer','sigma')
        page.locator('.graph-view-tools > summary').click()
        page.evaluate("()=>{const button=document.querySelector('[data-map-arrange]');button.click();button.click()}")
        expect(root).to_have_attribute('data-layout-running','true')
        expect(root).to_have_attribute('data-layout-running','false',timeout=5000)
        assert page.evaluate('window.__workerBudget')=={'active':0,'max':1}
        browser.close()


@pytest.mark.parametrize('failure',['unavailable','context_loss','worker_failure'])
def test_graph_gpu_failures_keep_the_full_dom_inspector(gpu_desk,failure):
    url,nodes=gpu_desk
    with sync_playwright() as play:
        browser=play.chromium.launch(executable_path=os.environ.get('THREADDESK_CHROMIUM') or None)
        page=browser.new_page(viewport={'width':1440,'height':900})
        if failure=='unavailable':
            page.add_init_script("const original=HTMLCanvasElement.prototype.getContext;HTMLCanvasElement.prototype.getContext=function(kind,...rest){return kind==='webgl2'?null:original.call(this,kind,...rest)}")
        if failure=='worker_failure':
            page.route('**/static/forceatlas2-0.10.1.min.js',lambda route:route.abort())
        page.goto(url+'/map',wait_until='networkidle')
        root=page.locator('[data-graph-endpoint]')
        if failure=='context_loss':
            expect(root).to_have_attribute('data-renderer','sigma')
            page.locator('[data-map-gpu] canvas').evaluate("canvas=>canvas.getContext('webgl2').getExtension('WEBGL_lose_context').loseContext()")
        elif failure=='worker_failure':
            expect(root).to_have_attribute('data-renderer','sigma')
            page.locator('.graph-view-tools > summary').click();page.locator('[data-map-arrange]').click()
            expect(page.locator('[data-map-summary]')).to_have_text('Layout nicht verfügbar. Positionen bleiben erhalten.')
            page.locator('.graph-view-tools > summary').click();page.locator('[data-map-list-toggle]').click()
        if failure!='worker_failure':expect(root).to_have_attribute('data-renderer','list')
        expect(page.locator('[data-map-node-list]')).to_be_visible()
        expect(page.locator('[data-list-node-id]')).to_have_count(50)
        page.locator('[data-map-list-next]').click();page.locator('[data-map-list-next]').click()
        expect(page.locator('[data-list-node-id]')).to_have_count(40)
        page.locator(f'[data-list-node-id="{nodes[139].id}"]').click()
        expect(page.locator('[data-map-detail-title]')).to_have_text(nodes[139].title)
        browser.close()


def test_renderer_threshold_refresh_preserves_shared_multiselection(tmp_path):
    from threaddesk.services.trash import TrashService
    store=JsonStore(tmp_path/'workspace');svc=ThreadService(store=store)
    with store.transaction():
        nodes=[svc.create_node('project' if n%8==0 else 'task',f'Threshold Node {n:03d}') for n in range(127)]
    desk=Desk(store.workspace_path);url=desk.start()
    try:
        with sync_playwright() as play:
            browser=play.chromium.launch(executable_path=os.environ.get('THREADDESK_CHROMIUM') or None)
            page=browser.new_page(viewport={'width':1440,'height':900});page.emulate_media(reduced_motion='reduce')
            page.goto(url+'/map',wait_until='networkidle')
            root=page.locator('[data-graph-endpoint]');expect(root).to_have_attribute('data-renderer','svg')
            page.locator(f'[data-node-id="{nodes[0].id}"] .map-node-shape').click()
            page.locator(f'[data-node-id="{nodes[8].id}"] .map-node-shape').click(modifiers=['Shift'])
            chosen=page.evaluate("document.querySelector('[data-graph-endpoint]').graphController.snapshot().selection")
            assert set(chosen)=={nodes[0].id,nodes[8].id}
            added=svc.create_node('task','Threshold added')
            page.evaluate("document.dispatchEvent(new CustomEvent('threaddesk:library-changed'))")
            expect(root).to_have_attribute('data-renderer','sigma')
            page.wait_for_function("document.querySelector('[data-graph-endpoint]').graphController.snapshot().selection.length===2")
            assert set(page.evaluate("document.querySelector('[data-graph-endpoint]').graphController.snapshot().selection"))==set(chosen)
            TrashService(store).move(kind='node',object_id=added.id,expected_revision=added.revision,operation_id='threshold-trash')
            page.evaluate("document.dispatchEvent(new CustomEvent('threaddesk:library-changed'))")
            expect(root).to_have_attribute('data-renderer','svg')
            assert set(page.evaluate("document.querySelector('[data-graph-endpoint]').graphController.snapshot().selection"))==set(chosen)
            expect(page.locator('.map-node.is-selected')).to_have_count(2)
            browser.close()
    finally:desk.stop()
