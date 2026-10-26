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
  const viewport = window.ThreadDeskMapViewport;
  const MIN_SCALE = 0.04;
  const MAX_SCALE = 4;
  let VIEW_W = Math.max(1, stage.clientWidth);
  let VIEW_H = Math.max(1, stage.clientHeight);
  canvas.setAttribute("viewBox", `0 0 ${VIEW_W} ${VIEW_H}`);

  // ---------------------------------------------------------------- Sprache
  // Form trägt den Typ, Farbe den Zustand. Farbe ist nie das einzige Signal:
  // jeder Knoten hat zusätzlich Form, Glyphe und Beschriftung.
  const SHAPE = {
    project: "circle", agent: "circle", person: "circle",
    task: "rect",
    decision: "doc", result: "doc", document: "doc",
    tool: "hex", source: "hex", workflow: "hex",
  };
  const TONE = {
    confirmed: "good", accepted: "good", verified: "good", active: "good",
    done: "good",
    proposed: "wait", review: "wait", waiting: "wait", ready: "wait",
    assigned: "wait", candidate: "wait", idea: "wait",
    blocked: "risk", rejected: "risk",
    paused: "idle", archived: "idle", superseded: "idle",
    delivered: "fresh", unverified: "fresh", in_progress: "fresh",
    rework: "fresh",
  };
  // Gerichtete Beziehungen bekommen eine Spitze, unsichere eine gestrichelte
  // Linie. Die Stärke bleibt überall ein Haarstrich; Bedeutung liegt in Farbe.
  const EDGE = {
    contains:    {tone: "soft",  width: 1, dash: null,    arrow: false, flow: false},
    depends_on:  {tone: "bold",  width: 1, dash: null,    arrow: true,  flow: false},
    blocks:      {tone: "risk",  width: 1, dash: null,    arrow: true,  flow: false},
    assigned_to: {tone: "soft",  width: 1, dash: "7 6",   arrow: true,  flow: false},
    produced:    {tone: "fresh", width: 1, dash: null,    arrow: true,  flow: true},
    follows:     {tone: "fresh", width: 1, dash: null,    arrow: true,  flow: true},
    supports:    {tone: "good",  width: 1, dash: null,    arrow: true,  flow: false},
    references:  {tone: "soft",  width: 1, dash: "3 7",   arrow: false, flow: false},
    related_to:  {tone: "soft",  width: 1, dash: "3 7",   arrow: false, flow: false},
  };
  const GLYPH = {
    project: "M-9-7h7l2 3h9v11h-18z",
    task: "M-8 0l5 5 10-10",
    decision: "M0-9l9 9-9 9-9-9z",
    result: "M-9 3l6 6 12-14",
    person: "M0-4a4 4 0 100-8 4 4 0 000 8zM-8 9a8 8 0 0116 0z",
    agent: "M-8-6h16v11h-16zM-4 9h8M0-11v5",
    document: "M-6-9h8l4 4v14h-12z",
    tool: "M6-9l-5 5 3 3 5-5a5 5 0 01-8 6l-6 6 3 3 6-6a5 5 0 016-8z",
    source: "M0-9a9 9 0 100 18 9 9 0 000-18zM-9 0h18M0-9c5 5 5 13 0 18",
    workflow: "M-9-5h7v10h11M6-9l4 4-4 4",
  };
  const SIZE = {circle: 34, rect: [64, 24], doc: [50, 32], hex: 34};
  // Der Bauplan verlangt: Farbe ist nie das einzige Signal. Jeder Zustand
  // bekommt daher zusätzlich eine kleine Marke am Knoten.
  const MARK = {
    good:  "M-3.5 0l2.5 2.5 4.5-5",
    wait:  "M0-3.2a3.2 3.2 0 100 6.4 3.2 3.2 0 000-6.4",
    fresh: "M-4 1c1.6-3 3-3 4 0s2.4 3 4 0",
    risk:  "M0-4.5v5M0 3.4v.2",
    idle:  "M-2-3.4v6.8M2-3.4v6.8",
  };
  const MARK_AT = {circle: [24, -24], hex: [24, -22], rect: [58, -28], doc: [44, -34]};

  const shapeOf = (node) => SHAPE[node.kind] || "circle";
  const toneOf = (node) => TONE[node.status] || "idle";
  const radiusOf = (node) => {
    const shape = shapeOf(node);
    if (shape === "rect") return Math.hypot(...SIZE.rect);
    if (shape === "doc") return Math.hypot(...SIZE.doc);
    return SIZE[shape];
  };

  // ---------------------------------------------------------------- Layout
  // Bestätigte Beziehungen ordnen eine ruhige, lesbare Anfangsansicht.
  // Bereits gesetzte Positionen bleiben bei Aktualisierungen erhalten.
  const layout = (nodes, relations, previous = new Map()) =>
    window.ThreadDeskMapLayout(nodes, relations,
      {width: VIEW_W, height: VIEW_H, radiusOf, previous});

  // ---------------------------------------------------------------- Zeichnen
  const el = (name, attrs = {}) => {
    const node = document.createElementNS(svgNS, name);
    Object.entries(attrs).forEach(([key, value]) => {
      if (value !== null && value !== undefined) node.setAttribute(key, value);
    });
    return node;
  };

  const outline = (node) => {
    const shape = shapeOf(node);
    if (shape === "rect") {
      const [w, h] = SIZE.rect;
      return el("rect", {x: -w, y: -h, width: w * 2, height: h * 2, rx: 8});
    }
    if (shape === "doc") {
      const [w, h] = SIZE.doc;
      const fold = 16;
      return el("path", {d: `M${-w} ${-h}H${w - fold}L${w} ${-h + fold}V${h}H${-w}Z`});
    }
    if (shape === "hex") {
      const r = SIZE.hex;
      const points = [];
      for (let i = 0; i < 6; i += 1) {
        const a = (Math.PI / 3) * i - Math.PI / 6;
        points.push(`${(Math.cos(a) * r).toFixed(1)},${(Math.sin(a) * r).toFixed(1)}`);
      }
      return el("polygon", {points: points.join(" ")});
    }
    return el("circle", {r: SIZE.circle});
  };

  // Beschriftung unter den Knoten, damit nichts abgeschnitten wird.
  const caption = (title) => {
    const group = el("g", {class: "map-label"});
    group.appendChild(el("rect", {class: "map-label-hit", fill: "transparent", "pointer-events": "all"}));
    const words = title.split(/\s+/).flatMap(word => word.match(/.{1,24}/g) || []);
    const lines = [];
    let line = "";
    words.forEach(word => {
      const candidate = line ? `${line} ${word}` : word;
      if (candidate.length > 24 && line) { lines.push(line); line = word; }
      else line = candidate;
    });
    if (line) lines.push(line);
    if (lines.length > 2) lines[1] = `${lines[1].slice(0, 23)}…`;
    lines.slice(0, 2).forEach((text, index) => {
      const item = el("text", {"text-anchor": "middle", y: index * 16});
      item.textContent = text;
      group.appendChild(item);
    });
    const fullTitle = el("title");
    fullTitle.textContent = title;
    group.appendChild(fullTitle);
    return group;
  };

  const defs = () => {
    const box = el("defs");
    box.innerHTML = `
      <radialGradient id="map-vignette" cx="50%" cy="45%" r="72%">
        <stop offset="0%" stop-color="#0d2029"/>
        <stop offset="60%" stop-color="#070f14"/>
        <stop offset="100%" stop-color="#03060a"/>
      </radialGradient>
      <pattern id="map-grid" width="46" height="46" patternUnits="userSpaceOnUse">
        <path d="M46 0H0V46" fill="none" stroke="#142a33" stroke-width="1"/>
      </pattern>
      <filter id="map-glow" x="-70%" y="-70%" width="240%" height="240%">
        <feGaussianBlur stdDeviation="7" result="blur"/>
        <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
      </filter>
      <filter id="map-edge-glow" x="-40%" y="-40%" width="180%" height="180%">
        <feGaussianBlur stdDeviation="2.2" result="blur"/>
        <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
      </filter>`;
    ["soft", "bold", "good", "fresh", "risk"].forEach((tone) => {
      const marker = el("marker", {
        id: `map-arrow-${tone}`, class: `map-arrow map-arrow-${tone}`,
        viewBox: "0 0 10 10", refX: "9", refY: "5",
        markerWidth: "5.5", markerHeight: "5.5", orient: "auto-start-reverse",
      });
      marker.appendChild(el("path", {d: "M0 1l8 4-8 4z"}));
      box.appendChild(marker);
    });
    return box;
  };

  const backdrop = () => {
    const group = el("g", {class: "map-backdrop", "aria-hidden": "true"});
    const pad = 800;
    group.appendChild(el("rect", {
      x: -pad, y: -pad, width: VIEW_W + pad * 2, height: VIEW_H + pad * 2,
      fill: "url(#map-vignette)",
    }));
    group.appendChild(el("rect", {
      x: -pad, y: -pad, width: VIEW_W + pad * 2, height: VIEW_H + pad * 2,
      fill: "url(#map-grid)", opacity: "0.5",
    }));
    return group;
  };

  // Kante endet am Rand der Form, damit die Spitze nicht im Knoten steckt.
  const edgePath = (from, to, fromR, toR) => {
    const dx = to.x - from.x;
    const dy = to.y - from.y;
    const dist = Math.hypot(dx, dy) || 1;
    const ux = dx / dist;
    const uy = dy / dist;
    const x1 = from.x + ux * (fromR + 3);
    const y1 = from.y + uy * (fromR + 3);
    const x2 = to.x - ux * (toR + 9);
    const y2 = to.y - uy * (toR + 9);
    const mx = (x1 + x2) / 2 - (y2 - y1) * 0.12;
    const my = (y1 + y2) / 2 + (x2 - x1) * 0.12;
    return `M${x1.toFixed(1)} ${y1.toFixed(1)}Q${mx.toFixed(1)} ${my.toFixed(1)} ${x2.toFixed(1)} ${y2.toFixed(1)}`;
  };

  let scale = 1;
  let offsetX = 0;
  let offsetY = 0;
  let drag = null;
  let nodeDrag = null;
  let placed = new Map();
  let sizes = new Map();
  let updateLabels = () => {};
  let applyFilter = () => {};
  let activeFilter = {query: "", kind: "", project_id: ""};
  let focusTicket = 0;
  const cancelFocus = () => {
    focusTicket += 1;
    root.classList.remove("is-focusing");
  };
  let selectedFocusId = null;
  const focusSelectionControl = root.querySelector("[data-map-focus-selection]");
  const updateFocusControl = () => {
    if (!focusSelectionControl) return;
    const selected = [...world.querySelectorAll(".is-selected[data-node-id]")]
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
  const zoom = (factor) => zoomAt(factor, stageCentre());
  // Einpassen heißt einpassen: der ganze Graph muss sichtbar werden.
  const fit = () => {
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

  const render = (graph, refreshing = false) => {
    const selectedIds = refreshing ? [...world.querySelectorAll(".is-selected[data-node-id]")].map(item => item.dataset.nodeId) : [];
    const previousPositions = placed;
    updateLabels = () => {};
    world.replaceChildren();
    canvas.querySelector("defs")?.remove();
    canvas.insertBefore(defs(), canvas.firstChild);
    empty.hidden = graph.nodes.length !== 0;
    summary.textContent = t("map.nodes_relations", {
      nodes: graph.counts.nodes, relations: graph.counts.relations,
    });

    world.appendChild(backdrop());
    placed = layout(graph.nodes, graph.relations, refreshing ? previousPositions : new Map());
    if (refreshing && previousPositions) {
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

    const showDetail = (node, notify = true) => {
      if (notify) root.dispatchEvent(new CustomEvent("threaddesk:node-selected", {detail: {id: node.id, thread_id: node.metadata?.thread_id}}));
      detailTitle.textContent = node.title;
      detailText.textContent = node.details || t("map.no_details");
      detailMeta.hidden = false;
      detailMeta.replaceChildren();
      [[t("map.field_kind"), node.kind],
       [t("map.field_status"), node.status],
       [t("map.field_source"), node.source],
       [t("map.field_visibility"), node.visibility],
       [t("map.field_revision"), node.revision]]
        .forEach(([term, value]) => {
          const item = document.createElement("div");
          const dt = document.createElement("dt");
          const dd = document.createElement("dd");
          dt.textContent = term;
          dd.textContent = value;
          item.append(dt, dd);
          detailMeta.appendChild(item);
        });
      const threadId = node.metadata && node.metadata.thread_id;
      if (typeof threadId === "string" && threadId && !/[/?#]/.test(threadId)) {
        const item = document.createElement("div");
        const link = document.createElement("a");
        link.href = `/?thread=${encodeURIComponent(threadId)}&node=${encodeURIComponent(node.id)}`;
        link.textContent = t("map.open_thread");
        link.setAttribute("data-map-thread", threadId);
        link.addEventListener("click", async event => {
          if (event.button || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
          event.preventDefault();
          try {
            const response = await window.threadDeskWrite(`/threads/${encodeURIComponent(threadId)}/switch`);
            if (!response.ok) throw new Error("switch_rejected");
            location.assign(link.href);
          } catch (_) { requestState("browser.save_uncertain", true); }
        });
        item.appendChild(link);
        detailMeta.appendChild(item);
      }
    };

    graph.nodes.forEach((node) => {
      const point = placed.get(node.id);
      const tone = toneOf(node);
      const appearance = ACTORS[node.metadata?.actor_id];
      const ai = node.kind === "agent" || Boolean(appearance?.ai);
      const group = el("g", {
        class: `map-node map-node-${shapeOf(node)} map-tone-${tone}${ai ? " is-ai" : ""}`,
        transform: `translate(${point.x.toFixed(1)} ${point.y.toFixed(1)})`,
        tabindex: "0", role: "button",
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
        selectedFocusId = node.id;
        showDetail(node);
        highlight();
        // Selection must not move the other click targets out of the viewport.
        // Explicit deep-link navigation below still focuses its destination.
      };
      group.addEventListener("click", (event) => {
        if (nodeDrag && nodeDrag.moved) return;
        select(event.shiftKey);
      });
      group.addEventListener("keydown", (event) => {
        if (event.key !== "Enter" && event.key !== " ") return;
        event.preventDefault();
        select(event.shiftKey);
      });
      // Knoten lassen sich verschieben; erst ab 3 px gilt es als Ziehen,
      // damit der Klick zum Auswählen erhalten bleibt.
      group.addEventListener("pointerdown", (event) => {
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

    const labelItems = [...nodeLayer.querySelectorAll(".map-node")].map((group, order) => {
      const label = group.querySelector(".map-label");
      const texts = [...label.querySelectorAll("text")];
      return {group, label, texts, hit: group.querySelector(".map-node-hit"),
        labelHit: label.querySelector(".map-label-hit"), order, widths: new Map()};
    });
    updateLabels = () => {
      const candidates = labelItems.filter(item => item.group.style.display !== "none")
        .map(item => {
          const {group, label, texts, order, widths} = item;
          const important = group.classList.contains("is-selected") ||
            group.classList.contains("is-hovered") || document.activeElement === group;
          const font = important ? 16 : 14;
          texts.forEach((text, index) => {
            text.style.fontSize = `${font}px`;
            text.setAttribute("y", index * (font + 4));
          });
          if (!widths.has(font)) widths.set(font,
            Math.min(VIEW_W - 24, Math.max(1, ...texts.map(text => text.getComputedTextLength()))));
          const point = placed.get(group.dataset.nodeId);
          const shape = SHAPE[group.dataset.kind] || "circle";
          const dimensions = Array.isArray(SIZE[shape]) ? SIZE[shape] : [SIZE[shape], SIZE[shape]];
          return {...item, font, width: widths.get(font), height: Math.max(1, texts.length) * (font + 4),
            x: offsetX + scale * point.x, y: offsetY + scale * point.y,
            radius: dimensions[1] * scale,
            halfWidth: dimensions[0] * scale, halfHeight: dimensions[1] * scale,
            priority: important ? 3 : group.classList.contains("is-near") ? 2 :
              group.dataset.kind === "project" ? 1 : 0};
        });
      viewport.labels(candidates, VIEW_W, VIEW_H).forEach(item => {
        item.label.style.display = item.visible ? "" : "none";
        item.label.dataset.screenFontSize = String(item.font);
        item.label.setAttribute("transform",
          `translate(${item.shiftX / scale} ${item.baseline / scale}) scale(${1 / scale})`);
        // The empty space between a displaced caption and its shape must stay
        // clickable for other nodes. Two exact regions avoid an invisible wall.
        const halfWidth = item.halfWidth / scale, halfHeight = item.halfHeight / scale;
        Object.entries({x: -halfWidth, y: -halfHeight, width: halfWidth * 2, height: halfHeight * 2})
          .forEach(([key, value]) => item.hit.setAttribute(key, value));
        Object.entries({x: -item.width / 2, y: -item.font,
          width: item.width, height: item.height})
          .forEach(([key, value]) => item.labelHit.setAttribute(key, value));
      });
    };
    applyFilter = () => {
      const normalize = value => String(value || "").normalize("NFKD")
        .replace(/[\u0300-\u036f]/g, "").toLocaleLowerCase();
      const query = normalize(activeFilter.query).trim();
      const project = activeFilter.project_id;
      const members = new Set(project ? [project] : []);
      if (project) {
        const projectThread = graph.nodes.find(node => node.id === project &&
          node.kind === "project")?.metadata?.thread_id;
        graph.nodes.forEach(node => {
          if (node.metadata?.project_id === project ||
              node.metadata?.project_ids?.includes(project) ||
              (projectThread && node.metadata?.thread_id === projectThread)) members.add(node.id);
        });
        let changed = true;
        while (changed) {
          changed = false;
          graph.relations.forEach(relation => {
            if (relation.kind === "contains" && members.has(relation.source_id) &&
                !members.has(relation.target_id)) {
              members.add(relation.target_id); changed = true;
            }
          });
        }
      }
      const visible = new Set();
      graph.nodes.forEach(node => {
        const matches = (!query || normalize(`${node.title} ${node.details || ""}`).includes(query)) &&
          (!activeFilter.kind || node.kind === activeFilter.kind) && (!project || members.has(node.id));
        const group = nodeLayer.querySelector(`[data-node-id="${CSS.escape(node.id)}"]`);
        group.style.display = matches ? "" : "none";
        group.setAttribute("tabindex", matches ? "0" : "-1");
        group.setAttribute("aria-hidden", String(!matches));
        if (matches) visible.add(node.id);
      });
      edges.forEach(({path, relation}) => {
        path.style.display = visible.has(relation.source_id) && visible.has(relation.target_id) ? "" : "none";
      });
      empty.hidden = visible.size !== 0;
      empty.textContent = query || activeFilter.kind || project ? t("map.no_matches") : t("map.empty");
      updateFocusControl();
      updateLabels();
      root.dispatchEvent(new CustomEvent("threaddesk:graph-filtered", {
        bubbles: true, detail: {visible: visible.size, total: graph.nodes.length},
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
      point.x = nodeDrag.origin.x + (now.x - nodeDrag.start.x);
      point.y = nodeDrag.origin.y + (now.y - nodeDrag.start.y);
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
      highlight(); applyTransform();
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
        showDetail(chosen[0]);
        highlight();
        const point = placed.get(chosen[0].id);
        if (point) focusOn(point);
      }
    }
  };

  root.addEventListener("threaddesk:graph-filter", event => {
    const detail = event.detail || {};
    activeFilter = {query: String(detail.query || ""), kind: String(detail.kind || ""),
      project_id: String(detail.project_id || "")};
    applyFilter();
  });
  const resizeStage = () => {
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
  };
  if (window.ResizeObserver) new ResizeObserver(resizeStage).observe(stage);
  else window.addEventListener("resize", resizeStage);

  // ---------------------------------------------------------------- Bedienung
  root.querySelector("[data-map-zoom-in]").addEventListener("click", () => zoom(1.25));
  root.querySelector("[data-map-zoom-out]").addEventListener("click", () => zoom(1 / 1.25));
  root.querySelector("[data-map-reset]").addEventListener("click", fit);
  focusSelectionControl?.addEventListener("click", () => {
    const selected = [...world.querySelectorAll(".is-selected[data-node-id]")]
      .filter(node => node.style.display !== "none");
    const target = selected.find(node => node.dataset.nodeId === selectedFocusId) || selected[0];
    if (!target) return;
    scale = Math.max(1, scale);
    focusOn(placed.get(target.dataset.nodeId));
  });
  updateFocusControl();
  stage.addEventListener("wheel", (event) => {
    event.preventDefault();
    zoomAt(event.deltaY < 0 ? 1.12 : 1 / 1.12, toUser(event.clientX, event.clientY));
  }, {passive: false});

  const DRAG_THRESHOLD = 3;
  stage.addEventListener("pointerdown", (event) => {
    if (nodeDrag) return;
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

  let refreshTicket = 0;
  async function refreshGraph(refreshing = false) {
    const ticket = ++refreshTicket;
    try {
      const response = await fetch(root.dataset.graphEndpoint, {headers: {Accept: "application/json"}, cache: "no-store"});
      if (!response.ok) throw new Error("graph request failed");
      const graph = await response.json();
      if (ticket !== refreshTicket) return;
      render(graph, refreshing); error.hidden = true;
      root.dispatchEvent(new CustomEvent("threaddesk:graph-loaded", {
        bubbles: true, detail: {nodes: graph.nodes},
      }));
    } catch (_) { if (ticket === refreshTicket) error.hidden = false; }
  }
  document.addEventListener("threaddesk:library-changed", () => refreshGraph(true));
  refreshGraph();
})();
