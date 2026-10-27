/* Deliver only explicit, revision-bound view intents to this graph document. */
(() => {
  const root = document.querySelector('[data-graph-endpoint]');
  if (!root) return;
  let client = null, started = false, stopped = false, invalidated = root.graphWorkspace.invalidated, awaitingWorkspace = true;
  let graphReady = false, workspaceReady = false;
  let lastHeartbeat = 0, running = false, timer = null;
  const observations = new Map();
  if (invalidated) { stopped = true;root.dataset.viewControlStatus = 'workspace_changed'; }
  const base = '/api/graph/view-control';
  async function request(path, body, authenticated = true) {
    const headers = {'Content-Type': 'application/json'};
    if (authenticated && client) headers['X-ThreadDesk-View-Client'] = client.client_token;
    const response = body === undefined ? await fetch(path, {headers, cache: 'no-store'}) :
      await window.threadDeskWrite(path, {headers, body: JSON.stringify(body)});
    const result = await response.json();
    if (invalidated) throw Error('workspace_changed');
    if (!response.ok || result.ok === false) throw Object.assign(Error(result.code || 'view_delivery_unavailable'), result);
    return result.result || result;
  }
  async function consume(intent) {
    const address = `${base}/${encodeURIComponent(client.client_id)}`;
    let observation = observations.get(intent.operation_id)?.body;
    if (!observation) {
      await request(address + '/claim', {operation_id: intent.operation_id});
      try {
        const view = await request(`/api/graph/views/${encodeURIComponent(intent.view_id)}`);
        if (view.revision !== intent.view_revision) {
          observation = {operation_id: intent.operation_id, status: 'revision_conflict', error_code: 'revision_conflict'};
        } else {
          await root.graphController.restore(view.state);
          root.dispatchEvent(new CustomEvent('threaddesk:graph-view-loaded', {detail: view.state}));
          await window.ThreadDeskMapViewport.stable(root.querySelector('[data-map-stage]'));
          await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
          observation = {operation_id: intent.operation_id, status: 'applied', observed_state: root.graphController.snapshot()};
        }
      } catch (error) {
        observation = {operation_id: intent.operation_id, status: 'failed',
          error_code: /^[A-Za-z0-9_.:-]{1,100}$/.test(error.message || '') ? error.message : 'view_apply_failed'};
      }
      observations.set(intent.operation_id, {at: Date.now(), body: observation});
    }
    // An uncertain acknowledgement is retried with the original observation.
    // It never reapplies a view over a camera the user subsequently changed.
    await confirm(intent.operation_id, observation);
  }
  async function confirm(operation, observation) {
    const result = await request(`${base}/${encodeURIComponent(client.client_id)}/ack`, observation);
    root.dataset.viewControlOperation = operation;
    root.dataset.viewControlStatus = result.status;
    observations.delete(operation);
  }
  async function tick() {
    if (stopped || running) return;
    running = true;
    // Cleanup must also run while the transport is failing.
    for (const [id, value] of observations) if (Date.now() - value.at > 15 * 60 * 1000) observations.delete(id);
    try {
      if (!client) {
        if (awaitingWorkspace) return;
        client = await request(base + '/connect', {workspace_id: root.graphWorkspace.id}, false);
        root.dataset.viewClientId = client.client_id;lastHeartbeat = Date.now();
      }
      if (!document.hidden) {
        const address = `${base}/${encodeURIComponent(client.client_id)}`;
        if (Date.now() - lastHeartbeat > 30000) {
          await request(address + '/heartbeat', {});lastHeartbeat = Date.now();
        }
        const pending = await request(address + '/pending');
        for (const intent of pending.requests) await consume(intent);
        // A committed ACK can disappear from pending before its HTTP response
        // reaches us. Its idempotent readback still must settle our local state.
        for (const [id, value] of observations) await confirm(id, value.body);
      }
    } catch (error) {
      if (invalidated) return;
      if (error.code === 'workspace_conflict') {
        root.graphWorkspace.accept(null);
        root.dispatchEvent(new CustomEvent('threaddesk:graph-workspace-check'));
        return;
      }
      root.dataset.viewControlStatus = 'waiting';
      if (error.code === 'view_client_denied') {
        client = null;
        // Observations belong to the old capability, never the next client.
        observations.clear();
        awaitingWorkspace = true;
        root.dispatchEvent(new CustomEvent('threaddesk:graph-workspace-check'));
      }
    } finally { running = false; if (!stopped) timer = setTimeout(tick, 1500); }
  }
  root.addEventListener('threaddesk:graph-loaded', () => {
    graphReady = true;
    if (!started && workspaceReady && !invalidated) { started = true; tick(); }
  });
  window.addEventListener('pagehide', () => { stopped = true; clearTimeout(timer); });
  root.addEventListener('threaddesk:workspace-changed', () => {
    invalidated = true;stopped = true;clearTimeout(timer);client = null;observations.clear();
    delete root.dataset.viewClientId;
    root.dataset.viewControlStatus = 'workspace_changed';
  });
  root.addEventListener('threaddesk:graph-workspace-checked', event => {
    if (!invalidated && root.graphWorkspace.accept(event.detail.workspace_id)) {
      awaitingWorkspace = false;workspaceReady = true;
      if (!started && graphReady) { started = true; tick(); }
    }
  });
  window.addEventListener('pageshow', event => {
    if (event.persisted && started && stopped && !invalidated) { stopped = false; tick(); }
  });
})();
