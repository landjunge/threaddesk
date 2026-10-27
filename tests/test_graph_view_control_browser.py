"""Actual browser camera transfer and acknowledgement over shared commands."""
from __future__ import annotations

import math
import re

from playwright.sync_api import expect
from test_graph_activity_browser import graph_activity


def command(page, identity, arguments, *, mutation=False):
    result = page.evaluate('''async request => {
      const catalog=await (await fetch('/api/commands/catalog')).json();
      const envelope={version:1,workspace_id:catalog.workspace_id,command:request.identity,arguments:request.arguments};
      if(request.mutation){envelope.operation_id=request.arguments.operation_id;envelope.expected_revision=request.arguments.expected_revision}
      const response=await window.threadDeskWrite('/api/commands',{headers:{'Content-Type':'application/json'},body:JSON.stringify(envelope)});
      return {status:response.status,body:await response.json()};
    }''',{'identity':identity,'arguments':arguments,'mutation':mutation})
    assert result['status']==200,result
    return result['body']['result']


def _save_view(page):
    root=page.locator('[data-graph-endpoint]')
    expect(root).to_have_attribute('data-view-client-id',re.compile('.+'))
    page.locator('[data-map-zoom-in]').click()
    page.locator('.graph-view-tools > summary').click()
    page.locator('[data-map-view-title]').fill('Remote control view')
    page.locator('[data-map-view-save]').click()
    expect(page.locator('[data-map-view-save]')).to_be_enabled()
    expect(page.locator('[data-map-view]')).not_to_have_value('')
    identity=page.locator('[data-map-view]').input_value()
    state=page.evaluate("document.querySelector('[data-graph-endpoint]').graphController.snapshot()")
    page.locator('.graph-view-tools > summary').click()
    return identity,state


def test_explicit_apply_waits_for_observed_ui_ack_and_replay_keeps_later_user_camera(graph_activity):
    page,_url,project,_identity,_other,_language=graph_activity
    page.locator(f'[data-node-id="{project}"] .map-node-shape').click()
    view,state=_save_view(page)
    page.locator('[data-map-zoom-out]').click();page.locator('[data-map-zoom-out]').click()
    root=page.locator('[data-graph-endpoint]')
    arguments={'id':view,'expected_revision':1,'operation_id':'browser-apply','client_id':root.get_attribute('data-view-client-id')}
    intent=command(page,'graph_view.apply',arguments,mutation=True)
    assert intent['status']=='queued' and intent['acknowledgement'] is None
    expect(root).to_have_attribute('data-view-control-operation','browser-apply',timeout=10000)
    expect(root).to_have_attribute('data-view-control-status','applied')
    status=command(page,'graph_view.apply_status',{'operation_id':'browser-apply'})
    assert status['result']['status']=='applied'
    assert status['result']['acknowledgement']['observation']['matched']
    actual=page.evaluate("document.querySelector('[data-graph-endpoint]').graphController.snapshot()")
    assert math.isclose(actual['camera']['scale'],state['camera']['scale'],rel_tol=1e-5)
    assert actual['selection']==state['selection']
    page.locator('[data-map-zoom-out]').click()
    later=page.evaluate("document.querySelector('[data-graph-endpoint]').graphController.snapshot().camera")
    command(page,'graph_view.apply',arguments,mutation=True)
    page.wait_for_timeout(1700)
    assert page.evaluate("document.querySelector('[data-graph-endpoint]').graphController.snapshot().camera")==later


def test_lost_ack_response_is_reconciled_without_applying_view_twice(graph_activity):
    page,_url,_project,_identity,_other,_language=graph_activity
    view,_state=_save_view(page)
    root=page.locator('[data-graph-endpoint]')
    acknowledgements=[]
    def lose_first(route):
        acknowledgements.append(route.request.post_data_json)
        if len(acknowledgements)==1:
            response=route.fetch();assert response.ok;route.abort('failed')
        else:route.continue_()
    page.route('**/api/graph/view-control/*/ack',lose_first)
    command(page,'graph_view.apply',{'id':view,'expected_revision':1,'operation_id':'lost-ack',
                                    'client_id':root.get_attribute('data-view-client-id')},mutation=True)
    page.wait_for_function("document.querySelector('[data-graph-endpoint]').dataset.viewControlStatus==='waiting'")
    # The first ACK reached the server. A later user zoom must survive its retry.
    page.locator('[data-map-zoom-out]').click()
    later=page.evaluate("document.querySelector('[data-graph-endpoint]').graphController.snapshot().camera")
    expect(root).to_have_attribute('data-view-control-operation','lost-ack',timeout=10000)
    expect(root).to_have_attribute('data-view-control-status','applied')
    assert len(acknowledgements)>=2 and acknowledgements[0]==acknowledgements[1]
    assert page.evaluate("document.querySelector('[data-graph-endpoint]').graphController.snapshot().camera")==later


def test_apply_loads_exact_saved_nodes_from_a_different_bounded_page(graph_activity):
    page,_url,project,_identity,_other,_language=graph_activity
    page.locator(f'[data-node-id="{project}"] .map-node-shape').click()
    view,saved=_save_view(page)
    # Ask the real backend for a one-node first page on subsequent GETs.
    page.route('**/api/graph/v2?*',lambda route:route.continue_(url=route.request.url+'&limit=1'))
    page.reload(wait_until='networkidle')
    expect(page.locator('.map-node')).to_have_count(1)
    root=page.locator('[data-graph-endpoint]')
    expect(root).to_have_attribute('data-view-client-id',re.compile('.+'))
    with page.expect_response(lambda response:response.url.endswith('/api/graph/v2') and response.request.method=='POST') as nodes:
        command(page,'graph_view.apply',{'id':view,'expected_revision':1,'operation_id':'other-page',
                                        'client_id':root.get_attribute('data-view-client-id')},mutation=True)
    assert nodes.value.ok,nodes.value.text()
    assert set(nodes.value.request.post_data_json['node_ids'])==set(saved['positions'])
    expect(root).to_have_attribute('data-view-control-operation','other-page',timeout=10000)
    expect(root).to_have_attribute('data-view-control-status','applied')
    expect(page.locator('.map-node')).to_have_count(3)
    status=command(page,'graph_view.apply_status',{'operation_id':'other-page'})
    assert status['result']['acknowledgement']['observation']['matched']


def test_lost_ack_does_not_follow_a_replaced_client_capability(graph_activity):
    import json
    page,_url,_project,_identity,_other,_language=graph_activity
    view,_saved=_save_view(page)
    root=page.locator('[data-graph-endpoint]');old_client=root.get_attribute('data-view-client-id')
    acknowledgements=[];lost=False;invalidated=False
    def lose_ack(route):
        nonlocal lost
        body=route.request.post_data_json;acknowledgements.append((route.request.url,body))
        if body['operation_id']=='old-client' and not lost:
            lost=True;response=route.fetch();assert response.ok;route.abort('failed')
        else:route.continue_()
    def invalidate_once(route):
        nonlocal invalidated
        if lost and not invalidated:
            invalidated=True;route.fulfill(status=403,content_type='application/json',body=json.dumps({'ok':False,'code':'view_client_denied'}))
        else:route.continue_()
    page.route('**/api/graph/view-control/*/ack',lose_ack)
    page.route('**/api/graph/view-control/*/pending',invalidate_once)
    command(page,'graph_view.apply',{'id':view,'expected_revision':1,'operation_id':'old-client','client_id':old_client},mutation=True)
    page.wait_for_function("old=>document.querySelector('[data-graph-endpoint]').dataset.viewClientId!==old",arg=old_client)
    new_client=root.get_attribute('data-view-client-id')
    command(page,'graph_view.apply',{'id':view,'expected_revision':1,'operation_id':'new-client','client_id':new_client},mutation=True)
    expect(root).to_have_attribute('data-view-control-operation','new-client',timeout=10000)
    page.wait_for_timeout(3200)
    expect(root).to_have_attribute('data-view-control-status','applied')
    assert not any('/'+new_client+'/' in url and body['operation_id']=='old-client' for url,body in acknowledgements)


def test_zoomed_svg_drag_tracks_pointer_and_camera_only_view_preserves_positions(graph_activity):
    page,_url,project,_identity,_other,_language=graph_activity
    root=page.locator('[data-graph-endpoint]')
    expect(root).to_have_attribute('data-view-client-id',re.compile('.+'))
    page.locator('[data-map-zoom-in]').click();page.locator('[data-map-zoom-in]').click()
    shape=page.locator(f'[data-node-id="{project}"] .map-node-shape')
    before=shape.bounding_box();x=before['x']+before['width']/2;y=before['y']+before['height']/2
    page.mouse.move(x,y);page.mouse.down();page.mouse.move(x+60,y+36,steps=8);page.mouse.up()
    after=shape.bounding_box()
    assert abs(after['x']-before['x']-60)<3,(before,after)
    assert abs(after['y']-before['y']-36)<3,(before,after)
    original=page.evaluate("document.querySelector('[data-graph-endpoint]').graphController.snapshot()")
    camera={**original['camera'],'x':original['camera']['x']+10,'y':original['camera']['y']+5}
    command(page,'graph_view.manage',{'action':'save','id':'camera-only','expected_revision':0,'operation_id':'camera-save',
                                     'data':{'title':'Only camera','state':{'camera':camera,'filters':original['filters'],
                                                                           'selection':original['selection']}}},mutation=True)
    command(page,'graph_view.apply',{'id':'camera-only','expected_revision':1,'operation_id':'camera-apply',
                                    'client_id':root.get_attribute('data-view-client-id')},mutation=True)
    expect(root).to_have_attribute('data-view-control-operation','camera-apply',timeout=10000)
    expect(root).to_have_attribute('data-view-control-status','applied')
    final=page.evaluate("document.querySelector('[data-graph-endpoint]').graphController.snapshot()")
    assert final['positions']==original['positions']
    assert math.isclose(final['camera']['x'],camera['x'],abs_tol=1e-5)
    assert math.isclose(final['camera']['y'],camera['y'],abs_tol=1e-5)
