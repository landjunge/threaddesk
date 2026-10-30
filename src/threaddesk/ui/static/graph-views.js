/* Saved views share the public application commands with CLI and MCP. */
(() => {
  const root = document.querySelector("[data-graph-endpoint]");
  if (!root) return;
  const chooser = root.querySelector("[data-map-view]"), title = root.querySelector("[data-map-view-title]");
  const message = root.querySelector("[data-map-view-message]");
  let strings = {}, loaded = null, pending = null, busy = false;
  const setBusy = value => {
    busy = value;
    root.querySelectorAll('[data-map-view-save], [data-map-view-load], [data-map-view-delete]')
      .forEach(button => { button.disabled = value; });
  };
  try { strings = JSON.parse(root.dataset.strings || "{}"); } catch (_) { /* template remains readable */ }
  const notify = key => { message.textContent = strings[key] || key; message.hidden = false; };
  const identity = () => "view-" + (crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(16).slice(2)}`);
  async function read(path) {
    const response = await fetch(path, {headers: {Accept: "application/json"}, cache: "no-store"});
    const data = await response.json();
    if (!response.ok || data.ok === false) throw data;
    return data.result || data;
  }
  async function refresh(selected = chooser.value) {
    const views = [];
    let offset = 0;
    do {
      const result = await read(`/api/graph/views?limit=100&offset=${offset}`);
      views.push(...result.views);
      offset = result.next_offset;
    } while (offset != null && views.length < 200);
    [...chooser.options].slice(1).forEach(option => option.remove());
    views.forEach(view => {
      const option = document.createElement("option"); option.value = view.id; option.textContent = view.title; chooser.append(option);
    });
    chooser.value = selected;
  }
  async function load() {
    if (!chooser.value || busy) return;
    setBusy(true);
    try {
      const view = await read(`/api/graph/views/${encodeURIComponent(chooser.value)}`);
      loaded = view; title.value = view.title; pending = null;
      await root.graphController.restore(view.state);
      message.hidden = true;
    } catch (_) { notify("map.view_failed"); }
    finally { setBusy(false); }
  }
  async function mutate(action) {
    if (busy) return;
    if (action === "save" && !title.value.trim()) { title.focus(); return; }
    if (action === "delete" && (!loaded || chooser.value !== loaded.id)) return;
    // A changed chooser is not permission to overwrite its unseen revision.
    if (chooser.value && loaded?.id !== chooser.value) { notify("map.view_conflict"); return; }
    const data = action === "save" ? {title: title.value.trim(), state: root.graphController.snapshot()} : {};
    const draft = {action, id: loaded?.id || pending?.id || identity(), expected_revision: loaded?.revision || 0, data};
    // Reuse the exact uncertain request. Never create an accidental second save.
    if (pending && JSON.stringify({...pending, operation_id: undefined}) !== JSON.stringify(draft)) {
      notify("map.view_failed"); return;
    }
    const request = pending || {...draft, operation_id: identity()};
    pending = request;
    setBusy(true);
    try {
      const response = await window.threadDeskWrite("/api/graph/views", {
        headers: {"Content-Type": "application/json"}, body: JSON.stringify(request)});
      const payload = await response.json();
      if (!response.ok || payload.ok === false) {
        const code = payload.code || payload.error?.code;
        if (["revision_conflict", "operation_conflict"].includes(code)) {
          pending = null; notify("map.view_conflict"); return;
        }
        throw payload;
      }
      const result = payload.result || payload;
      const confirmed = action === "delete" ? null : await read(`/api/graph/views/${encodeURIComponent(result.view.id)}`);
      if (confirmed && confirmed.revision !== result.view.revision) { pending = null; notify("map.view_conflict"); return; }
      loaded = confirmed; pending = null;
      await refresh(confirmed?.id || ""); notify("map.view_saved");
    } catch (_) { notify("map.view_failed"); }
    finally { setBusy(false); }
  }
  chooser.addEventListener("change", () => { if (!chooser.value) { loaded = null; pending = null; title.value = ""; } });
  root.querySelector("[data-map-view-load]").addEventListener("click", load);
  root.querySelector("[data-map-view-save]").addEventListener("click", () => mutate("save"));
  root.querySelector("[data-map-view-delete]").addEventListener("click", () => mutate("delete"));
  refresh().catch(() => notify("map.view_failed"));
})();
