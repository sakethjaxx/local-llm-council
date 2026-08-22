// ── APP BOOTSTRAP ──
function initApp() {
  initTheme();
  initResizer();
  initPressFeedback();
  initDragAndDrop();
  initKeyboardShortcuts();
  renderSeats();
  hydrateCloudKeys();
  setTokenBudgetProfile('balanced');
  fetchDemoCatalog();
  loadModelCatalog().then(() => renderSeats());
  loadHardwareDefaults();

  document.getElementById('attachmentInput')?.addEventListener('change', (event) => {
    const incoming = Array.from(event.target.files || []);
    const existingNames = new Set(selectedFiles.map(f => f.name));
    for (const f of incoming) {
      if (!existingNames.has(f.name)) selectedFiles.push(f);
    }
    event.target.value = '';
    renderSelectedFiles();
    refreshPreflight();
  });
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initApp);
} else {
  initApp();
}
