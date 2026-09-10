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
  const svgNS = "http://www.w3.org/2000/svg";
  const MIN_SCALE = 0.35;
  const MAX_SCALE = 3;
  const [, , VIEW_W, VIEW_H] = (canvas.getAttribute("viewBox") || "0 0 1000 700")
    .split(/\s+/).map(Number);
  let scale = 1;
  let offsetX = 0;
  let offsetY = 0;
  let drag = null;

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
  const reset = () => {
    scale = 1;
    offsetX = 0;
    offsetY = 0;
    applyTransform();
    const box = world.getBBox();
    if (!box.width || !box.height) return;
    const padding = 32;
    scale = clamp(Math.min(
      (VIEW_W - padding * 2) / box.width,
      (VIEW_H - padding * 2) / box.height,
    ));
    offsetX = VIEW_W / 2 - scale * (box.x + box.width / 2);
    offsetY = VIEW_H / 2 - scale * (box.y + box.height / 2);
    applyTransform();
  };
  const el = (name, attrs = {}) => {
    const node = document.createElementNS(svgNS, name);
    Object.entries(attrs).forEach(([key, value]) => node.setAttribute(key, value));
    return node;
  };
  const positions = (nodes) => {
    const result = new Map();
    const radius = Math.min(260, 95 + nodes.length * 18);
    nodes.forEach((node, index) => {
      const angle = nodes.length === 1 ? 0 : (Math.PI * 2 * index) / nodes.length - Math.PI / 2;
      result.set(node.id, {
        x: nodes.length === 1 ? 500 : 500 + Math.cos(angle) * radius,
        y: nodes.length === 1 ? 350 : 350 + Math.sin(angle) * radius,
      });
    });
    return result;
  };
  const render = (graph) => {
    world.replaceChildren();
    empty.hidden = graph.nodes.length !== 0;
    summary.textContent = `${graph.counts.nodes} Knoten · ${graph.counts.relations} Verbindungen`;
    const points = positions(graph.nodes);
    graph.relations.forEach((relation) => {
      const from = points.get(relation.source_id);
      const to = points.get(relation.target_id);
      if (!from || !to) return;
      world.appendChild(el("line", {x1: from.x, y1: from.y, x2: to.x, y2: to.y, class: "map-edge"}));
    });
    graph.nodes.forEach((node) => {
      const point = points.get(node.id);
      const group = el("g", {
        class: "map-node", transform: `translate(${point.x} ${point.y})`,
        tabindex: "0", role: "button", "data-status": node.status,
        "aria-label": `${node.title}, ${node.kind}, ${node.status}`,
      });
      const shape = node.kind === "task"
        ? el("rect", {x: -70, y: -27, width: 140, height: 54, rx: 5})
        : el("circle", {r: 42});
      shape.setAttribute("class", "map-node-shape");
      const label = el("text", {"text-anchor": "middle", y: 5});
      label.textContent = node.title.length > 20 ? `${node.title.slice(0, 19)}…` : node.title;
      group.append(shape, label);
      const select = (additive = false) => {
        if (!additive) world.querySelectorAll(".is-selected").forEach((item) => item.classList.remove("is-selected"));
        group.classList.toggle("is-selected");
        detailTitle.textContent = node.title;
        detailText.textContent = node.details || "Keine Details";
        detailMeta.hidden = false;
        detailMeta.replaceChildren();
        [["Typ", node.kind], ["Status", node.status], ["Herkunft", node.source], ["Sichtbarkeit", node.visibility], ["Revision", node.revision]].forEach(([term, value]) => {
          const item = document.createElement("div");
          const dt = document.createElement("dt");
          const dd = document.createElement("dd");
          dt.textContent = term;
          dd.textContent = value;
          item.append(dt, dd);
          detailMeta.appendChild(item);
        });
      };
      group.addEventListener("click", (event) => select(event.shiftKey));
      group.addEventListener("keydown", (event) => {
        if (event.key !== "Enter" && event.key !== " ") return;
        event.preventDefault();
        select(event.shiftKey);
      });
      world.appendChild(group);
    });
    reset();
  };

  root.querySelector("[data-map-zoom-in]").addEventListener("click", () => zoom(1.2));
  root.querySelector("[data-map-zoom-out]").addEventListener("click", () => zoom(1 / 1.2));
  root.querySelector("[data-map-reset]").addEventListener("click", reset);
  stage.addEventListener("wheel", (event) => {
    event.preventDefault();
    zoomAt(event.deltaY < 0 ? 1.1 : 1 / 1.1, toUser(event.clientX, event.clientY));
  }, {passive: false});
  const DRAG_THRESHOLD = 3;
  stage.addEventListener("pointerdown", (event) => {
    drag = {
      x: event.clientX, y: event.clientY, offsetX, offsetY,
      pointerId: event.pointerId, panning: false,
    };
  });
  stage.addEventListener("pointermove", (event) => {
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
  };
  stage.addEventListener("pointerup", endDrag);
  stage.addEventListener("pointercancel", endDrag);
  fetch(root.dataset.graphEndpoint, {headers: {Accept: "application/json"}})
    .then((response) => {
      if (!response.ok) throw new Error("graph request failed");
      return response.json();
    })
    .then(render)
    .catch(() => { error.hidden = false; });
})();
