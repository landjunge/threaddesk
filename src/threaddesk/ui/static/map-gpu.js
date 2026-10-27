/* Optional large-graph renderer. The read model, inspector and views stay shared. */
(() => {
  let vendor;
  let workerVendor;
  function script(source) {
    return new Promise((resolve, reject) => {
      const node = document.createElement('script'); node.src = source; node.onload = resolve; node.onerror = reject;
      document.head.append(node);
    });
  }
  function load() {
    if (!vendor) vendor = (async () => {
      if (!document.createElement('canvas').getContext('webgl2')) throw new Error('webgl2_unavailable');
      await script('/static/graphology-0.26.0.min.js');
      await script('/static/sigma-4.0.3.min.js');
    })();
    return vendor;
  }
  window.ThreadDeskGraphGPU = {load, create(root, data, positions, options) {
    const container = root.querySelector('[data-map-gpu]');
    const graph = new graphology.Graph({multi: true});
    const selected = new Set(), visible = new Set(data.nodes.map(node => node.id));
    const byId = new Map(data.nodes.map(node => [node.id, node]));
    const shape = kind => ['project', 'person', 'agent'].includes(kind) ? 'circle'
      : kind === 'task' ? 'square' : ['document', 'decision', 'result'].includes(kind) ? 'diamond' : 'triangle';
    const symbol = status => ['confirmed', 'accepted', 'verified', 'active', 'done'].includes(status) ? '✓'
      : ['blocked', 'rejected'].includes(status) ? '!' : ['paused', 'archived', 'superseded'].includes(status) ? 'Ⅱ' : '○';
    data.nodes.forEach(node => graph.addNode(node.id, {...positions.get(node.id),
      label: `${symbol(node.status)} ${node.title}`, shape: shape(node.kind),
      size: 8, color: options.color(node), hidden: false, selected: false, fixed: options.fixed(node.id)}));
    data.relations.forEach(edge => {
      if (graph.hasNode(edge.source_id) && graph.hasNode(edge.target_id))
        graph.addEdgeWithKey(edge.id, edge.source_id, edge.target_id, {color: '#56737f', size: .7});
    });
    container.hidden = false;
    const R = Sigma.rendering;
    const renderer = new Sigma(graph, container, {
      settings: {autoRescaleContent: 'nodes', autoRescale: 'once', hideEdgesOnMove: data.relations.length > 3000,
        hideLabelsOnMove: data.nodes.length > 700, stagePadding: 40, enableNodeDrag: true,
        getDraggedNodes: node => options.fixed(node) ? [] : [node], labelDensity: 1, labelRenderedSizeThreshold: 0,
        itemSizesReference: 'screen', zoomToSizeRatioFunction: () => 1,
        minCameraRatio: .01, maxCameraRatio: 20, enableCameraRotation: false, enableCameraMouseRotation: false},
      primitives: {nodes: {shapes: [R.sdfCircle(), R.sdfSquare(), R.sdfDiamond(), R.sdfTriangle()], layers: [R.layerFill()]}},
      styles: {nodes: [Sigma.DEFAULT_STYLES.nodes, {shape: {attribute: 'shape'}, color: {attribute: 'color'},
        visibility: attr => attr.hidden ? 'hidden' : 'visible',
        label: {attribute: 'label'}, labelColor: '#eaf5fa', labelSize: attr => attr.selected ? 16 : 14,
        labelPosition: 'below', labelVisibility: attr => attr.labelShown ? 'visible' : 'hidden',
        size: attr => attr.selected ? 12 : 8}],
        edges: [Sigma.DEFAULT_STYLES.edges, {visibility: attr => attr.hidden ? 'hidden' : 'visible'}]},
    });
    let worker = null, workerTimer = null, destroyed = false, layoutTicket = 0;
    // Screen-space label occupancy is independent of graph zoom. A sparse grid
    // bounds collision checks without thousands of DOM measurements per frame.
    const measure = document.createElement('canvas').getContext('2d'), widths = new Map();
    let labelFrame = null, updatingLabels = false;
    function updateLabels() {
      labelFrame = null;
      if (destroyed) return;
      const frame = renderer.getDimensions(), occupied = new Map(), shown = new Set();
      const buckets = box => {
        const keys = [];
        for (let x = Math.floor(box.x / 128); x <= Math.floor((box.x + box.width) / 128); x++)
          for (let y = Math.floor(box.y / 64); y <= Math.floor((box.y + box.height) / 64); y++) keys.push(`${x}:${y}`);
        return keys;
      };
      const intersects = (a, b) => a.x < b.x + b.width && a.x + a.width > b.x && a.y < b.y + b.height && a.y + a.height > b.y;
      const rows = graph.mapNodes((id, attr) => ({id, attr, point: renderer.graphToViewport(attr),
        priority: selected.has(id) ? 3 : byId.get(id).kind === 'project' ? 1 : 0})).filter(row => !row.attr.hidden)
        .sort((a, b) => b.priority - a.priority || a.id.localeCompare(b.id));
      for (const row of rows) {
        const font = selected.has(row.id) ? 16 : 14, key = `${font}:${row.attr.label}`;
        if (!widths.has(key)) { measure.font = `${font}px ${getComputedStyle(root).fontFamily}`; widths.set(key, measure.measureText(row.attr.label).width + 10); }
        const width = widths.get(key), box = {x: row.point.x - width / 2, y: row.point.y + 13, width, height: font + 7};
        const keys = buckets(box);
        if (!selected.has(row.id) && (box.x < 4 || box.y < 4 || box.x + box.width > frame.width - 4 || box.y + box.height > frame.height - 4 ||
            keys.some(key => (occupied.get(key) || []).some(other => intersects(box, other))))) continue;
        shown.add(row.id);
        keys.forEach(key => { if (!occupied.has(key)) occupied.set(key, []); occupied.get(key).push(box); });
      }
      updatingLabels = true;
      graph.updateEachNodeAttributes((id, attr) => ({...attr, labelShown: shown.has(id)}));
      updatingLabels = false;
    }
    function scheduleLabels() { if (!destroyed && !updatingLabels && labelFrame === null) labelFrame = requestAnimationFrame(updateLabels); }
    renderer.getCamera().on('updated', scheduleLabels);
    graph.on('eachNodeAttributesUpdated', scheduleLabels);
    scheduleLabels();
    const stopLayout = () => {
      layoutTicket++;
      clearTimeout(workerTimer);
      if (worker) { worker.stop(); worker.kill(); worker = null; }
      root.dataset.layoutRunning = 'false';
    };
    window.addEventListener('pagehide', stopLayout);
    function select(id, additive = false) {
      if (!byId.has(id)) return;
      if (!additive) selected.clear();
      if (selected.has(id)) selected.delete(id); else selected.add(id);
      graph.updateEachNodeAttributes((key, attr) => ({...attr, selected: selected.has(key)}));
      options.select(byId.get(id));
    }
    renderer.on('clickNode', event => select(event.node, Boolean(event.event?.original?.shiftKey)));
    const lost = event => { event.preventDefault(); stopLayout(); options.fallback('gpu_context_lost'); };
    container.querySelectorAll('canvas').forEach(canvas => canvas.addEventListener('webglcontextlost', lost));
    const camera = (unclamped = false) => {
      const frame = renderer.getDimensions(), centre = {x: frame.width / 2, y: frame.height / 2};
      const point = renderer.viewportToGraph(centre), adjacent = renderer.graphToViewport({x: point.x + 1, y: point.y});
      const scale = Math.hypot(adjacent.x - centre.x, adjacent.y - centre.y);
      return {x: point.x, y: point.y, scale: unclamped ? scale : Math.max(.04, Math.min(4, scale))};
    };
    function moveCamera(value) {
      const current = camera(true), state = renderer.getCamera().getState();
      const framed = renderer.graphToFramedGraph({x: value.x, y: value.y});
      renderer.getCamera().setState({x: framed.x, y: framed.y,
        ratio: Math.max(.01, Math.min(20, state.ratio * current.scale / value.scale))});
    }
    function constrainCamera() {
      const value = camera(true), clamped = Math.max(.04, Math.min(4, value.scale));
      if (Math.abs(clamped - value.scale) > .000001) moveCamera({...value, scale: clamped});
    }
    renderer.getCamera().on('updated', constrainCamera);
    return {
      select, camera, stopLayout,
      point: id => graph.hasNode(id) ? renderer.graphToViewport(graph.getNodeAttributes(id)) : null,
      selection: () => [...selected],
      labelMetrics: () => ({displayed: renderer.getNodeDisplayedLabels().size,
        selected: [...selected].map(id => ({id, size: renderer.getNodeDisplayData(id)?.labelSize}))}),
      snapshotPositions: () => Object.fromEntries(graph.mapNodes((id, attr) => [id, {x: attr.x, y: attr.y, fixed: options.fixed(id)}])),
      restore(state) {
        stopLayout();
        graph.updateEachNodeAttributes((id, attr) => ({...attr, ...(state.positions[id] || {}), selected: false}));
        selected.clear();
        for (const id of state.selection || []) if (byId.has(id)) selected.add(id);
        graph.updateEachNodeAttributes((id, attr) => ({...attr, selected: selected.has(id)}));
        if (selected.size) options.select(byId.get([...selected][0]));
        moveCamera(state.camera);
      },
      filter(ids) {
        visible.clear(); ids.forEach(id => visible.add(id));
        graph.updateEachNodeAttributes((id, attr) => ({...attr, hidden: !visible.has(id), color: options.color(byId.get(id)), fixed: options.fixed(id)}));
        graph.updateEachEdgeAttributes((_id, attr, source, target) => ({...attr, hidden: !visible.has(source) || !visible.has(target)}));
      },
      zoom(factor) {
        stopLayout(); const state = camera();
        moveCamera({...state, scale: Math.max(.04, Math.min(4, state.scale * factor))});
      },
      fit() { stopLayout(); renderer.getCamera().setState({x: .5, y: .5, ratio: 1, angle: 0}); },
      focus(id) {
        if (!graph.hasNode(id)) return;
        const attr = graph.getNodeAttributes(id);
        moveCamera({x: attr.x, y: attr.y, scale: Math.max(.8, camera().scale)});
      },
      async arrange() {
        stopLayout();
        const ticket = layoutTicket;
        if (!window.ThreadDeskForceAtlas2) {
          if (!workerVendor) workerVendor = script('/static/forceatlas2-0.10.1.min.js');
          await workerVendor;
        }
        if (destroyed || ticket !== layoutTicket) return;
        const working = graph.copy();
        working.updateEachNodeAttributes((id, attr) => ({...attr, fixed: options.fixed(id) || !visible.has(id)}));
        worker = window.ThreadDeskForceAtlas2(working, {settings: {
          barnesHutOptimize: true, barnesHutTheta: .5, slowDown: 8, adjustSizes: true}});
        worker.start();root.dataset.layoutRunning = 'true';
        workerTimer = setTimeout(() => {
          // One final position update respects Reduced Motion and keeps all
          // other controls responsive while the worker computes off screen.
          const result = working.export();
          stopLayout();
          const points = new Map(result.nodes.map(node => [node.key, node.attributes]));
          graph.updateEachNodeAttributes((id, attr) => ({...attr,
            x: points.get(id).x, y: points.get(id).y}));
        }, 1500);
      },
      destroy() {
        destroyed = true; stopLayout();
        window.removeEventListener('pagehide', stopLayout);
        cancelAnimationFrame(labelFrame);renderer.getCamera().off('updated', scheduleLabels);
        renderer.getCamera().off('updated', constrainCamera);
        graph.off('eachNodeAttributesUpdated', scheduleLabels);
        container.querySelectorAll('canvas').forEach(canvas => canvas.removeEventListener('webglcontextlost', lost));
        renderer.kill();container.replaceChildren();container.hidden = true;
      },
    };
  }};
})();
