(() => {
  const file = document.querySelector('[data-testid="bundle-file"]');
  const confirm = document.querySelector('[data-testid="import-confirm"]');
  const dryRun = document.querySelector('[data-testid="run-dry-run"]');
  const summary = document.querySelector('[data-migration-summary]');
  const proposals = document.querySelector('[data-migration-proposals]');
  const conflictSection = document.querySelector('[data-testid="migration-conflicts"]');
  const conflicts = document.querySelector('[data-migration-conflicts]');
  const evidence = document.querySelector('[data-migration-evidence]');
  const recover = document.querySelector('[data-testid="migration-recover"]');
  let reviewSha = null;
  let batchId = null;
  let bundleHash = null;
  let hardBlockers = [];
  let unresolvedConflicts = new Set();
  let resolutions = {};
  const actionLabels = {
    keep_local: uiText('browser.migration.keep_local'),
    take_source: uiText('browser.migration.take_source'),
  };
  const fieldLabels = {
    title: uiText('browser.migration.field_title'),
    status: uiText('browser.migration.field_status'),
    details: uiText('browser.migration.field_content'),
  };
  const appendVersion = (comparison, version, label, missingText = '') => {
    const panel = document.createElement('article');
    panel.className = 'migration-version';
    const heading = document.createElement('h4');
    heading.textContent = label;
    panel.append(heading);
    if (!version) {
      const missing = document.createElement('p');
      missing.className = 'muted';
      missing.textContent = missingText;
      panel.append(missing);
      comparison.append(panel);
      return;
    }
    const fields = document.createElement('dl');
    [
      [fieldLabels.title, version.title],
      [fieldLabels.status, version.status],
      [fieldLabels.details, version.details],
    ].forEach(([fieldLabel, value]) => {
      const row = document.createElement('div');
      const term = document.createElement('dt');
      const description = document.createElement('dd');
      term.textContent = fieldLabel;
      description.textContent = value || '—';
      row.append(term, description);
      fields.append(row);
    });
    panel.append(fields);
    comparison.append(panel);
  };
  if (!file || !confirm || !dryRun || !summary || !proposals || !conflictSection || !conflicts || !evidence || !recover) return;

  const updateConfirm = () => {
    const remaining = [...unresolvedConflicts].filter((sourceId) => !resolutions[sourceId]);
    confirm.disabled = !reviewSha || hardBlockers.length > 0 || remaining.length > 0;
    if (reviewSha && hardBlockers.length === 0 && unresolvedConflicts.size > 0) {
      summary.textContent = remaining.length
        ? uiText('browser.migration.conflicts_left', {count: remaining.length})
        : uiText('browser.migration.conflicts_resolved', {hash: bundleHash.slice(0, 12)});
    }
  };

  const renderConflict = (item) => {
    const card = document.createElement('section');
    card.className = 'card migration-conflict';
    card.dataset.conflictSource = item.source_id;
    const title = document.createElement('h3');
    title.textContent = uiText('browser.migration.conflict', {title: item.title});
    card.append(title);
    const comparison = document.createElement('div');
    comparison.className = 'migration-comparison';
    appendVersion(
      comparison,
      item.local_version,
      uiText('browser.migration.local_version'),
      uiText('browser.migration.missing_target')
    );
    appendVersion(comparison, item.source_version, uiText('browser.migration.source_version'));
    card.append(comparison);
    const actions = document.createElement('div');
    actions.className = 'actions';
    (item.allowed_actions || []).forEach((action) => {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'btn btn-ghost';
      button.dataset.action = action;
      button.setAttribute('aria-pressed', 'false');
      button.textContent = actionLabels[action];
      button.addEventListener('click', () => {
        resolutions[item.source_id] = {action, token: item.conflict_token};
        actions.querySelectorAll('button').forEach((candidate) => {
          candidate.setAttribute('aria-pressed', String(candidate === button));
        });
        updateConfirm();
      });
      actions.append(button);
    });
    card.append(actions);
    conflicts.append(card);
  };

  file.addEventListener('change', () => {
    const selected = file.files && file.files[0];
    const valid = Boolean(selected && selected.name.toLowerCase().endsWith('.tdbundle'));
    reviewSha = null; batchId = null; bundleHash = null; hardBlockers = [];
    unresolvedConflicts = new Set(); resolutions = {};
    recover.hidden = true; confirm.disabled = true; dryRun.disabled = !valid;
    evidence.replaceChildren();
    summary.textContent = valid ? selected.name : uiText('browser.migration.choose_bundle');
    proposals.replaceChildren();
    conflicts.replaceChildren(); conflictSection.hidden = true;
  });
  dryRun.addEventListener('click', async () => {
    if (!file.files || !file.files[0]) return;
    reviewSha = null; confirm.disabled = true; dryRun.disabled = true;
    summary.textContent = uiText('browser.migration.checking'); proposals.replaceChildren();
    conflicts.replaceChildren(); conflictSection.hidden = true; resolutions = {};
    const data = new FormData(); data.append('bundle', file.files[0]);
    try {
      const response = await fetch('/api/migration/dry-run', {method: 'POST', body: data});
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || 'preview_failed');
      summary.textContent = result.blockers.length
        ? uiText('browser.migration.blocked', {blockers: result.blockers.join(', ')})
        : uiText('browser.migration.ready', {hash: result.bundle_sha256.slice(0, 12)});
      result.proposals.forEach((item) => {
        const row = document.createElement('li');
        row.textContent = item.diff + ': ' + item.title;
        proposals.append(row);
        if (item.diff === 'conflict') renderConflict(item);
      });
      reviewSha = result.review_sha256 || null;
      bundleHash = result.bundle_sha256;
      hardBlockers = result.blockers.filter((blocker) => blocker !== 'conflict');
      unresolvedConflicts = new Set(
        result.proposals.filter((item) => item.diff === 'conflict').map((item) => item.source_id)
      );
      conflictSection.hidden = unresolvedConflicts.size === 0;
      updateConfirm();
    } catch (error) { summary.textContent = uiText('browser.migration.failed', {reason: error.message}); }
    finally { dryRun.disabled = false; }
  });
  confirm.addEventListener('click', async () => {
    if (!reviewSha || confirm.disabled) return;
    confirm.disabled = true; summary.textContent = uiText('browser.migration.importing');
    const data = new FormData();
    data.append('bundle_sha256', reviewSha);
    data.append('resolutions_json', JSON.stringify(resolutions));
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
    } catch (error) {
      summary.textContent = uiText('browser.migration.failed', {reason: error.message});
      if (error.message === 'resolution_stale') reviewSha = null;
      updateConfirm();
    }
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
