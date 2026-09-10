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
  const svgNS = "http://www.w3.org/2000/svg";
  let scale = 1;
  let offsetX = 0;
  let offsetY = 0;
  let drag = null;

  const applyTransform = () => {
    world.setAttribute("transform", `translate(${offsetX} ${offsetY}) scale(${scale})`);
  };
  const zoom = (factor) => {
    scale = Math.max(0.35, Math.min(3, scale * factor));
    applyTransform();
  };
  const reset = () => {
    scale = 1;
    offsetX = 0;
    offsetY = 0;
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
  };

  root.querySelector("[data-map-zoom-in]").addEventListener("click", () => zoom(1.2));
  root.querySelector("[data-map-zoom-out]").addEventListener("click", () => zoom(1 / 1.2));
  root.querySelector("[data-map-reset]").addEventListener("click", reset);
  stage.addEventListener("wheel", (event) => {
    event.preventDefault();
    zoom(event.deltaY < 0 ? 1.1 : 1 / 1.1);
  }, {passive: false});
  stage.addEventListener("pointerdown", (event) => {
    drag = {x: event.clientX, y: event.clientY, offsetX, offsetY};
    stage.setPointerCapture(event.pointerId);
    stage.classList.add("is-panning");
  });
  stage.addEventListener("pointermove", (event) => {
    if (!drag) return;
    offsetX = drag.offsetX + event.clientX - drag.x;
    offsetY = drag.offsetY + event.clientY - drag.y;
    applyTransform();
  });
  stage.addEventListener("pointerup", () => {
    drag = null;
    stage.classList.remove("is-panning");
  });
  fetch(root.dataset.graphEndpoint, {headers: {Accept: "application/json"}})
    .then((response) => {
      if (!response.ok) throw new Error("graph request failed");
      return response.json();
    })
    .then(render)
    .catch(() => { error.hidden = false; });
})();
