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
  try {
    STRINGS = JSON.parse(root.dataset.strings || "{}");
  } catch (error) {
    STRINGS = {};
  }
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
  const MIN_SCALE = 0.25;
  const MAX_SCALE = 4;
  const [, , VIEW_W, VIEW_H] = (canvas.getAttribute("viewBox") || "0 0 1000 700")
    .split(/\s+/).map(Number);

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
  // Linie, wichtige Abhängigkeiten eine stärkere.
  const EDGE = {
    contains:    {tone: "soft",  width: 1.4, dash: null,    arrow: false, flow: false},
    depends_on:  {tone: "bold",  width: 2.4, dash: null,    arrow: true,  flow: false},
    blocks:      {tone: "risk",  width: 2.6, dash: null,    arrow: true,  flow: false},
    assigned_to: {tone: "soft",  width: 1.6, dash: "7 6",   arrow: true,  flow: false},
    produced:    {tone: "fresh", width: 2.0, dash: null,    arrow: true,  flow: true},
    follows:     {tone: "fresh", width: 1.8, dash: null,    arrow: true,  flow: true},
    supports:    {tone: "good",  width: 1.6, dash: null,    arrow: true,  flow: false},
    references:  {tone: "soft",  width: 1.2, dash: "3 7",   arrow: false, flow: false},
    related_to:  {tone: "soft",  width: 1.2, dash: "3 7",   arrow: false, flow: false},
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
  // Kräftesimulation statt fester Kreis: Verbundenes rückt zusammen,
  // Unverbundenes weicht aus. Ohne Zufall, damit dieselben Daten dieselbe
  // Karte ergeben.
  const layout = (nodes, relations) => {
    const CX = VIEW_W / 2;
    const CY = VIEW_H / 2;
    const count = nodes.length;
    const points = new Map();
    nodes.forEach((node, index) => {
      const angle = (index / Math.max(count, 1)) * Math.PI * 2;
      const spread = 120 + (index % 5) * 26;
      points.set(node.id, {
        x: CX + Math.cos(angle) * spread,
        y: CY + Math.sin(angle) * spread * 0.72,
        vx: 0, vy: 0, r: radiusOf(node) + 26,
      });
    });
    const links = relations
      .map((rel) => [points.get(rel.source_id), points.get(rel.target_id)])
      .filter(([a, b]) => a && b && a !== b);
    const list = [...points.values()];
    const REST = 168;
    for (let step = 0; step < 420; step += 1) {
      const cooling = 1 - step / 420;
      for (let i = 0; i < list.length; i += 1) {
        for (let j = i + 1; j < list.length; j += 1) {
          const a = list[i];
          const b = list[j];
          let dx = b.x - a.x;
          let dy = b.y - a.y;
          let dist = Math.hypot(dx, dy) || 0.01;
          const push = 24000 / (dist * dist);
          dx /= dist; dy /= dist;
          a.vx -= dx * push; a.vy -= dy * push;
          b.vx += dx * push; b.vy += dy * push;
          const overlap = a.r + b.r - dist;
          if (overlap > 0) {
            a.vx -= dx * overlap * 0.5; a.vy -= dy * overlap * 0.5;
            b.vx += dx * overlap * 0.5; b.vy += dy * overlap * 0.5;
          }
        }
      }
      links.forEach(([a, b]) => {
        let dx = b.x - a.x;
        let dy = b.y - a.y;
        const dist = Math.hypot(dx, dy) || 0.01;
        const pull = (dist - REST) * 0.012;
        dx /= dist; dy /= dist;
        a.vx += dx * pull; a.vy += dy * pull;
        b.vx -= dx * pull; b.vy -= dy * pull;
      });
      list.forEach((p) => {
        p.vx += (CX - p.x) * 0.004;
        p.vy += (CY - p.y) * 0.004;
        p.x += p.vx * cooling; p.y += p.vy * cooling;
        p.vx *= 0.82; p.vy *= 0.82;
      });
    }
    return points;
  };

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
    const words = title.split(/\s+/);
    const lines = [];
    let line = "";
    words.forEach((word) => {
      const candidate = line ? `${line} ${word}` : word;
      if (candidate.length > 22 && line) {
        lines.push(line);
        line = word;
      } else {
        line = candidate;
      }
    });
    if (line) lines.push(line);
    lines.slice(0, 2).forEach((text, index) => {
      const item = el("text", {"text-anchor": "middle", y: 54 + index * 15});
      item.textContent = text;
      group.appendChild(item);
    });
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

  const applyTransform = () => {
    world.setAttribute("transform", `translate(${offsetX} ${offsetY}) scale(${scale})`);
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
    scale = 1;
    offsetX = 0;
    offsetY = 0;
    applyTransform();
    const nodes = world.querySelector("[data-map-nodes]");
    if (!nodes) return;
    const box = nodes.getBBox();
    if (!box.width || !box.height) return;
    const padding = 44;
    scale = clamp(Math.min(
      (VIEW_W - padding * 2) / box.width,
      (VIEW_H - padding * 2) / box.height,
    ));
    offsetX = VIEW_W / 2 - scale * (box.x + box.width / 2);
    offsetY = VIEW_H / 2 - scale * (box.y + box.height / 2);
    applyTransform();
  };

  const render = (graph) => {
    world.replaceChildren();
    canvas.querySelector("defs")?.remove();
    canvas.insertBefore(defs(), canvas.firstChild);
    empty.hidden = graph.nodes.length !== 0;
    summary.textContent = t("map.nodes_relations", {
      nodes: graph.counts.nodes, relations: graph.counts.relations,
    });

    world.appendChild(backdrop());
    placed = layout(graph.nodes, graph.relations);
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

    const showDetail = (node) => {
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
    };

    graph.nodes.forEach((node) => {
      const point = placed.get(node.id);
      const tone = toneOf(node);
      const group = el("g", {
        class: `map-node map-node-${shapeOf(node)} map-tone-${tone}`,
        transform: `translate(${point.x.toFixed(1)} ${point.y.toFixed(1)})`,
        tabindex: "0", role: "button",
        "data-status": node.status, "data-kind": node.kind, "data-tone": tone,
        "data-node-id": node.id,
        "aria-label": `${node.title}, ${node.kind}, ${node.status}`,
      });
      const halo = outline(node);
      halo.setAttribute("class", "map-node-halo");
      const shape = outline(node);
      shape.setAttribute("class", "map-node-shape");
      // Symbol im Symbol: der Typ bleibt auch ohne Farbe erkennbar.
      const glyph = el("path", {class: "map-node-glyph", d: GLYPH[node.kind] || GLYPH.project});
      const [mx, my] = MARK_AT[shapeOf(node)] || MARK_AT.circle;
      const mark = el("g", {class: "map-node-mark", transform: `translate(${mx} ${my})`});
      mark.appendChild(el("circle", {class: "map-node-mark-disc", r: 8}));
      mark.appendChild(el("path", {class: "map-node-mark-sign", d: MARK[tone] || MARK.idle}));
      group.append(halo, shape, glyph, mark, caption(node.title));

      const select = (additive = false) => {
        if (!additive) {
          nodeLayer.querySelectorAll(".is-selected")
            .forEach((item) => item.classList.remove("is-selected"));
        }
        group.classList.toggle("is-selected");
        showDetail(node);
        highlight();
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
    };

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
      return true;
    };
    fit();
  };

  // ---------------------------------------------------------------- Bedienung
  root.querySelector("[data-map-zoom-in]").addEventListener("click", () => zoom(1.25));
  root.querySelector("[data-map-zoom-out]").addEventListener("click", () => zoom(1 / 1.25));
  root.querySelector("[data-map-reset]").addEventListener("click", fit);
  stage.addEventListener("wheel", (event) => {
    event.preventDefault();
    zoomAt(event.deltaY < 0 ? 1.12 : 1 / 1.12, toUser(event.clientX, event.clientY));
  }, {passive: false});

  const DRAG_THRESHOLD = 3;
  stage.addEventListener("pointerdown", (event) => {
    if (nodeDrag) return;
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

  fetch(root.dataset.graphEndpoint, {headers: {Accept: "application/json"}})
    .then((response) => {
      if (!response.ok) throw new Error("graph request failed");
      return response.json();
    })
    .then(render)
    .catch(() => { error.hidden = false; });
})();
