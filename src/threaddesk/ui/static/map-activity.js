/* Inert activity presentation and a paged DOM alternative to the graph. */
window.ThreadDeskMapActivity = (root, t) => {
  const colors = {"24h": "#f7ef79", "7d": "#9bdb70", "30d": "#51bfa4",
    "90d": "#65a6c2", older: "#a2a8c3", unknown: "#9aa7b0"};
  let graph = {nodes: [], as_of: null}, mode = "work", visible = null, page = 0;
  const pageSize = 50;
  const list = root.querySelector("[data-map-node-list]");
  const items = root.querySelector("[data-map-list-items]");
  const listToggle = root.querySelector("[data-map-list-toggle]");
  const stamp = value => {
    try { return new Intl.DateTimeFormat(document.documentElement.lang || "de", {
      dateStyle: "medium", timeStyle: "long"}).format(new Date(value)); }
    catch (_) { return value || ""; }
  };
  function current(node) {
    const activity = node.activity || {};
    const candidates = mode === "modified" ? [activity.modified] : mode === "accessed"
      ? [activity.accessed] : [activity.modified, activity.accessed];
    const event = candidates.filter(Boolean).sort((a, b) =>
      Date.parse(b.occurred_at) - Date.parse(a.occurred_at))[0];
    if (!event || !graph.as_of) return {event: null, band: "unknown", future: false};
    const age = (Date.parse(graph.as_of) - Date.parse(event.occurred_at)) / 1000;
    if (!Number.isFinite(age) || age < 0) return {event, band: "unknown", future: age < 0};
    const band = [[86400, "24h"], [604800, "7d"], [2592000, "30d"], [7776000, "90d"]]
      .find(([limit]) => age <= limit)?.[1] || "older";
    return {event, band, future: false};
  }
  function describe(node) {
    if (graph.activity_status === "unavailable") return t("map.activity_unavailable");
    const activity = current(node);
    if (activity.future) return t("map.activity_clock");
    if (!activity.event) return t("map.activity_unknown");
    const event = activity.event;
    return [t(event.channel === "modified" ? "map.activity_modified" : "map.activity_accessed"),
      event.filename, stamp(event.occurred_at),
      event.aggregation === "attached_file" ? t("map.activity_attached") : ""].filter(Boolean).join(" · ");
  }
  function decorate(group, node) {
    const activity = current(node);
    group.dataset.ageBand = activity.band;
    group.style.setProperty("--file-activity-color", colors[activity.band]);
    group.classList.toggle("has-future-time", activity.future);
    const title = group.querySelector(":scope > title");
    if (title) title.textContent = node.title + "\n" + describe(node);
    group.setAttribute("aria-label", `${node.title}, ${node.kind}, ${node.status}, ${describe(node)}`);
  }
  function details(node) {
    const output = root.querySelector("[data-map-detail-activity]");
    if (!output) return;
    const lines = [describe(node)];
    for (const channel of ["modified", "accessed"]) {
      const event = node.activity?.[channel];
      if (event) lines.push(`${t(channel === "modified" ? "map.activity_modified" : "map.activity_accessed")}: ${event.filename || ""} · ${stamp(event.occurred_at)}`);
    }
    output.textContent = lines.join("\n");
    output.title = t("map.activity_note");
  }
  function renderList() {
    if (!items || list.hidden) return;
    const rows = graph.nodes.filter(node => !visible || visible.has(node.id))
      .sort((a, b) => a.title.localeCompare(b.title) || a.id.localeCompare(b.id));
    page = Math.min(page, Math.max(0, Math.ceil(rows.length / pageSize) - 1));
    items.replaceChildren();
    rows.slice(page * pageSize, (page + 1) * pageSize).forEach(node => {
      const item = document.createElement("li"), button = document.createElement("button");
      button.type = "button"; button.className = "map-list-node"; button.dataset.listNodeId = node.id;
      const title = document.createElement("strong"), meta = document.createElement("span");
      title.textContent = node.title;
      meta.textContent = `${node.kind} · ${node.status} · ${describe(node)}`;
      button.append(title, meta);
      button.addEventListener("click", () => root.dispatchEvent(new CustomEvent("threaddesk:graph-select-request", {detail: {id: node.id}})));
      item.append(button); items.append(item);
    });
    root.querySelector("[data-map-list-page]").textContent = t("map.list_page", {
      first: rows.length ? page * pageSize + 1 : 0, last: Math.min(rows.length, (page + 1) * pageSize), total: rows.length});
    root.querySelector("[data-map-list-previous]").disabled = page === 0;
    root.querySelector("[data-map-list-next]").disabled = (page + 1) * pageSize >= rows.length;
  }
  root.querySelector("[data-map-list-previous]")?.addEventListener("click", () => { page--; renderList(); });
  root.querySelector("[data-map-list-next]")?.addEventListener("click", () => { page++; renderList(); });
  listToggle?.addEventListener("click", () => {
    const open = list.hidden;
    list.hidden = !open;
    root.classList.toggle("graph-list-open", open);
    // Keep the measured graph stage mounted: a hidden stage has zero geometry.
    root.querySelector("[data-map-canvas]").setAttribute("aria-hidden", String(open));
    listToggle.setAttribute("aria-pressed", String(open));
    listToggle.textContent = t(open ? "map.canvas" : "map.list");
    renderList();
  });
  root.addEventListener("threaddesk:graph-filtered", event => {
    visible = new Set(event.detail.ids || graph.nodes.map(node => node.id)); page = 0; renderList();
  });
  return {
    current, describe, decorate, details, color: node => colors[current(node).band],
    update(next, nextMode = mode) {
      graph = next; mode = nextMode;
      root.dataset.colorMode = mode;
      root.querySelector("[data-map-status-legend]").hidden = mode !== "status";
      root.querySelector("[data-map-activity-footer]").hidden = mode === "status";
      root.querySelector("[data-map-as-of]").textContent = t("map.activity_as_of", {time: stamp(graph.as_of)});
      const warning = root.querySelector("[data-map-activity-warning]");
      warning.hidden = graph.activity_status !== "unavailable";
      warning.textContent = t("map.activity_unavailable");
      root.querySelector("[data-map-as-of]").title = t("map.activity_note");
      const partial = root.querySelector("[data-map-partial]");
      root.querySelector("[data-map-page-controls]").hidden = graph.next_offset == null && !graph.filters?.offset;
      root.querySelector("[data-map-graph-previous]").disabled = !graph.filters?.offset;
      root.querySelector("[data-map-graph-next]").disabled = graph.next_offset == null;
      partial.textContent = t("map.graph_partial", {shown: graph.nodes.length, total: graph.total || graph.nodes.length});
      renderList();
    },
  };
};
