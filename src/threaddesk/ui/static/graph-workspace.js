/* Workspace navigation only; graph and file domain state keep their owners. */
(() => {
  const root = document.querySelector("[data-graph-endpoint]");
  if (!root) return;
  const inspector = root.querySelector("[data-map-inspector]");
  const toggle = root.querySelector("[data-map-inspector-toggle]");
  if (!inspector || !toggle) return;
  const tabs = [...root.querySelectorAll("[data-map-tab]")];
  const panes = [...root.querySelectorAll("[data-map-pane]")];
  let selectedId = null, explicitTab = false;

  function chooseTab(name, focus = false) {
    tabs.forEach(tab => {
      const chosen = tab.dataset.mapTab === name;
      tab.setAttribute("aria-selected", String(chosen));
      tab.tabIndex = chosen ? 0 : -1;
      if (chosen && focus) tab.focus();
    });
    panes.forEach(pane => { pane.hidden = pane.dataset.mapPane !== name; });
  }
  function show(open) {
    inspector.hidden = !open;
    toggle.setAttribute("aria-expanded", String(open));
  }
  toggle.addEventListener("click", () => show(inspector.hidden));
  root.querySelector("[data-map-inspector-close]")?.addEventListener("click", () => {
    show(false); toggle.focus();
  });
  tabs.forEach((tab, index) => {
    tab.addEventListener("click", () => { explicitTab = true; chooseTab(tab.dataset.mapTab); });
    tab.addEventListener("keydown", event => {
      if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
      event.preventDefault(); explicitTab = true;
      const next = event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1
        : (index + (event.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length;
      chooseTab(tabs[next].dataset.mapTab, true);
    });
  });
  root.addEventListener("threaddesk:node-selected", event => {
    selectedId = event.detail?.id || null;
    if (!selectedId) return;
    if (!explicitTab) chooseTab("selection");
    show(true);
  });
  root.addEventListener("threaddesk:files-listed", event => {
    if (!explicitTab && !inspector.hidden && event.detail?.node_id === selectedId && event.detail.total > 0)
      chooseTab("files");
  });

  const controls = root.querySelector("[data-map-filters]");
  if (!controls) return;
  const query = controls.querySelector("[data-map-query]");
  const kind = controls.querySelector("[data-map-kind]");
  const project = controls.querySelector("[data-map-project]");
  const count = controls.querySelector("[data-map-filter-count]");
  const mode = controls.querySelector("[data-map-mode]");
  const age = controls.querySelector("[data-map-age]");
  const status = controls.querySelector("[data-map-status]");
  const hops = controls.querySelector("[data-map-hops]");
  let strings = {};
  try { strings = JSON.parse(root.dataset.strings || "{}"); } catch (_) { /* readable control labels remain */ }
  function filter(queryServer = true) {
    root.dispatchEvent(new CustomEvent("threaddesk:graph-filter", {detail: {
      query: query.value.trim(), kind: kind.value, project_id: project.value,
      mode: mode.value, band: age.value, status: status.value, hops: Number(hops.value),
      server_query: queryServer !== false,
    }}));
  }
  let inputTimer;
  query.addEventListener("input", () => { clearTimeout(inputTimer); inputTimer = setTimeout(filter, 120); });
  kind.addEventListener("change", filter); project.addEventListener("change", filter);
  [mode, age, status, hops].forEach(input => input.addEventListener("change", filter));
  controls.addEventListener("submit", event => {
    event.preventDefault(); clearTimeout(inputTimer); filter();
    root.dispatchEvent(new CustomEvent("threaddesk:graph-search-submit"));
  });
  controls.querySelector("[data-map-clear-filters]")?.addEventListener("click", () => {
    query.value = ""; kind.value = ""; project.value = ""; age.value = ""; status.value = ""; hops.value = "0";
    filter(); query.focus();
  });
  // Read model supplied by the renderer, avoiding a second graph request.
  root.addEventListener("threaddesk:graph-loaded", event => {
    const chosen = project.value;
    const chosenText = project.selectedOptions[0]?.textContent;
    [...project.options].slice(1).forEach(option => option.remove());
    (event.detail?.nodes || []).filter(node => node.kind === "project").forEach(node => {
      const option = document.createElement("option");
      option.value = node.id; option.textContent = node.title; project.append(option);
    });
    if ([...project.options].some(option => option.value === chosen)) project.value = chosen;
    else if (chosen) {
      const option = document.createElement("option"); option.value = chosen; option.textContent = chosenText;
      project.append(option); project.value = chosen;
    }
    const selectedStatus = status.value;
    [...status.options].slice(1).forEach(option => option.remove());
    [...new Set((event.detail?.nodes || []).map(node => node.status))].sort().forEach(value => {
      const option = document.createElement("option"); option.value = value; option.textContent = value; status.append(option);
    });
    if (selectedStatus && ![...status.options].some(option => option.value === selectedStatus)) {
      const option = document.createElement("option"); option.value = selectedStatus; option.textContent = selectedStatus; status.append(option);
    }
    status.value = selectedStatus;
  });
  root.addEventListener("threaddesk:graph-filtered", event => {
    if (!count) return;
    count.hidden = !query.value.trim() && !kind.value && !project.value && !age.value && !status.value && !Number(hops.value);
    count.textContent = (strings["map.filtered_count"] || "{visible} / {total}")
      .replace("{visible}", String(event.detail.visible)).replace("{total}", String(event.detail.total));
  });
  root.addEventListener("threaddesk:graph-view-loaded", event => {
    const filters = event.detail?.filters || {};
    query.value = filters.query || ""; kind.value = filters.kind || "";
    project.value = filters.project_id || ""; mode.value = filters.mode || "work";
    age.value = filters.band || ""; status.value = filters.status || ""; hops.value = String(filters.hops || 0);
    filter(false);
  });
})();
