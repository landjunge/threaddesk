/* Read-only invalidation reuses the graph controller and preserves drafts. */
(() => {
  const root = document.querySelector('[data-graph-endpoint]');
  if (!root) return;
  const strings = JSON.parse(root.dataset.strings || '{}');
  const labels = {pending: strings['map.live_pending'], workspace: strings['map.live_workspace'],
    error: strings['map.live_error'], updating: strings['map.live_updating']};
  const notice = root.querySelector('[data-map-live]');
  const message = root.querySelector('[data-map-live-message]');
  const update = root.querySelector('[data-map-live-update]');
  const drafts = new Set();
  let baseline = null, pending = null, running = false, applying = false;
  let timer = null, stopped = false, controller = null, pointer = false, workspaceChanged = false;
  const field = element => element?.matches('input,textarea,select,[contenteditable="true"]');
  function show(state) {
    root.dataset.liveStatus = state;
    notice.hidden = state === 'ready';
    message.textContent = state === 'ready' ? '' : labels[state];
    update.disabled = state === 'updating';
  }
  function blocked(explicit = false) {
    if (pointer || root.graphController?.interacting() || root.querySelector('dialog[open]')) return true;
    if (explicit) return false;
    if (field(document.activeElement) && root.contains(document.activeElement)) return true;
    return [...drafts].some(element => root.contains(element) && (!element.closest('dialog') || element.closest('dialog').open));
  }
  async function apply(explicit = false) {
    if (!pending || applying || stopped || document.hidden) return;
    if (blocked(explicit)) { show(workspaceChanged ? 'workspace' : 'pending'); return; }
    if (workspaceChanged) { location.reload(); return; }
    const target = pending;
    applying = true;show('updating');
    try {
      const confirmed = await root.graphController.refresh(() => !blocked(explicit));
      if (!confirmed) {
        if (blocked(explicit)) { show('pending');return; }
        throw Error('graph_refresh_unavailable');
      }
      baseline = target;
      if (pending === target) pending = null;
      if (explicit) drafts.clear();
      root.dispatchEvent(new CustomEvent('threaddesk:graph-live-updated'));
      show(pending ? 'pending' : 'ready');
    } catch (_) { show('error'); }
    finally { applying = false; }
  }
  function schedule() {
    clearTimeout(timer);
    if (!stopped && !document.hidden) timer = setTimeout(tick, 7500);
  }
  async function tick() {
    if (stopped || document.hidden || running) return;
    running = true;controller = new AbortController();
    const requestController = controller;
    const timeout = setTimeout(() => requestController.abort(), 5000);
    try {
      const response = await fetch('/api/graph/change-status', {cache: 'no-store', signal: controller.signal});
      const status = await response.json();
      if (!response.ok || status.status !== 'ready' || typeof status.fingerprint !== 'string' || !status.workspace_id)
        throw Error('graph_change_status_unavailable');
      if (!root.graphWorkspace.accept(status.workspace_id)) {
        workspaceChanged = true;pending = status;show('workspace');await apply();
      } else if (!baseline) { baseline = status;show('ready'); }
      else if (status.fingerprint !== baseline.fingerprint || status.minute !== baseline.minute) {
        pending = status;await apply();
      } else if (root.dataset.liveStatus === 'error') show(pending ? 'pending' : 'ready');
      if (!workspaceChanged) root.dispatchEvent(new CustomEvent('threaddesk:graph-workspace-checked', {detail: {workspace_id: status.workspace_id}}));
    } catch (error) { if (error.name !== 'AbortError' || !document.hidden && !stopped) show('error'); }
    finally { clearTimeout(timeout);controller = null;running = false;schedule(); }
  }
  update.addEventListener('click', () => pending ? apply(true) : tick());
  root.addEventListener('threaddesk:graph-workspace-check', tick);
  root.addEventListener('threaddesk:workspace-changed', () => { workspaceChanged = true; });
  root.addEventListener('input', event => { if (field(event.target)) drafts.add(event.target); });
  root.addEventListener('focusout', () => setTimeout(() => apply(), 0));
  root.addEventListener('close', () => apply(), true);
  root.querySelector('[data-map-stage]').addEventListener('pointerdown', () => { pointer = true; });
  window.addEventListener('pointerup', () => { pointer = false;setTimeout(() => apply(), 0); });
  window.addEventListener('pointercancel', () => { pointer = false;setTimeout(() => apply(), 0); });
  document.addEventListener('visibilitychange', () => {
    clearTimeout(timer);
    if (document.hidden) controller?.abort();else tick();
  });
  window.addEventListener('pagehide', () => { stopped = true;clearTimeout(timer);controller?.abort(); });
  window.addEventListener('pageshow', event => { if (event.persisted) { stopped = false;tick(); } });
  show('ready');tick();
})();
