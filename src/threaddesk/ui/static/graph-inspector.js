/* One inspector for SVG, GPU, keyboard list and stored-view navigation. */
window.ThreadDeskGraphInspector = (root, t, activity, isFixed) => {
  const detailTitle = root.querySelector("[data-map-detail-title]");
  const detailText = root.querySelector("[data-map-detail-text]");
  const detailMeta = root.querySelector("[data-map-detail-meta]");
  const showDetail = (node, notify = true) => {
      if (notify) root.dispatchEvent(new CustomEvent("threaddesk:node-selected", {detail: {id: node.id, thread_id: node.metadata?.thread_id}}));
      detailTitle.textContent = node.title;
      const trash = root.querySelector('[data-map-trash]');
      trash.hidden = false;
      const board = node.kind === "whiteboard" && node.source === "threaddesk.whiteboard" &&
        typeof node.metadata?.thread_id === "string" && node.id === "wb-" + node.metadata.thread_id;
      trash.dataset.trashObject = board ? node.metadata.thread_id : node.metadata?.library_record_id || node.id;
      trash.dataset.trashKind = board ? 'thread' : node.metadata?.library_record_id ? 'file' : 'node';
      trash.dataset.trashConfirm = t(board ? 'map.trash_whiteboard_confirm' : node.metadata?.library_record_id ? 'map.trash_file_confirm' : 'map.trash_confirm');
      trash.dataset.trashRevision = String(node.revision);
      trash.disabled = Boolean(node.metadata?.library_record_id);
      if (node.metadata?.library_record_id) {
        const id = node.metadata.library_record_id;
        fetch('/api/library/query?' + new URLSearchParams({action: 'info', id}), {cache: 'no-store'})
          .then(response => { if (!response.ok) throw Error('file_info_unavailable'); return response.json(); })
          .then(payload => {
            const record = payload.result || payload;
            if (trash.dataset.trashObject === id && Number.isInteger(record.revision)) {
              trash.dataset.trashRevision = String(record.revision);trash.disabled = false;
            }
          }).catch(() => { /* Keep an unverified file action disabled. */ });
      }
      activity.details(node);
      const fix = root.querySelector("[data-map-fix-selected]");
      fix.disabled = false;
      fix.textContent = t(isFixed(node.id) ? "map.unfix_selected" : "map.fix_selected");
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
      if (board) {
        const state = document.createElement("p");
        state.dataset.mapWhiteboardState = node.metadata.whiteboard_status;
        state.textContent = t("map.whiteboard_state") + ": " + node.metadata.whiteboard_status;
        detailMeta.appendChild(state);
      }
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
            const stateResponse = await fetch(`/api/threads/${encodeURIComponent(threadId)}`, {cache: "no-store"});
            if (!stateResponse.ok) throw new Error("thread_unavailable");
            const state = await stateResponse.json();
            const revision = state.thread?.revision ?? state.revision;
            if (!Number.isInteger(revision)) throw new Error("thread_revision_missing");
            const operation = crypto.randomUUID ? crypto.randomUUID() : `switch-${Date.now()}-${Math.random().toString(16).slice(2)}`;
            const response = await window.threadDeskWrite(`/threads/${encodeURIComponent(threadId)}/switch`, {
              body: new URLSearchParams({expected_revision: String(revision), operation_id: operation})});
            if (!response.ok) throw new Error("switch_rejected");
            location.assign(link.href);
          } catch (_) { link.textContent = t("browser.save_uncertain"); }
        });
        item.appendChild(link);
        detailMeta.appendChild(item);
      }
    };

  return showDetail;
};
