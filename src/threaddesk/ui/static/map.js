(() => {
  const root = document.querySelector("[data-graph-endpoint]");
  if (!root) return;

  const stage = root.querySelector("[data-map-stage]");
  const world = root.querySelector("[data-map-world]");
  const empty = root.querySelector("[data-map-empty]");
  const error = root.querySelector("[data-map-error]");
  const summary = root.querySelector("[data-map-summary]");
  const detailTitle = root.querySelector("[data-map-detail-title]");
  const detailText = root.querySelector("[data-map-detail-text]");
  const detailMeta = root.querySelector("[data-map-detail-meta]");
  const canvas = root.querySelector("[data-map-canvas]");
  const effectsToggle = root.querySelector("[data-map-effects]");
  const svgNS = "http://www.w3.org/2000/svg";
  // Texte kommen aus dem Katalog des Servers, nie aus dieser Datei.
  let STRINGS = {};
  let ACTORS = {};
  try {
    STRINGS = JSON.parse(root.dataset.strings || "{}");
  } catch (error) {
    STRINGS = {};
  }
  try { ACTORS = JSON.parse(root.dataset.actorMarks || "{}"); }
  catch (_) { ACTORS = {}; }
  const ACTOR_COLORS = {ink: "#8b909a", moss: "#6f8f78", clay: "#a68462",
    sea: "#6d8ea3", plum: "#8d7ea8", sand: "#b1a27a"};
  const t = (key, values) => {
    let text = STRINGS[key];
    if (text === undefined) return key;
    if (values) {
      Object.entries(values).forEach(([name, value]) => {
        text = text.split(`{${name}}`).join(value);
      });
    }
    return text;
  };
  const activity = window.ThreadDeskMapActivity(root, t);
  const viewport = window.ThreadDeskMapViewport;
  const MIN_SCALE = 0.04;
  const MAX_SCALE = 4;
  let VIEW_W = Math.max(1, stage.clientWidth);
  let VIEW_H = Math.max(1, stage.clientHeight);
  canvas.setAttribute("viewBox", `0 0 ${VIEW_W} ${VIEW_H}`);

  const shapes = window.ThreadDeskMapShapes(() => ({width: VIEW_W, height: VIEW_H}));
  const {SHAPE, TONE, EDGE, GLYPH, SIZE, MARK, MARK_AT, shapeOf, toneOf, radiusOf,
    el, outline, caption, defs, backdrop, edgePath} = shapes;

  // ---------------------------------------------------------------- Layout
  // Bestätigte Beziehungen ordnen eine ruhige, lesbare Anfangsansicht.
  // Bereits gesetzte Positionen bleiben bei Aktualisierungen erhalten.
  const layout = (nodes, relations, previous = new Map()) =>
    window.ThreadDeskMapLayout(nodes, relations,
      {width: VIEW_W, height: VIEW_H, radiusOf, previous});

  let scale = 1;
  let offsetX = 0;
  let offsetY = 0;
  let drag = null;
  let nodeDrag = null;
  let placed = new Map();
  let sizes = new Map();
  let updateLabels = () => {};
  let invalidateLabelWidths = () => {};
  let initialDrawn = false, latestGraph = null;
  let serverPaging = false, pageOffset = 0;
  let gpu = null, gpuUnavailable = false;
  let startupDeadline = 0, startupTimer = null;
  let layoutWindow = {width: window.innerWidth, height: window.innerHeight};
  const windowGeometryChanged = () => window.innerWidth !== layoutWindow.width ||
    window.innerHeight !== layoutWindow.height;
  let startupCorrectionUsed = false, correctionPending = false, hasInteraction = false;
  const noteInteraction = () => {
    hasInteraction = true;
    clearTimeout(startupTimer);
  };
  ["pointerdown", "click", "keydown", "wheel", "input"].forEach(name =>
    root.addEventListener(name, noteInteraction, {capture: true, passive: true}));
  let applyFilter = () => {};
  let activeFilter = {query: "", kind: "", project_id: "", status: "", mode: "work", band: "", hops: 0};
  let fixedIds = new Set();
  const showDetail = window.ThreadDeskGraphInspector(root, t, activity, id => fixedIds.has(id));
  let pendingSearchFocus = false;
  let focusTicket = 0;
  const cancelFocus = () => {
    focusTicket += 1;
    root.classList.remove("is-focusing");
  };
  let selectedFocusId = null;
  let selectedNodeIds = new Set();
  const focusSelectionControl = root.querySelector("[data-map-focus-selection]");
  const updateFocusControl = () => {
    if (!focusSelectionControl) return;
    const selected = gpu ? gpu.selection().length > 0 : [...world.querySelectorAll(".is-selected[data-node-id]")]
      .some(node => node.style.display !== "none");
    focusSelectionControl.disabled = !selected;
    focusSelectionControl.setAttribute("aria-disabled", String(!selected));
  };

  const applyTransform = () => {
    world.setAttribute("transform", `translate(${offsetX} ${offsetY}) scale(${scale})`);
    updateLabels();
  };
  // Programmatischer Fokus gleitet einmal hin. Ziehen und Rad bleiben direkt.
  // effects-off deckt den Schalter und prefers-reduced-motion ab.
  const focusOn = (point) => {
    const ticket = ++focusTicket;
    const targetX = VIEW_W / 2 - scale * point.x;
    const targetY = VIEW_H / 2 - scale * point.y;
    const motionOk = !root.classList.contains("effects-off");
    if (!motionOk) {
      offsetX = targetX;
      offsetY = targetY;
      applyTransform();
      return;
    }
    root.classList.add("is-focusing");
    const startX = offsetX;
    const startY = offsetY;
    const start = performance.now();
    const step = (now) => {
      if (ticket !== focusTicket) return;
      const amount = Math.min(1, (now - start) / 220);
      const eased = 1 - (1 - amount) ** 3;
      offsetX = startX + (targetX - startX) * eased;
      offsetY = startY + (targetY - startY) * eased;
      applyTransform();
      if (amount < 1) requestAnimationFrame(step);
      else root.classList.remove("is-focusing");
    };
    requestAnimationFrame(step);
  };
  const clamp = (value) => Math.max(MIN_SCALE, Math.min(MAX_SCALE, value));
  // Bildschirmpixel und Kartenkoordinaten sind nicht dasselbe: die viewBox
  // wird auf die Bühnenbreite skaliert. Ohne Umrechnung folgt die Karte dem
  // Cursor nicht, sobald das Fenster schmaler als die viewBox ist.
  const toUser = (clientX, clientY) => {
    const ctm = canvas.getScreenCTM();
    if (!ctm) return {x: VIEW_W / 2, y: VIEW_H / 2};
    const point = canvas.createSVGPoint();
    point.x = clientX;
    point.y = clientY;
    const mapped = point.matrixTransform(ctm.inverse());
    return {x: mapped.x, y: mapped.y};
  };
  const pixelsPerUser = () => {
    const ctm = canvas.getScreenCTM();
    return ctm && ctm.a ? ctm.a : 1;
  };
  // Zoomt um einen festen Punkt, damit der Inhalt nicht aus dem Bild wandert.
  const zoomAt = (factor, anchor) => {
    cancelFocus();
    const next = clamp(scale * factor);
    if (next === scale) return;
    offsetX = anchor.x - (next / scale) * (anchor.x - offsetX);
    offsetY = anchor.y - (next / scale) * (anchor.y - offsetY);
    scale = next;
    applyTransform();
  };
  const stageCentre = () => {
    const rect = stage.getBoundingClientRect();
    return toUser(rect.left + rect.width / 2, rect.top + rect.height / 2);
  };
  const zoom = (factor) => gpu ? gpu.zoom(factor) : zoomAt(factor, stageCentre());
  // Einpassen heißt einpassen: der ganze Graph muss sichtbar werden.
  const fit = () => {
    if (gpu) { gpu.fit(); return; }
    cancelFocus();
    const points = [...world.querySelectorAll(".map-node")]
      .filter(node => node.style.display !== "none")
      .map(node => ({...placed.get(node.dataset.nodeId), r: sizes.get(node.dataset.nodeId)}));
    const camera = viewport.fit(points, VIEW_W, VIEW_H);
    if (!camera) return;
    scale = camera.scale;
    offsetX = camera.x;
    offsetY = camera.y;
    applyTransform();
  };

  const filterWithoutSVG = graph => {
    activity.update(graph, activeFilter.mode);
    const visible = window.ThreadDeskGraphFilter(graph, activeFilter, activity, selectedFocusId);
    if (gpu) gpu.filter(visible);
    empty.hidden = visible.size !== 0;
    root.dispatchEvent(new CustomEvent("threaddesk:graph-filtered", {
      bubbles: true, detail: {visible: visible.size, total: graph.nodes.length, ids: [...visible]},
    }));
    updateFocusControl();
  };
  const renderFallback = graph => {
    if (gpu) { gpu.destroy(); gpu = null; }
    root.dataset.renderer = "list"; canvas.hidden = true; world.replaceChildren();
    summary.textContent = t("map.gpu_fallback");
    placed = layout(graph.nodes, graph.relations, placed);
    applyFilter = () => filterWithoutSVG(graph); applyFilter();
    const button = root.querySelector("[data-map-list-toggle]");
    if (root.querySelector("[data-map-node-list]").hidden) button.click();
    button.disabled = true;
    root.querySelector("[data-map-arrange]").disabled = true;
  };
  const renderGPU = (graph, refreshing) => {
    const previous = gpu ? {camera: gpu.camera(), positions: gpu.snapshotPositions(), selection: [...selectedNodeIds]} :
      placed.size ? {camera: {x: (VIEW_W / 2 - offsetX) / scale, y: (VIEW_H / 2 - offsetY) / scale, scale},
        positions: Object.fromEntries([...placed].map(([id, point]) => [id, {x: point.x, y: point.y, fixed: fixedIds.has(id)}])),
        selection: [...selectedNodeIds]} : null;
    if (previous) placed = new Map(Object.entries(previous.positions));
    if (gpu) { gpu.destroy(); gpu = null; }
    root.dataset.renderer = "sigma"; canvas.hidden = true; world.replaceChildren();
    summary.textContent = t("map.nodes_relations", {nodes: graph.counts.nodes, relations: graph.counts.relations});
    placed = layout(graph.nodes, graph.relations, placed);
    activity.update(graph, activeFilter.mode);
    try {
      gpu = window.ThreadDeskGraphGPU.create(root, graph, placed, {
        fixed: id => fixedIds.has(id),
        color: node => activeFilter.mode === "status" ? getComputedStyle(root).getPropertyValue(`--tone-${toneOf(node)}`).trim() : activity.color(node),
        select: node => { selectedFocusId = node.id; selectedNodeIds = new Set(gpu.selection()); showDetail(node); updateFocusControl(); if (activeFilter.hops) applyFilter(); },
        fallback: () => { gpuUnavailable = true; renderFallback(latestGraph); },
      });
      root.querySelector("[data-map-arrange]").disabled = false;
      applyFilter = () => filterWithoutSVG(graph);
      if (previous && refreshing) gpu.restore(previous);
      applyFilter();
      if (!refreshing) {
        const params = new URLSearchParams(location.search);
        const wanted = graph.nodes.find(node => node.id === params.get("node") ||
          params.get("thread") && node.metadata?.thread_id === params.get("thread"));
        if (wanted) { gpu.select(wanted.id); gpu.focus(wanted.id); }
      }
    } catch (_) { gpuUnavailable = true; renderFallback(graph); }
  };
  const render = (graph, refreshing = false, initialReflow = false) => {
    const ids = new Set(graph.nodes.map(node => node.id));
    selectedNodeIds = new Set([...selectedNodeIds].filter(id => ids.has(id)));
    if (selectedFocusId && !ids.has(selectedFocusId)) {
      selectedFocusId = null;
      detailTitle.textContent = t("map.no_selection"); detailText.textContent = t("map.pick_hint"); detailMeta.hidden = true;
      root.querySelector("[data-map-detail-activity]").textContent = "";
      root.querySelector("[data-map-fix-selected]").disabled = true;
      root.querySelector("[data-map-trash]").hidden = true;
      root.dispatchEvent(new CustomEvent("threaddesk:node-selected", {detail: {id: null}}));
    }
    if (graph.nodes.length >= 128) {
      if (gpuUnavailable) renderFallback(graph); else renderGPU(graph, refreshing);
      return;
    }
    if (gpu) { gpu.destroy(); gpu = null; }
    root.dataset.renderer = "svg"; canvas.hidden = false;
    root.querySelector("[data-map-arrange]").disabled = true;
    const selectedIds = refreshing ? [...selectedNodeIds] : [];
    const previousPositions = placed;
    updateLabels = () => {};
    world.replaceChildren();
    canvas.querySelector("defs")?.remove();
    canvas.insertBefore(defs(), canvas.firstChild);
    empty.hidden = graph.nodes.length !== 0;
    summary.textContent = t("map.nodes_relations", {
      nodes: graph.counts.nodes, relations: graph.counts.relations,
    });
    activity.update(graph, activeFilter.mode);
    if (!refreshing || initialReflow) {
      // The summary itself may wrap and change the available stage height.
      resizeStage();
      layoutWindow = {width: window.innerWidth, height: window.innerHeight};
    }

    world.appendChild(backdrop());
    placed = layout(graph.nodes, graph.relations, refreshing && !initialReflow ? previousPositions : new Map());
    if (refreshing && !initialReflow && previousPositions) {
      previousPositions.forEach((point, id) => { if (placed.has(id)) placed.set(id, point); });
    }
    sizes = new Map(graph.nodes.map((node) => [node.id, radiusOf(node)]));

    const edgeLayer = el("g", {class: "map-edges", "data-map-edges": ""});
    const nodeLayer = el("g", {class: "map-nodes", "data-map-nodes": ""});
    world.append(edgeLayer, nodeLayer);

    const edges = [];
    graph.relations.forEach((relation) => {
      const from = placed.get(relation.source_id);
      const to = placed.get(relation.target_id);
      if (!from || !to) return;
      const style = EDGE[relation.kind] || EDGE.related_to;
      const path = el("path", {
        class: `map-edge map-edge-${style.tone}${style.flow ? " map-edge-flow" : ""}`,
        d: edgePath(from, to, sizes.get(relation.source_id), sizes.get(relation.target_id)),
        "stroke-width": style.width,
        "stroke-dasharray": style.dash,
        "marker-end": style.arrow ? `url(#map-arrow-${style.tone})` : null,
        "data-relation": relation.kind,
      });
      const label = el("title");
      label.textContent = relation.kind;
      path.appendChild(label);
      edgeLayer.appendChild(path);
      edges.push({path, relation, style});
    });


    graph.nodes.forEach((node) => {
      const point = placed.get(node.id);
      const tone = toneOf(node);
      const appearance = ACTORS[node.metadata?.actor_id];
      const ai = node.kind === "agent" || Boolean(appearance?.ai);
      const group = el("g", {
        class: `map-node map-node-${shapeOf(node)} map-tone-${tone}${ai ? " is-ai" : ""}`,
        transform: `translate(${point.x.toFixed(1)} ${point.y.toFixed(1)})`,
        tabindex: "-1", role: "button",
        "data-status": node.status, "data-kind": node.kind, "data-tone": tone,
        "data-node-id": node.id,
        "aria-label": `${node.title}, ${node.kind}, ${node.status}`,
      });
      const threadId = node.metadata && node.metadata.thread_id;
      if (typeof threadId === "string" && threadId) group.dataset.threadId = threadId;
      const halo = outline(node);
      halo.setAttribute("class", "map-node-halo");
      const shape = outline(node);
      shape.setAttribute("class", "map-node-shape");
      const ring = ai ? outline(node) : null;
      if (ring) ring.setAttribute("class", "map-node-ai-ring");
      // Symbol im Symbol: der Typ bleibt auch ohne Farbe erkennbar.
      const glyph = el("path", {class: "map-node-glyph", d: GLYPH[node.kind] || GLYPH.project});
      const [mx, my] = MARK_AT[shapeOf(node)] || MARK_AT.circle;
      const mark = el("g", {class: "map-node-mark", transform: `translate(${mx} ${my})`});
      mark.appendChild(el("circle", {class: "map-node-mark-disc", r: 8}));
      mark.appendChild(el("path", {class: "map-node-mark-sign", d: MARK[tone] || MARK.idle}));
      const hit = el("rect", {class: "map-node-hit", fill: "transparent", "pointer-events": "all"});
      group.append(hit, halo, shape, glyph, mark, caption(node.title));
      if (appearance) {
        const badge = el("g", {class: "map-node-actor-mark",
          transform: `translate(${-mx} ${my})`, "data-actor-tone": appearance.color_token,
          "pointer-events": "none"});
        badge.appendChild(el("circle", {r: 6, fill: ACTOR_COLORS[appearance.color_token] || "#8b909a",
          stroke: "#04070a", "stroke-width": 1}));
        const actorTitle = el("title");
        actorTitle.textContent = appearance.name || appearance.label || node.metadata.actor_id;
        badge.appendChild(actorTitle);
        group.appendChild(badge);
      }
      const title = el("title");
      title.textContent = node.title;
      group.appendChild(title);
      group.dataset.fixed = String(fixedIds.has(node.id));
      activity.decorate(group, node);
      group.addEventListener("focus", () => updateLabels());
      group.addEventListener("blur", () => updateLabels());
      group.addEventListener("pointerenter", () => { group.classList.add("is-hovered"); updateLabels(); });
      group.addEventListener("pointerleave", () => { group.classList.remove("is-hovered"); updateLabels(); });
      if (ring) group.insertBefore(ring, glyph);

      const select = (additive = false) => {
        if (!additive) {
          nodeLayer.querySelectorAll(".is-selected")
            .forEach((item) => item.classList.remove("is-selected"));
        }
        group.classList.toggle("is-selected");
        selectedNodeIds = new Set([...nodeLayer.querySelectorAll(".is-selected")].map(item => item.dataset.nodeId));
        selectedFocusId = node.id;
        showDetail(node);
        highlight();
        if (activeFilter.hops) applyFilter();
        // Selection must not move the other click targets out of the viewport.
        // Explicit deep-link navigation below still focuses its destination.
      };
      group.addEventListener("click", (event) => {
        if (nodeDrag && nodeDrag.moved) return;
        select(event.shiftKey);
      });
      group.addEventListener("keydown", (event) => {
        if (["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "Home", "End"].includes(event.key)) {
          event.preventDefault();
          const nodes = [...nodeLayer.querySelectorAll(".map-node")].filter(item => item.style.display !== "none");
          const index = nodes.indexOf(group);
          const next = event.key === "Home" ? 0 : event.key === "End" ? nodes.length - 1 :
            (index + (["ArrowRight", "ArrowDown"].includes(event.key) ? 1 : -1) + nodes.length) % nodes.length;
          nodes.forEach(item => item.tabIndex = -1); nodes[next].tabIndex = 0; nodes[next].focus();
          return;
        }
        if (event.key !== "Enter" && event.key !== " ") return;
        event.preventDefault();
        select(event.shiftKey);
      });
      // Knoten lassen sich verschieben; erst ab 3 px gilt es als Ziehen,
      // damit der Klick zum Auswählen erhalten bleibt.
      group.addEventListener("pointerdown", (event) => {
        if (fixedIds.has(node.id)) return;
        nodeDrag = {
          id: node.id, group, moved: false,
          start: toUser(event.clientX, event.clientY),
          origin: {x: point.x, y: point.y},
          screen: {x: event.clientX, y: event.clientY},
        };
        event.stopPropagation();
      });
      nodeLayer.appendChild(group);
    });

    const redrawEdges = () => {
      edges.forEach(({path, relation}) => {
        const from = placed.get(relation.source_id);
        const to = placed.get(relation.target_id);
        if (!from || !to) return;
        path.setAttribute("d", edgePath(
          from, to, sizes.get(relation.source_id), sizes.get(relation.target_id)));
      });
    };

    // Auswahl hebt ihre Verbindungen hervor und dämpft den Rest.
    const highlight = () => {
      const chosen = new Set([...nodeLayer.querySelectorAll(".is-selected")]
        .map((item) => item.dataset.nodeId));
      root.classList.toggle("has-selection", chosen.size > 0);
      edges.forEach(({path, relation}) => {
        const touched = chosen.has(relation.source_id) || chosen.has(relation.target_id);
        path.classList.toggle("is-linked", chosen.size > 0 && touched);
      });
      nodeLayer.querySelectorAll(".map-node").forEach((item) => {
        const id = item.dataset.nodeId;
        const near = chosen.has(id) || edges.some(({relation}) =>
          (relation.source_id === id && chosen.has(relation.target_id))
          || (relation.target_id === id && chosen.has(relation.source_id)));
        item.classList.toggle("is-near", chosen.size > 0 && near);
      });
      updateFocusControl();
      updateLabels();
    };

    const labels = window.ThreadDeskMapLabels(nodeLayer, {
      shapes, viewport, positions: () => placed,
      dimensions: () => ({width: VIEW_W, height: VIEW_H}),
      camera: () => ({scale, offsetX, offsetY}),
    });
    updateLabels = labels.update; invalidateLabelWidths = labels.invalidate;
    applyFilter = () => {
      activity.update(graph, activeFilter.mode);
      const visible = window.ThreadDeskGraphFilter(graph, activeFilter, activity, selectedFocusId);
      graph.nodes.forEach(node => {
        const matches = visible.has(node.id);
        const group = nodeLayer.querySelector(`[data-node-id="${CSS.escape(node.id)}"]`);
        activity.decorate(group, node);
        group.style.display = matches ? "" : "none";
        group.setAttribute("tabindex", "-1");
        group.setAttribute("aria-hidden", String(!matches));
        if (matches) visible.add(node.id);
      });
      const keyboardTarget = (selectedFocusId && visible.has(selectedFocusId)) ? selectedFocusId : [...visible][0];
      if (keyboardTarget) nodeLayer.querySelector(`[data-node-id="${CSS.escape(keyboardTarget)}"]`).setAttribute("tabindex", "0");
      edges.forEach(({path, relation}) => {
        path.style.display = visible.has(relation.source_id) && visible.has(relation.target_id) ? "" : "none";
      });
      empty.hidden = visible.size !== 0;
      empty.textContent = activeFilter.query || activeFilter.kind || activeFilter.project_id || activeFilter.status || activeFilter.band ? t("map.no_matches") : t("map.empty");
      updateFocusControl();
      updateLabels();
      root.dispatchEvent(new CustomEvent("threaddesk:graph-filtered", {
        bubbles: true, detail: {visible: visible.size, total: graph.nodes.length, ids: [...visible]},
      }));
    };
    applyFilter();

    root.__mapDrag = (event) => {
      if (!nodeDrag) return false;
      const moved = Math.hypot(event.clientX - nodeDrag.screen.x,
                               event.clientY - nodeDrag.screen.y);
      if (!nodeDrag.moved && moved < 3) return true;
      nodeDrag.moved = true;
      const now = toUser(event.clientX, event.clientY);
      const point = placed.get(nodeDrag.id);
      point.x = nodeDrag.origin.x + (now.x - nodeDrag.start.x) / scale;
      point.y = nodeDrag.origin.y + (now.y - nodeDrag.start.y) / scale;
      nodeDrag.group.setAttribute(
        "transform", `translate(${point.x.toFixed(1)} ${point.y.toFixed(1)})`);
      redrawEdges();
      updateLabels();
      return true;
    };
    if (refreshing) {
      selectedIds.forEach(id => nodeLayer.querySelector(`[data-node-id="${CSS.escape(id)}"]`)?.classList.add("is-selected"));
      const current = graph.nodes.find(node => selectedIds.includes(node.id));
      if (current) showDetail(current, false);
      highlight();
      if (initialReflow) {
        fit();
        if (current) {
          const point = placed.get(current.id);
          offsetX = VIEW_W / 2 - scale * point.x;
          offsetY = VIEW_H / 2 - scale * point.y;
        }
      }
      applyTransform();
      return;
    }
    fit();
    const params = new URLSearchParams(window.location.search);
    const wantedNode = params.get("node");
    const wantedThread = params.get("thread");
    if (wantedNode || wantedThread) {
      const chosen = graph.nodes.filter((node) => {
        const linked = node.metadata && node.metadata.thread_id;
        return wantedNode ? node.id === wantedNode : linked === wantedThread;
      });
      chosen.forEach((node) => {
        const item = nodeLayer.querySelector(`[data-node-id="${CSS.escape(node.id)}"]`);
        if (item) item.classList.add("is-selected");
      });
      if (chosen.length) {
        selectedFocusId = chosen[0].id;
        selectedNodeIds = new Set(chosen.map(node => node.id));
        showDetail(chosen[0]);
        highlight();
        const point = placed.get(chosen[0].id);
        if (point) focusOn(point);
      }
    }
  };

  root.addEventListener("threaddesk:graph-filter", event => {
    noteInteraction();
    const detail = event.detail || {};
    activeFilter = {query: String(detail.query || ""), kind: String(detail.kind || ""),
      project_id: String(detail.project_id || ""), status: String(detail.status || ""),
      mode: detail.mode || "work", band: detail.band || "", hops: Number(detail.hops || 0)};
    applyFilter();
    const selected = latestGraph?.nodes.find(node => node.id === selectedFocusId);
    if (selected) activity.details(selected);
    if (serverPaging && detail.server_query !== false) { pageOffset = 0; refreshGraph(); }
  });
  root.addEventListener("threaddesk:graph-select-request", event => {
    const id = event.detail?.id;
    if (gpu) { gpu.select(id, Boolean(event.detail?.additive)); return; }
    if (root.dataset.renderer === "list") {
      const node = latestGraph?.nodes.find(item => item.id === id);
      if (node) {
        if (!event.detail?.additive) selectedNodeIds.clear();
        selectedNodeIds.add(id); selectedFocusId = id; showDetail(node);
      }
      return;
    }
    const group = [...world.querySelectorAll("[data-node-id]")].find(item => item.dataset.nodeId === id);
    group?.dispatchEvent(new MouseEvent("click", {bubbles: true, shiftKey: Boolean(event.detail?.additive)}));
  });
  const focusFirstMatch = () => {
    if (gpu) {
      const ids = window.ThreadDeskGraphFilter(latestGraph, activeFilter, activity, selectedFocusId);
      if (ids.size) gpu.focus([...ids][0]);
      return;
    }
    const group = [...world.querySelectorAll("[data-node-id]")].find(item => item.style.display !== "none");
    if (group) { scale = Math.max(1, scale); focusOn(placed.get(group.dataset.nodeId)); }
  };
  root.addEventListener("threaddesk:graph-search-submit", () => {
    if (serverPaging) pendingSearchFocus = true; else focusFirstMatch();
  });
  root.querySelector("[data-map-fix-selected]")?.addEventListener("click", () => {
    if (!selectedFocusId) return;
    if (fixedIds.has(selectedFocusId)) fixedIds.delete(selectedFocusId); else fixedIds.add(selectedFocusId);
    const group = world.querySelector(`[data-node-id="${CSS.escape(selectedFocusId)}"]`);
    if (group) group.dataset.fixed = String(fixedIds.has(selectedFocusId));
    if (gpu) { gpu.stopLayout(); applyFilter(); }
    root.querySelector("[data-map-fix-selected]").textContent = t(fixedIds.has(selectedFocusId) ? "map.unfix_selected" : "map.fix_selected");
  });
  root.querySelector("[data-map-arrange]")?.addEventListener("click", () => {
    gpu?.arrange().catch(() => {
      gpu?.stopLayout(); summary.textContent = t("map.worker_unavailable");
    });
  });
  root.graphController = {
    refresh: canApply => refreshGraph(false, canApply),
    interacting: () => Boolean(drag || nodeDrag || root.dataset.layoutRunning === "true"),
    nodePoint: id => gpu ? gpu.point(id) : placed.has(id) ? {
      x: offsetX + scale * placed.get(id).x, y: offsetY + scale * placed.get(id).y,
    } : null,
    labelMetrics: () => gpu ? gpu.labelMetrics() : null,
    snapshot: () => ({camera: gpu ? gpu.camera() : {x: (VIEW_W / 2 - offsetX) / scale, y: (VIEW_H / 2 - offsetY) / scale, scale}, filters: {...activeFilter},
      positions: gpu ? gpu.snapshotPositions() : Object.fromEntries([...placed].map(([id, point]) => [id, {x: point.x, y: point.y, fixed: fixedIds.has(id)}])),
      selection: [...selectedNodeIds]}),
    restore: async state => {
      if (!latestGraph) return;
      noteInteraction(); cancelFocus();
      const wanted = [...new Set([...Object.keys(state.positions || {}), ...(state.selection || [])])];
      if (wanted.some(id => !latestGraph.nodes.some(node => node.id === id))) {
        if (wanted.length > 1000) throw Error("view_graph_limit");
        const response = await window.threadDeskWrite('/api/graph/v2', {
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({node_ids: wanted, mode: state.filters?.mode || 'work', limit: 1000})});
        if (!response.ok) throw Error("view_graph_unavailable");
        const graph = await response.json();
        if (graph.nodes.length !== wanted.length) throw Error("view_nodes_unavailable");
        if (graph.nodes.length >= 128 && !gpuUnavailable) {
          try { await window.ThreadDeskGraphGPU.load(); } catch (_) { gpuUnavailable = true; }
        }
        latestGraph = graph; serverPaging = true; pageOffset = 0; render(graph, true);
        root.dispatchEvent(new CustomEvent('threaddesk:graph-loaded', {detail: {nodes: graph.nodes, graph}}));
      }
      const ids = new Set(latestGraph.nodes.map(node => node.id));
      selectedNodeIds = new Set((state.selection || []).filter(id => ids.has(id)));
      const points = Object.entries(state.positions || {}).filter(([id]) => ids.has(id));
      if (gpu) placed = new Map(Object.entries(gpu.snapshotPositions()));
      points.forEach(([id, point]) => {
        placed.set(id, {x: point.x, y: point.y});
        if (point.fixed) fixedIds.add(id); else fixedIds.delete(id);
      });
      activeFilter = {...activeFilter, ...state.filters};
      if (gpu) { gpu.restore(state); applyFilter(); return; }
      render(latestGraph, true);
      world.querySelectorAll(".is-selected").forEach(item => item.classList.remove("is-selected"));
      let additive = false;
      for (const id of state.selection || []) {
        if (!ids.has(id)) continue;
        root.dispatchEvent(new CustomEvent("threaddesk:graph-select-request", {detail: {id, additive}}));
        additive = true;
      }
      scale = clamp(state.camera.scale);
      offsetX = VIEW_W / 2 - state.camera.x * scale; offsetY = VIEW_H / 2 - state.camera.y * scale;
      applyTransform();
    },
  };
  // One bounded correction catches a late native WINDOW resize before input.
  // Our own header/inspector changes only preserve camera and positions.
  const scheduleStartupCorrection = () => {
    if (!initialDrawn || hasInteraction || startupCorrectionUsed || correctionPending ||
        !windowGeometryChanged() || performance.now() > startupDeadline) return;
    clearTimeout(startupTimer);
    startupTimer = setTimeout(async () => {
      correctionPending = true;
      try {
        await viewport.stable(stage);
        if (hasInteraction || startupCorrectionUsed || !latestGraph ||
            !windowGeometryChanged() || performance.now() > startupDeadline) return;
        startupCorrectionUsed = true;
        render(latestGraph, true, true);
      } catch (_) { /* keep the last usable graph if the window never settles */ }
      finally { correctionPending = false; }
    }, 180);
  };
  const resizeStage = () => {
    if (gpu) return;
    const width = Math.max(1, stage.clientWidth);
    const height = Math.max(1, stage.clientHeight);
    if (width === VIEW_W && height === VIEW_H) return;
    cancelFocus();
    const next = viewport.resize({x: offsetX, y: offsetY},
      {width: VIEW_W, height: VIEW_H}, {width, height});
    offsetX = next.x; offsetY = next.y;
    VIEW_W = width; VIEW_H = height;
    canvas.setAttribute("viewBox", `0 0 ${width} ${height}`);
    applyTransform();
    scheduleStartupCorrection();
  };
  if (window.ResizeObserver) new ResizeObserver(resizeStage).observe(stage);
  else window.addEventListener("resize", resizeStage);

  // ---------------------------------------------------------------- Bedienung
  root.querySelector("[data-map-zoom-in]").addEventListener("click", () => zoom(1.25));
  root.querySelector("[data-map-zoom-out]").addEventListener("click", () => zoom(1 / 1.25));
  root.querySelector("[data-map-reset]").addEventListener("click", fit);
  focusSelectionControl?.addEventListener("click", () => {
    if (gpu) { const ids = gpu.selection(); if (ids.length) gpu.focus(ids[0]); return; }
    const selected = [...world.querySelectorAll(".is-selected[data-node-id]")]
      .filter(node => node.style.display !== "none");
    const target = selected.find(node => node.dataset.nodeId === selectedFocusId) || selected[0];
    if (!target) return;
    scale = Math.max(1, scale);
    focusOn(placed.get(target.dataset.nodeId));
  });
  updateFocusControl();
  stage.addEventListener("wheel", (event) => {
    if (gpu) return;
    event.preventDefault();
    zoomAt(event.deltaY < 0 ? 1.12 : 1 / 1.12, toUser(event.clientX, event.clientY));
  }, {passive: false});

  const DRAG_THRESHOLD = 3;
  stage.addEventListener("pointerdown", (event) => {
    if (gpu || nodeDrag) return;
    cancelFocus();
    drag = {
      x: event.clientX, y: event.clientY, offsetX, offsetY,
      pointerId: event.pointerId, panning: false,
    };
  });
  stage.addEventListener("pointermove", (event) => {
    if (root.__mapDrag && root.__mapDrag(event)) return;
    if (!drag) return;
    const dx = event.clientX - drag.x;
    const dy = event.clientY - drag.y;
    if (!drag.panning) {
      if (Math.hypot(dx, dy) < DRAG_THRESHOLD) return;
      // Den Zeiger erst beim echten Ziehen einfangen. Ein Capture schon beim
      // pointerdown leitet auch den anschließenden Klick an die Bühne um —
      // dann lässt sich kein Knoten mehr auswählen.
      drag.panning = true;
      stage.setPointerCapture(drag.pointerId);
      stage.classList.add("is-panning");
    }
    const ratio = pixelsPerUser();
    offsetX = drag.offsetX + dx / ratio;
    offsetY = drag.offsetY + dy / ratio;
    applyTransform();
  });
  const endDrag = () => {
    if (drag && drag.panning && stage.hasPointerCapture(drag.pointerId)) {
      stage.releasePointerCapture(drag.pointerId);
    }
    drag = null;
    stage.classList.remove("is-panning");
    if (nodeDrag) window.setTimeout(() => { nodeDrag = null; }, 0);
  };
  stage.addEventListener("pointerup", endDrag);
  stage.addEventListener("pointercancel", endDrag);

  // Effekte sind abschaltbar und starten aus, wenn das System weniger
  // Bewegung verlangt.
  const calm = window.matchMedia("(prefers-reduced-motion: reduce)");
  const setEffects = (on) => {
    root.classList.toggle("effects-off", !on);
    if (effectsToggle) {
      effectsToggle.setAttribute("aria-pressed", String(on));
      effectsToggle.textContent = on ? t("map.effects_on") : t("map.effects_off");
    }
  };
  setEffects(!calm.matches);
  calm.addEventListener?.("change", (event) => setEffects(!event.matches));
  effectsToggle?.addEventListener("click", () => {
    setEffects(root.classList.contains("effects-off"));
  });

  document.fonts?.addEventListener?.("loadingdone", () => {
    invalidateLabelWidths();
    updateLabels();
  });
  const pageReady = viewport.ready(stage);
  pageReady.catch(() => {}); // the request path below presents the error state
  let refreshTicket = 0;
  async function refreshGraph(fitPage = false, canApply = () => true) {
    const ticket = ++refreshTicket;
    try {
      const address = new URL(root.dataset.graphEndpoint, location.href);
      if (serverPaging) {
        Object.entries(activeFilter).forEach(([key, value]) => address.searchParams.set(key, String(value)));
        address.searchParams.set("offset", String(pageOffset));
        if (selectedFocusId && activeFilter.hops) address.searchParams.set("center", selectedFocusId);
      }
      const response = await fetch(address, {headers: {Accept: "application/json"}, cache: "no-store"});
      if (!response.ok) throw new Error("graph request failed");
      const graph = await response.json();
      await pageReady;
      if (ticket !== refreshTicket) return false;
      resizeStage();
      if (graph.nodes.length >= 128 && !gpuUnavailable) {
        try { await window.ThreadDeskGraphGPU.load(); }
        catch (_) { gpuUnavailable = true; }
      }
      if (!canApply()) return false;
      latestGraph = graph;
      serverPaging ||= graph.next_offset != null;
      const wasDrawn = initialDrawn;
      render(graph, wasDrawn);
      if (fitPage) fit();
      if (pendingSearchFocus) { pendingSearchFocus = false; focusFirstMatch(); }
      if (!wasDrawn) {
        initialDrawn = true;
        startupDeadline = performance.now() + 2500;
      }
      error.hidden = true;
      root.dispatchEvent(new CustomEvent("threaddesk:graph-loaded", {
        bubbles: true, detail: {nodes: graph.nodes, graph},
      }));
      return true;
    } catch (_) { if (ticket === refreshTicket) error.hidden = false; return false; }
  }
  document.addEventListener("threaddesk:library-changed", () => {
    noteInteraction();
    refreshGraph();
  });
  root.querySelector("[data-map-graph-next]")?.addEventListener("click", () => {
    if (latestGraph?.next_offset == null) return;
    pageOffset = latestGraph.next_offset; refreshGraph(true);
  });
  root.querySelector("[data-map-graph-previous]")?.addEventListener("click", () => {
    pageOffset = Math.max(0, pageOffset - (latestGraph?.filters?.limit || 1000)); refreshGraph(true);
  });
  refreshGraph();
})();
