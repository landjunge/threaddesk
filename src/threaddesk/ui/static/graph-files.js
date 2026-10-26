/* Thin file-manager adapter: all file state belongs to shared commands. */
(() => {
  const panel = document.querySelector("[data-graph-files]");
  if (!panel) return;
  const strings = JSON.parse(panel.dataset.strings || "{}");
  const t = key => strings[`graph_files.${key}`] || key;
  const find = name => panel.querySelector(`[data-${name}]`);
  const list = find("files-list"), status = find("files-status");
  const dialog = find("file-preview"), message = find("file-message");
  const pendingKey = "threaddesk:library:pending";
  let node = null, selected = null, next = null, listTicket = 0, previewTicket = 0;
  let activeSearch = "", browseFolder = null, canOpen = false, busy = false, pending = null, graphNodes = [];
  try {
    const saved = JSON.parse(sessionStorage.getItem(pendingKey) || "null");
    if (saved && typeof saved === "object" && typeof saved.operation_id === "string" && /^[A-Za-z0-9_-]{1,128}$/.test(saved.operation_id)) pending = saved;
  } catch (_) { /* no unsafe replay */ }
  const operation = () => `files-${crypto.randomUUID()}`;
  const safeFailures = new Set(["validation_error", "revision_conflict", "operation_conflict", "name_conflict", "object_in_trash", "not_found", "trash_generation_conflict", "external_open_blocked", "no_default_application", "unsupported_workspace_version"]);
  function remember(value) {
    pending = value;
    try { if (value) sessionStorage.setItem(pendingKey, JSON.stringify(value)); else sessionStorage.removeItem(pendingKey); } catch (_) { /* current tab still retains the operation */ }
  }
  async function read(action, args = {}) {
    const response = await fetch(`/api/library/query?${new URLSearchParams({action, ...args})}`, {cache: "no-store"});
    const result = await response.json();
    if (!result.ok) throw new Error(result.code || "read_failed");
    return result.result;
  }
  async function write(args) {
    const response = await window.threadDeskWrite("/api/library/command", {
      method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(args),
    });
    const result = await response.json();
    if (!result.ok) {
      const error = new Error(result.code || "write_failed");
      error.confirmedFailure = safeFailures.has(result.code);
      throw error;
    }
    return result.result;
  }
  function button(text, handler) {
    const element = document.createElement("button");
    element.type = "button"; element.className = "btn btn-ghost";
    element.textContent = text; element.addEventListener("click", handler);
    return element;
  }
  function option(select, value, label) {
    const item = document.createElement("option"); item.value = value; item.textContent = label; select.append(item);
  }
  function choices() {
    const project = find("files-project"), assignment = find("file-project"), target = find("file-node");
    const keep = [project.value, assignment.value, target.value];
    project.replaceChildren(); assignment.replaceChildren(); target.replaceChildren();
    option(project, "", t("all_projects")); option(assignment, "", t("keep_project")); option(target, "", t("no_node"));
    graphNodes.forEach(item => {
      option(target, item.id, `${item.title} · ${item.kind}`);
      if (item.kind === "project") {
        option(project, item.id, item.title);
        if (item.metadata?.thread_id) option(assignment, item.metadata.thread_id, item.title);
      }
    });
    if (selected?.thread_id && ![...assignment.options].some(item => item.value === selected.thread_id))
      option(assignment, selected.thread_id, selected.thread_title || t("current_project"));
    [project, assignment, target].forEach((select, i) => { select.value = keep[i]; });
    if (!target.value && selected?.node_ids?.length) target.value = selected.node_ids[0];
  }
  async function refreshChoices() {
    try {
      const response = await fetch("/api/graph", {cache: "no-store"});
      if (!response.ok) throw new Error("graph_unavailable");
      const graph = await response.json();
      graphNodes = (graph.nodes || []).sort((a, b) => a.title.localeCompare(b.title)); choices();
    } catch (_) { status.textContent = t("choices_unavailable"); }
  }
  function render(rows, folders = []) {
    list.replaceChildren();
    const shownRecords = new Set(); let shownCount = 0;
    if (browseFolder !== null && browseFolder !== "") {
      const parent = document.createElement("li");
      parent.append(button(t("parent_folder"), () => {
        browseFolder = browseFolder.includes("/") ? browseFolder.slice(0, browseFolder.lastIndexOf("/")) : "";
        find("files-folder").value = browseFolder; load();
      })); list.append(parent);
    }
    folders.forEach(folder => {
      const li = document.createElement("li");
      li.append(button(`${t("folder")}: ${folder}`, () => {
        browseFolder = folder; find("files-folder").value = folder; load();
      })); list.append(li);
    });
    rows.forEach(row => {
      const li = document.createElement("li");
      const id = row.record_id || (row.entity_type === "file" || !row.entity_type ? row.id : null);
      const title = row.filename || row.title || row.id;
      // A generated file node and the corresponding file search document are
      // two matches for one attachment, not two different stored originals.
      if (id && shownRecords.has(id)) return;
      if (id) shownRecords.add(id);
      shownCount += 1;
      if (id) {
        const entry = button(title, () => preview(id)); entry.dataset.fileRecord = id;
        // A normal click only previews. The explicit Open action is also available
        // when the modal intercepts the second pointer event of a double click.
        entry.addEventListener("dblclick", () => selected?.id === id && perform("open")); li.append(entry);
      } else {
        const a = document.createElement("a"); a.textContent = title;
        a.href = row.entity_type === "thread"
          ? row.thread_path || `/?thread=${encodeURIComponent(row.thread_id || row.id)}`
          : row.graph_path || `/map?node=${encodeURIComponent(row.node_id || row.id)}`;
        li.append(a);
      }
      const info = document.createElement("span"); info.className = "muted";
      info.textContent = ` ${row.format || row.entity_type || ""} · ${row.logical_path || row.origin_path || ""}${row.trashed ? ` · ${t("trash")}` : ""}`; li.append(info);
      if (row.node_id || id) {
        const a = document.createElement("a"); a.textContent = t("node");
        a.href = row.graph_path || `/map?node=${encodeURIComponent(row.file_node_id || id || row.node_id)}`;
        li.append(a);
      }
      list.append(li);
    });
    status.textContent = shownCount || folders.length ? `${shownCount} · ${activeSearch || t("heading")}${folders.length ? ` · ${folders.length} ${t("folder")}` : ""}` : t("empty");
  }
  async function load(offset = 0) {
    const request = ++listTicket;
    try {
      const args = {limit: "50", offset: String(offset), include_trashed: String(find("files-trash").checked)};
      let result;
      if (activeSearch) {
        const filters = {kind: find("files-type").value, date_from: find("files-date-from").value,
          date_to: find("files-date-to").value, project_id: find("files-project").value};
        Object.entries(filters).forEach(([key, value]) => { if (value) args[key] = value; });
        result = await read("search", {...args, query: activeSearch});
      } else {
        if (node) args.node_id = node.id;
        if (browseFolder !== null) args.folder = browseFolder;
        args.sort = find("files-sort").value; result = await read("list", args);
      }
      if (request !== listTicket) return;
      const rows = result.hits || result.records || []; render(rows, result.folders);
      document.querySelector("[data-graph-endpoint]")?.dispatchEvent(new CustomEvent("threaddesk:files-listed", {
        detail: {node_id: node?.id || null, total: result.total ?? rows.length},
      }));
      next = result.next_offset ?? (rows.length === 50 ? offset + 50 : null);
      find("files-more").hidden = next === null;
      const index = result.index;
      if (index && index.status !== "ready") status.textContent += ` · ${t("index_state")}: ${index.status}`;
    } catch (error) { if (request === listTicket) status.textContent = `${t("error")}: ${error.message}`; }
  }
  function actionState() {
    panel.querySelectorAll("[data-file-action]").forEach(element => {
      const action = element.dataset.fileAction;
      element.hidden = action === "restore" ? !selected?.trashed : Boolean(selected?.trashed);
      element.disabled = !selected || busy || Boolean(pending) || (action === "open" && !canOpen);
    });
    ["file-name", "file-folder", "file-project", "file-node"].forEach(name => {
      find(name).disabled = busy || Boolean(pending);
    });
    find("file-check").hidden = !pending;
    find("file-check").disabled = busy;
  }
  function receiptMessage(result) {
    if (result.status === "failed") return `${t("failed")}: ${result.error || "external_open_failed"}`;
    if (result.status === "unknown") return t("uncertain");
    if (result.status === "launch_requested") return t("launch_requested");
    if (result.graph_projection?.status === "pending" || (result.index && result.index.status !== "ready")) return t("saved_pending");
    return t("saved");
  }
  async function preview(id) {
    const ticket = ++previewTicket;
    try {
      const result = await read("preview", {id});
      if (ticket !== previewTicket) return;
      selected = result.record; message.textContent = pending ? t("uncertain") : "";
      find("file-title").textContent = selected.filename; find("file-name").value = selected.filename;
      const path = selected.logical_path || selected.origin_path || "";
      find("file-folder").value = path.includes("/") ? path.slice(0, path.lastIndexOf("/")) : "";
      find("file-node").value = selected.node_ids?.[0] || selected.node_id || "";
      const assigned = selected.node_ids || (selected.node_id ? [selected.node_id] : []);
      find("file-assignments").textContent = `${t("current_nodes")}: ${assigned.length ? assigned.map(id => graphNodes.find(item => item.id === id)?.title || t("unavailable_node")).join(", ") : t("no_node")}`;
      const project = find("file-project");
      if (selected.thread_id && ![...project.options].some(item => item.value === selected.thread_id))
        option(project, selected.thread_id, selected.thread_title || t("current_project"));
      project.value = selected.thread_id || "";
      const body = find("file-body"); body.replaceChildren();
      if (result.kind === "text") { const pre = document.createElement("pre"); pre.textContent = result.text || ""; body.append(pre); }
      else if (["image", "audio", "video"].includes(result.kind)) {
        const media = document.createElement(result.kind === "image" ? "img" : result.kind);
        media.addEventListener("error", () => {
          if (ticket !== previewTicket) return;
          body.textContent = t("metadata_only"); message.textContent = t("preview_failed");
        }, {once: true});
        media.src = `/api/library/content/${encodeURIComponent(id)}`;
        if (result.kind === "image") media.alt = selected.filename;
        else { media.controls = true; media.preload = "metadata"; } body.append(media);
      } else body.textContent = t("metadata_only");
      find("file-information").textContent = `${selected.size} B · ${selected.media_type} · SHA-256 ${selected.sha256}${result.truncated ? ` · ${t("truncated")}` : ""}`;
      find("file-information").textContent += `\n${t("folder")}: ${selected.logical_path || selected.origin_path}\n${t("version")}: ${selected.version || 1}${selected.current_version === false ? ` · ${t("historical")}` : ""}\n${selected.origin_path || ""}`;
      canOpen = Boolean(result.can_open); actionState(); if (!dialog.open) dialog.showModal();
    } catch (error) { if (ticket === previewTicket) status.textContent = `${t("error")}: ${error.message}`; }
  }
  async function finish(args, result, ticket) {
    if (result.status !== "unknown") remember(null);
    if (previewTicket === ticket && selected?.id === args.id) {
      message.textContent = receiptMessage(result);
      if (args.action === "trash") { ++previewTicket; dialog.close(); }
      else if (args.action !== "open" && result.record) {
        await preview(result.record.id);
        if (selected?.id === result.record.id) message.textContent = receiptMessage(result);
      }
    }
    if (args.action !== "open") {
      document.querySelector("[data-graph-endpoint]")?.dispatchEvent(new CustomEvent("threaddesk:library-changed", {detail: {record_id: result.record?.id || args.id}}));
      await refreshChoices();
    }
    await load();
  }
  async function perform(action) {
    if (!selected || busy || pending || (action === "open" && !canOpen)) return;
    const data = {};
    if (["rename", "copy"].includes(action)) data.filename = find("file-name").value;
    if (action === "move") data.folder = find("file-folder").value;
    if (action === "restore") data.trash_generation = selected.trash_generation;
    if (action === "assign") {
      const target = find("file-node").value;
      // A project-only change must not silently discard additional existing links.
      data.node_ids = target ? [...new Set([...(selected.node_ids || []), target])] : [];
      if (find("file-project").value) data.thread_id = find("file-project").value;
    }
    const args = {action, id: selected.id, expected_revision: selected.revision, operation_id: operation()};
    if (action !== "open") args.data = data;
    const ticket = previewTicket; remember(args); busy = true; actionState();
    try { await finish(args, await write(args), ticket); }
    catch (error) {
      if (error.confirmedFailure) remember(null);
      if (previewTicket === ticket) message.textContent = `${t("error")}: ${error.message}${pending ? ` · ${t("uncertain")}` : ""}`;
    } finally { busy = false; actionState(); }
  }
  find("file-check").addEventListener("click", async () => {
    if (!pending || busy) return;
    const args = pending, ticket = previewTicket; busy = true; actionState();
    try {
      const result = await read("operation", {operation_id: args.operation_id});
      if (result.found && result.result?.status !== "unknown") await finish(args, result.result, ticket);
      else message.textContent = t("uncertain");
    } catch (_) { message.textContent = t("uncertain"); }
    finally { busy = false; actionState(); }
  });
  find("file-close").addEventListener("click", () => { ++previewTicket; dialog.close(); });
  dialog.addEventListener("cancel", () => { ++previewTicket; });
  panel.querySelectorAll("[data-file-action]").forEach(element => element.addEventListener("click", () => perform(element.dataset.fileAction)));
  panel.querySelector("[data-file-search]").addEventListener("submit", event => {
    event.preventDefault(); activeSearch = new FormData(event.target).get("query").trim(); node = null; browseFolder = null; load();
  });
  find("files-all").addEventListener("click", () => { node = null; activeSearch = ""; browseFolder = null; load(); });
  find("files-folder-open").addEventListener("click", () => { activeSearch = ""; browseFolder = find("files-folder").value; load(); });
  find("files-sort").addEventListener("change", () => load());
  find("files-trash").addEventListener("change", () => load());
  find("files-more").addEventListener("click", () => next !== null && load(next));
  document.querySelector("[data-graph-endpoint]")?.addEventListener("threaddesk:node-selected", event => {
    node = event.detail; activeSearch = ""; browseFolder = null; find("files-folder").value = ""; load();
  });
  refreshChoices(); actionState();
})();
