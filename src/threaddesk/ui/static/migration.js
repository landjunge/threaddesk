(() => {
  const file = document.querySelector('[data-testid="bundle-file"]');
  const confirm = document.querySelector('[data-testid="import-confirm"]');
  const summary = document.querySelector('[data-migration-summary]');
  if (!file || !confirm || !summary) return;
  file.addEventListener('change', () => {
    const selected = file.files && file.files[0];
    const valid = Boolean(selected && selected.name.toLowerCase().endsWith('.tdbundle'));
    confirm.disabled = !valid;
    summary.textContent = valid ? selected.name : 'Bitte eine .tdbundle-Datei auswählen.';
  });
})();
