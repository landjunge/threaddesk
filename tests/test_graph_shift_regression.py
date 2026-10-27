"""An overview drawer must keep click targets usable without changing user zoom."""
from test_ui_browser import page, live_map, fresh_map_view  # noqa: F401


def snapshot(page):
    return page.evaluate("document.querySelector('[data-graph-endpoint]').graphController.snapshot()")


def test_overview_first_selection_keeps_shapes_inside_the_narrower_stage(page):
    page.click('[data-map-reset]')
    before = snapshot(page)
    page.locator('.map-node-shape').first.click()
    page.wait_for_timeout(160)
    actual = snapshot(page)
    assert actual['positions'] == before['positions']
    result = page.locator('[data-map-stage]').evaluate('''stage => {
      const bounds=stage.getBoundingClientRect();
      return [...stage.querySelectorAll('.map-node-shape')].map(shape=>{
        const b=shape.getBoundingClientRect();
        return b.left>=bounds.left && b.right<=bounds.right && b.top>=bounds.top && b.bottom<=bounds.bottom;
      });
    }''')
    assert all(result), result


def test_opening_inspector_preserves_deliberately_zoomed_camera_and_positions(page):
    page.click('[data-map-reset]');page.click('[data-map-zoom-in]')
    identity = page.locator('[data-map-stage]').evaluate('''stage => {
      const bounds=stage.getBoundingClientRect();
      return [...stage.querySelectorAll('.map-node')].find(node=>{
        const b=node.querySelector('.map-node-shape').getBoundingClientRect();
        return b.left>=bounds.left && b.right<=bounds.right && b.top>=bounds.top && b.bottom<=bounds.bottom;
      }).dataset.nodeId;
    }''')
    before = snapshot(page)
    page.locator(f'[data-node-id="{identity}"] .map-node-shape').click()
    page.wait_for_timeout(160)
    actual = snapshot(page)
    assert actual['camera'] == before['camera']
    assert actual['positions'] == before['positions']
