// Entry point: initialization + one delegated click/change listener.
// Boot

import { state } from './state.js?v=20260709-editable-names';
import { clearCloudKeys, hydrateCloudKeys, persistCloudKeys } from './api.js';
import {
  addSeat,
  applyDemoPreset,
  applyModelProfile,
  attachSample,
  autoConfigureHardware,
  bootstrapModels,
  checkFirstRun,
  copyPullCommand,
  fetchDemoCatalog,
  loadHardwareDefaults,
  loadPresetSamples,
  refreshPreflight,
  removeFile,
  removeSeat,
  renderSeats,
  renderSelectedFiles,
  renderSetupGuide,
  setDeepDebate,
  setTokenBudgetProfile,
  useInstalledRosterNow,
  updateSeat,
} from './config-panel.js?v=20260709-editable-names';
import { exportReport, launchCouncil, launchProjectReview, launchSelfReview, stopRun } from './run.js';
import { sendChat } from './chat.js';
import { closeReplayModal, loadReplayRunDetail, openReplayModal } from './replay.js';
import { closeMemory, viewCodeGraph, viewMemory } from './graphs.js';
import { jumpToMemberCard } from './render.js';
import { showToast } from './utils.js';

const actions = {
  'launch-council': () => launchCouncil(),
  'stop-run': () => stopRun(),
  'retry-run': () => launchCouncil(),
  'launch-project-review': () => launchProjectReview(),
  'launch-self-review': () => launchSelfReview(),
  'export-report': () => exportReport(),
  'send-chat': () => sendChat(),
  'open-replay': () => openReplayModal(),
  'close-replay': () => closeReplayModal(),
  'load-replay-run': (el) => loadReplayRunDetail(el.dataset.run),
  'view-memory': () => viewMemory(),
  'view-code-graph': () => viewCodeGraph(),
  'close-memory': () => closeMemory(),
  'apply-preset': (el) => applyDemoPreset(el.dataset.preset),
  'load-preset-samples': (el) => loadPresetSamples(el.dataset.preset),
  'attach-sample': (el) => attachSample(el.dataset.sample),
  'refresh-preflight': () => refreshPreflight(),
  'apply-model-profile': (el) => applyModelProfile(el.dataset.profile),
  'set-token-budget': (el) => setTokenBudgetProfile(el.dataset.profile),
  'clear-cloud-keys': () => clearCloudKeys(),
  'add-seat': () => addSeat(),
  'remove-seat': (el) => removeSeat(el.dataset.seat),
  'auto-configure-hardware': () => autoConfigureHardware(),
  'remove-file': (el) => removeFile(parseInt(el.dataset.index, 10)),
  'set-mode': (el) => setDeepDebate(el.dataset.mode === 'deliberate'),
  'jump-to-member': (el) => jumpToMemberCard(el.dataset.member),
  'show-setup': () => checkFirstRun().then(() => renderSetupGuideIfBlocked()),
  'bootstrap-models': () => bootstrapModels(),
  'use-installed-roster': () => useInstalledRosterNow(),
  'copy-pull-cmd': () => copyPullCommand(),
  'recheck-setup': () => recheckSetup(),
};

async function recheckSetup() {
  try {
    const resp = await fetch('/ollama/status');
    const status = await resp.json();
    if (status.ready) {
      const { resetPanelToEmptyState } = await import('./config-panel.js?v=20260709-editable-names');
      resetPanelToEmptyState();
      refreshPreflight();
    } else {
      renderSetupGuide(status);
    }
  } catch {
    renderSetupGuide(null);
  }
}

async function renderSetupGuideIfBlocked() {
  try {
    const resp = await fetch('/ollama/status');
    renderSetupGuide(await resp.json());
  } catch {
    renderSetupGuide(null);
  }
}

document.addEventListener('click', (event) => {
  const target = event.target.closest('[data-action]');
  if (!target) return;
  const handler = actions[target.dataset.action];
  if (handler) {
    event.preventDefault();
    handler(target);
  }
});

// Keyboard: mode options behave like radio buttons; Enter submits chat.
document.addEventListener('keydown', (event) => {
  if (event.key === 'Enter' && event.target.matches('[data-enter-action]')) {
    const handler = actions[event.target.dataset.enterAction];
    if (handler) {
      event.preventDefault();
      handler(event.target);
    }
  }
  if ((event.key === 'Enter' || event.key === ' ') && event.target.matches('.mode-option')) {
    event.preventDefault();
    setDeepDebate(event.target.dataset.mode === 'deliberate');
  }
});

// Seat edits (change events on dynamically rendered inputs).
document.addEventListener('change', (event) => {
  if (event.target.matches('[data-field][data-seat]')) {
    updateSeat(event.target.dataset.seat, event.target.dataset.field, event.target.value);
  }
});

document.addEventListener('input', (event) => {
  if (event.target.matches('.cloud-key-input')) {
    persistCloudKeys();
  }
  if (event.target.matches('#panelWidthRange')) {
    setPanelWidth(event.target.value);
  }
});

function setPanelWidth(value) {
  const width = Math.max(320, Math.min(560, parseInt(value, 10) || 390));
  document.documentElement.style.setProperty('--sidebar-width', `${width}px`);
  localStorage.setItem('llmCouncilPanelWidth', String(width));
  const range = document.getElementById('panelWidthRange');
  if (range) range.value = String(width);
}

function restorePanelWidth() {
  setPanelWidth(localStorage.getItem('llmCouncilPanelWidth') || '390');
}

const MAX_BROWSER_ATTACHMENTS = 10;

function addFilesToSelection(files, { preserveRelativePath = false } = {}) {
  const existingNames = new Set(state.selectedFiles.map((f) => f.name));
  let added = 0;
  let skipped = 0;
  for (const sourceFile of files) {
    if (state.selectedFiles.length >= MAX_BROWSER_ATTACHMENTS) {
      skipped += 1;
      continue;
    }
    const relativeName = preserveRelativePath && sourceFile.webkitRelativePath
      ? sourceFile.webkitRelativePath
      : sourceFile.name;
    if (existingNames.has(relativeName)) {
      skipped += 1;
      continue;
    }
    const file = relativeName === sourceFile.name
      ? sourceFile
      : new File([sourceFile], relativeName, { type: sourceFile.type, lastModified: sourceFile.lastModified });
    state.selectedFiles.push(file);
    existingNames.add(relativeName);
    added += 1;
  }
  if (skipped > 0) {
    showToast(`Added ${added} file${added === 1 ? '' : 's'}; skipped ${skipped}. Use local folder review for larger projects.`);
  }
}

// Boot
document.querySelectorAll('#projectReviewSection').forEach((section, index) => {
  if (index > 0) section.parentElement?.remove();
});
renderSeats();
hydrateCloudKeys();
restorePanelWidth();
setTokenBudgetProfile('balanced');
setDeepDebate(false);
fetchDemoCatalog();
loadHardwareDefaults();
checkFirstRun();

document.getElementById('attachmentInput').addEventListener('change', (event) => {
  const incoming = Array.from(event.target.files || []);
  addFilesToSelection(incoming);
  event.target.value = '';
  renderSelectedFiles();
  refreshPreflight();
});

document.getElementById('folderInput').addEventListener('change', (event) => {
  const incoming = Array.from(event.target.files || []);
  addFilesToSelection(incoming, { preserveRelativePath: true });
  event.target.value = '';
  renderSelectedFiles();
  refreshPreflight();
});
