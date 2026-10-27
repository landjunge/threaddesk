/* Shared revision-bound domain commands; no implicit purge or file execution. */
(() => {
  const root = document.querySelector("[data-trash-page]");
  let strings = {}, workspace = null, tab = "objects", offset = 0, next = null, loadVersion = 0;
  try { strings = JSON.parse(root?.dataset.strings || document.body.dataset.uiStrings || "{}"); } catch (_) { /* controls retain their labels */ }
  const text = key => strings[key] || key;
  const identity = () => "trash-" + (crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(16).slice(2)}`);
  async function request(command, args, operation = null, revision = null) {
    if (!workspace) {
      const response = await fetch("/api/commands/catalog?limit=1", {cache: "no-store"});
      if (!response.ok) throw new Error("catalog_unavailable");
      workspace = (await response.json()).workspace_id;
    }
    const body = {version: 1, workspace_id: workspace, command, arguments: args};
    if (operation) body.operation_id = operation;
    if (revision !== null) body.expected_revision = revision;
    const response = await window.threadDeskWrite("/api/commands", {headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)});
    const data = await response.json();
    if (!response.ok || data.ok === false) throw data;
    if (!("result" in data)) throw new Error("result_too_large");
    return data.result;
  }
  const status = message => { const target = root?.querySelector("[data-trash-message]") || document.querySelector("#request-state"); if (target) { target.hidden = false; target.textContent = message; } };
  const failure = error => status(text(String(error?.code || "").includes("conflict") ? "trash.conflict" : "trash.failed"));
  async function load(append = false) {
    const version = ++loadVersion, requestedTab = tab;
    const result = requestedTab === "objects"
      ? await request("trash.list", {limit: 50, offset, state: "trashed"})
      : await request("library_query", {action: "list", include_trashed: true, limit: 50, offset});
    if (version !== loadVersion || requestedTab !== tab) return;
    const list = root.querySelector("[data-trash-items]");
    if (!append) list.replaceChildren();
    const rows = requestedTab === "objects" ? result.items : result.records.filter(item => item.trashed);
    for (const item of rows) {
      const row = document.createElement("li"), title = document.createElement("strong"), detail = document.createElement("p"), button = document.createElement("button");
      title.textContent = item.title || item.filename || item.object_id;
      detail.textContent = `${text("trash.kind." + (item.kind || "file"))} · ${text("trash.deleted_at")}: ${item.deleted_at || ""}`;
      button.type = "button"; button.className = "btn"; button.textContent = text("trash.restore");
      button.addEventListener("click", async () => {
        button.disabled = true;
        try {
          const operation = identity();
          const result = requestedTab === "objects"
            ? await request("trash.restore", {trash_id: item.trash_id, generation: item.generation, expected_revision: item.revision, operation_id: operation}, operation, item.revision)
            : await request("library_manage", {action: "restore", id: item.id, expected_revision: item.revision, operation_id: operation, data: {trash_generation: item.trash_generation}}, operation, item.revision);
          // An independent read verifies the new lifecycle before removing the row.
          const confirmed = requestedTab === "objects"
            ? await request("trash.get", {trash_id: item.trash_id})
            : await request("library_query", {action: "info", id: item.id});
          if (requestedTab === "objects" ? confirmed.state !== "restored" : confirmed.trashed) throw new Error("restore_unconfirmed");
          row.remove(); status(text(result.unresolved_references?.length ? "trash.unresolved" : "trash.restored"));
        } catch (error) { failure(error); button.disabled = false; }
      });
      row.append(title, detail, button); list.append(row);
    }
    next = result.next_offset;
    root.querySelector("[data-trash-next]").hidden = next === null;
    if (!list.children.length && next === null) status(text("trash.empty"));
  }
  if (root) {
    root.querySelectorAll("[data-trash-tab]").forEach(button => button.addEventListener("click", () => {
      tab = button.dataset.trashTab; offset = 0; root.querySelectorAll("[data-trash-tab]").forEach(other => other.setAttribute("aria-pressed", String(other === button))); load().catch(failure);
    }));
    root.querySelector("[data-trash-refresh]").addEventListener("click", () => { offset = 0; load().catch(failure); });
    root.querySelector("[data-trash-next]").addEventListener("click", () => { offset = next; load(true).catch(failure); });
    load().catch(failure);
  }
  document.addEventListener("click", async event => {
    const button = event.target.closest("[data-trash-object]");
    if (!button || button.disabled) return;
    if (!window.confirm(button.dataset.trashConfirm)) return;
    button.disabled = true;
    try {
      const operation = identity(), kind = button.dataset.trashKind || "thread";
      if (kind === "file") {
        const info = await request("library_query", {action: "info", id: button.dataset.trashObject});
        await request("library_manage", {action: "trash", id: info.id, expected_revision: info.revision, operation_id: operation}, operation, info.revision);
        const confirmed = await request("library_query", {action: "info", id: info.id});
        if (!confirmed.trashed) throw new Error("trash_unconfirmed");
        window.location.assign("/trash"); return;
      }
      const result = await request("trash.move", {kind, object_id: button.dataset.trashObject,
        expected_revision: Number(button.dataset.trashRevision), operation_id: operation}, operation, Number(button.dataset.trashRevision));
      const confirmed = await request("trash.get", {trash_id: result.entry.trash_id});
      if (confirmed.state !== "trashed") throw new Error("trash_unconfirmed");
      window.location.assign("/trash");
    } catch (error) { failure(error); button.disabled = false; }
  });
})();
