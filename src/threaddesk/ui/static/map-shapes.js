/* SVG visual vocabulary only; no persistence, camera or domain effects. */
window.ThreadDeskMapShapes = dimensions => {
  const svgNS = "http://www.w3.org/2000/svg";
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
    const {width: VIEW_W, height: VIEW_H} = dimensions();
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

  return {SHAPE, TONE, EDGE, GLYPH, SIZE, MARK, MARK_AT, shapeOf, toneOf, radiusOf,
    el, outline, caption, defs, backdrop, edgePath};
};
