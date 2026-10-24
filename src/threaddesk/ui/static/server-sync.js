/* Refresh observed sync state without replacing edited project settings. */
(() => {
  'use strict';
  const state = document.getElementById('desktop-sync-status');
  if (!state) return;
  const labels = JSON.parse(state.dataset.stateLabels);
  const detail = document.getElementById('desktop-sync-error');
  const issues = document.getElementById('desktop-sync-issues');
  let pending = false;
  async function refresh() {
    if (pending || document.hidden) return;
    pending = true;
    try {
      const response = await fetch(state.dataset.statusUrl, {credentials:'same-origin', cache:'no-store'});
      if (!response.ok) throw new Error();
      const value = await response.json();
      const observed = value.status || {state:'unconfigured'};
      state.textContent = labels[observed.state] || labels.pending;
      detail.textContent = observed.detail || observed.error || '';
      issues.replaceChildren();
      for (const issue of observed.issues || []) {
        const line = document.createElement('p'); line.textContent = issue; issues.append(line);
      }
    } catch {
      state.textContent = labels.disconnected;
    } finally { pending = false; }
  }
  window.setInterval(refresh, 5000);
})();
