(() => {
  const file = document.querySelector('[data-testid="bundle-file"]');
  const confirm = document.querySelector('[data-testid="import-confirm"]');
  const dryRun = document.querySelector('[data-testid="run-dry-run"]');
  const summary = document.querySelector('[data-migration-summary]');
  const proposals = document.querySelector('[data-migration-proposals]');
  const evidence = document.querySelector('[data-migration-evidence]');
  const recover = document.querySelector('[data-testid="migration-recover"]');
  let reviewSha = null;
  let batchId = null;
  if (!file || !confirm || !dryRun || !summary || !proposals || !evidence || !recover) return;
  file.addEventListener('change', () => {
    const selected = file.files && file.files[0];
    const valid = Boolean(selected && selected.name.toLowerCase().endsWith('.tdbundle'));
    reviewSha = null; batchId = null; recover.hidden = true; confirm.disabled = true; dryRun.disabled = !valid;
    evidence.replaceChildren();
    summary.textContent = valid ? selected.name : uiText('browser.migration.choose_bundle');
    proposals.replaceChildren();
  });
  dryRun.addEventListener('click', async () => {
    if (!file.files || !file.files[0]) return;
    reviewSha = null; confirm.disabled = true; dryRun.disabled = true;
    summary.textContent = uiText('browser.migration.checking'); proposals.replaceChildren();
    const data = new FormData(); data.append('bundle', file.files[0]);
    try {
      const response = await fetch('/api/migration/dry-run', {method: 'POST', body: data});
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || 'preview_failed');
      summary.textContent = result.blockers.length
        ? uiText('browser.migration.blocked', {blockers: result.blockers.join(', ')})
        : uiText('browser.migration.ready', {hash: result.bundle_sha256.slice(0, 12)});
      result.proposals.forEach((item) => { const row = document.createElement('li'); row.textContent = item.diff + ': ' + item.title; proposals.append(row); });
      reviewSha = result.review_sha256 || null;
      confirm.disabled = !result.can_confirm_import || !reviewSha;
    } catch (error) { summary.textContent = uiText('browser.migration.failed', {reason: error.message}); }
    finally { dryRun.disabled = false; }
  });
  confirm.addEventListener('click', async () => {
    if (!reviewSha || confirm.disabled) return;
    confirm.disabled = true; summary.textContent = uiText('browser.migration.importing');
    const data = new FormData(); data.append('bundle_sha256', reviewSha);
    try {
      const response = await fetch('/api/migration/confirm', {method: 'POST', body: data});
      const result = await response.json();
      if (response.status === 202) { summary.textContent = uiText('browser.migration.uncertain', {batch: result.batch_id}); return; }
      if (!response.ok) throw new Error(result.detail || 'import_failed');
      batchId = result.id;
      summary.textContent = uiText('browser.migration.imported', {batch: result.id});
      evidence.replaceChildren();
      [result.backup_path, result.report_path].filter(Boolean).forEach((path) => {
        const row = document.createElement('li');
        row.textContent = path;
        evidence.append(row);
      });
      recover.hidden = !batchId;
    } catch (error) { summary.textContent = uiText('browser.migration.failed', {reason: error.message}); confirm.disabled = false; }
  });
  recover.addEventListener('click', async () => {
    if (!batchId) return;
    recover.disabled = true;
    const data = new FormData(); data.append('batch_id', batchId);
    try {
      const response = await fetch('/api/migration/recover', {method: 'POST', body: data});
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || 'recovery_failed');
      summary.textContent = uiText('browser.migration.recovered', {path: result.path});
    } catch (error) {
      summary.textContent = uiText('browser.migration.failed', {reason: error.message});
      recover.disabled = false;
    }
  });
})();
