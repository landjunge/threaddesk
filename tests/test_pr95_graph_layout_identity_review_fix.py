"""The same semantic graph must not acquire random slots from new UUIDs."""
import json
import subprocess
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[1] / "src/threaddesk/ui/static"

# Real 1180x760 browser measurements from the representative workspace graph.
# Keep this pure geometry regression independent of platform font substitution;
# test_graph_workspace_browser still measures the actual DOM and collisions.
PROBE = r"""
const fs = require('fs'), path = require('path'), vm = require('vm');
const context = {window: {}}; vm.createContext(context);
for (const name of ['map-layout.js', 'map-viewport.js', 'map-shapes.js']) {
  vm.runInContext(fs.readFileSync(path.join(process.argv[1], name), 'utf8'), context);
}
const api = context.window, width = 1146, height = 464;
const shapes = api.ThreadDeskMapShapes(() => ({width, height}));
const nodes = Array.from({length: 25}, (_, number) => ({
  title: `Bereich ${String(number).padStart(2, '0')} – Langer fachlicher Titel für Planung, Quellen und überprüfbare Ergebnisse`,
  kind: ['task', 'decision', 'document', 'project'][number % 4],
}));
nodes.push({title: 'fixture-0.txt', kind: 'document'}, {title: 'fixture-1.txt', kind: 'document'},
  {title: 'Zentrales Projekt für lange Titel und übersichtliche Dateien', kind: 'project'});
const widths = [130.328125,128,129.953125,130.28125,130.515625,130.15625,
  130.421875,129.203125,130.453125,130.421875,128,127.4375,127.640625,
  127.96875,128.1875,127.84375,128.09375,127.4375,128.125,128.09375,
  129.953125,127.640625,129.59375,129.921875,129.9375,76.5625,74.453125,
  147.8643035888672];
function run(seed) {
  const ranks = nodes.map((_, i) => i); let state = seed;
  const next = () => { state = (Math.imul(state, 1664525) + 1013904223) >>> 0; return state; };
  for (let i = ranks.length - 1; i > 0; i--) {
    const j = next() % (i + 1); [ranks[i], ranks[j]] = [ranks[j], ranks[i]];
  }
  const graph = nodes.map((node, i) => ({...node, id: ranks[i].toString(16).padStart(12, '0')}));
  const relations = graph.slice(0,25).map(node => ({source_id: graph[27].id, target_id: node.id}));
  for (const owner of [7,11,15,19,23,27]) {
    for (const file of [25,26]) relations.push({source_id: graph[owner].id, target_id: graph[file].id});
  }
  const positions = api.ThreadDeskMapLayout(graph, relations, {width, height, radiusOf: shapes.radiusOf});
  const camera = api.ThreadDeskMapViewport.fit(graph.map(node => ({...positions.get(node.id), r: shapes.radiusOf(node)})), width, height);
  const candidates = graph.map((node, order) => {
    const point = positions.get(node.id), size = shapes.SIZE[shapes.SHAPE[node.kind]];
    const dimensions = Array.isArray(size) ? size : [size, size];
    return {order, id: node.id, font: order === 27 ? 16 : 14,
      priority: order === 27 ? 3 : 2, width: widths[order], height: order === 27 ? 40 : order >= 25 ? 18 : 36,
      x: camera.x + camera.scale * point.x, y: camera.y + camera.scale * point.y,
      radius: dimensions[1] * camera.scale,
      halfWidth: dimensions[0] * camera.scale, halfHeight: dimensions[1] * camera.scale};
  });
  const visible = api.ThreadDeskMapViewport.labels(candidates, width, height).filter(item => item.visible);
  return {seed, visible: visible.length, nodes: graph.length,
    titleSlots: graph.map(node => ({title: node.title, ...positions.get(node.id)}))};
}
console.log(JSON.stringify([1,150,413].map(run)));
"""


@pytest.fixture(scope="module")
def geometry_cases():
    result = subprocess.run(["node", "-e", PROBE, str(STATIC)], capture_output=True,
                            text=True, check=True, timeout=15)
    return json.loads(result.stdout)


def test_semantic_title_slots_survive_different_ids(geometry_cases):
    baseline = geometry_cases[0]["titleSlots"]
    assert all(case["titleSlots"] == baseline for case in geometry_cases), geometry_cases


def test_seed150_overview_keeps_at_least_half_its_labels(geometry_cases):
    case = next(case for case in geometry_cases if case["seed"] == 150)
    assert case["nodes"] == 28
    assert case["visible"] >= 14, case
