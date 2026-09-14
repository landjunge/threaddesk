(() => {
  const file = document.querySelector('[data-testid="bundle-file"]');
  const confirm = document.querySelector('[data-testid="import-confirm"]');
  const dryRun = document.querySelector('[data-testid="run-dry-run"]');
  const summary = document.querySelector('[data-migration-summary]');
  const proposals = document.querySelector('[data-migration-proposals]');
  if (!file || !confirm || !dryRun || !summary || !proposals) return;
  file.addEventListener('change', () => {
    const selected = file.files && file.files[0];
    const valid = Boolean(selected && selected.name.toLowerCase().endsWith('.tdbundle'));
    confirm.disabled = true;
    dryRun.disabled = !valid;
    summary.textContent = valid ? selected.name : uiText('browser.migration.choose_bundle');
    proposals.replaceChildren();
  });
  dryRun.addEventListener('click', async () => {
    if (!file.files || !file.files[0]) return;
    confirm.disabled = true;
    dryRun.disabled = true;
    summary.textContent = uiText('browser.migration.checking');
    proposals.replaceChildren();
    const data = new FormData();
    data.append('bundle', file.files[0]);
    try {
      const response = await fetch('/api/migration/dry-run', {method: 'POST', body: data});
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || 'preview_failed');
      summary.textContent = result.blockers.length
        ? uiText('browser.migration.blocked', {blockers: result.blockers.join(', ')})
        : uiText('browser.migration.ready', {hash: result.bundle_sha256.slice(0, 12)});
      result.proposals.forEach((item) => {
        const row = document.createElement('li');
        row.textContent = `${item.diff}: ${item.title}`;
        proposals.append(row);
      });
      confirm.disabled = !result.can_confirm_import;
    } catch (error) {
      summary.textContent = uiText('browser.migration.failed', {reason: error.message});
    } finally {
      dryRun.disabled = false;
    }
  });
})();
