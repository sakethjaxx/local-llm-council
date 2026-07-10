// Left panel: presets, preflight, seats, model profiles, mode selector,
// file attachments, and the first-run guided setup.

import { state, MODEL_PROFILES, TOKEN_BUDGET_SUMMARIES, LOCAL_MODEL_CHOICES, councilSeatIds } from './state.js?v=20260709-editable-names';
import { escapeHtml, showToast } from './utils.js';

// Section
export function renderPresets() {
  const grid = document.getElementById('presetGrid');
  if (!state.demoCatalog) {
    grid.innerHTML = '<div class="status-line">Loading demo presets...</div>';
    return;
  }
  grid.innerHTML = state.demoCatalog.presets
    .map(
      (preset) => `
    <div class="preset-card">
      <div class="preset-title">${escapeHtml(preset.label)}</div>
      <div class="preset-desc">${escapeHtml(preset.description)}</div>
      <div class="inline-actions">
        <button class="btn btn-small" data-action="apply-preset" data-preset="${escapeHtml(preset.id)}">Use preset</button>
        <button class="btn btn-small" data-action="load-preset-samples" data-preset="${escapeHtml(preset.id)}">Load sample files</button>
      </div>
    </div>`
    )
    .join('');
}

export function renderSampleActions() {
  const box = document.getElementById('sampleActions');
  if (!state.demoCatalog) {
    box.innerHTML = '';
    return;
  }
  box.innerHTML = (state.demoCatalog.samples || [])
    .map(
      (sample) =>
        `<button class="btn btn-small" data-action="attach-sample" data-sample="${escapeHtml(sample.id)}">${escapeHtml(sample.label)}</button>`
    )
    .join('');
}

export async function fetchDemoCatalog() {
  try {
    const resp = await fetch('/config/presets');
    state.demoCatalog = await resp.json();
    renderPresets();
    renderSampleActions();
  } catch (e) {
    console.error('Failed to load demo catalog', e);
  }
}

function configFromPreset(preset) {
  if (preset.config) return JSON.parse(JSON.stringify(preset.config));
  const seats = preset.seats || [];
  const keys = ['architect', 'security', 'perf'];
  const config = {};
  seats.slice(0, 3).forEach((seat, index) => {
    config[keys[index]] = {
      label: seat.label || `Seat ${index + 1}`,
      model: seat.model,
      color: seat.color || ['#4D6BFE', '#FF4444', '#00A76F'][index],
      icon: seat.icon || ['A', 'B', 'C'][index],
      persona: seat.persona || '',
    };
  });
  config.chairman = {
    label: 'Chairman',
    model: preset.chairman_model || 'ollama/qwen2.5:7b',
    color: '#F5C842',
    icon: 'C',
    persona: preset.chairman_persona || 'You are the Chairman. Synthesize the council into a decisive summary with concrete next steps.',
  };
  return config;
}

export async function applyDemoPreset(presetId) {
  if (!state.demoCatalog) return;
  const preset = state.demoCatalog.presets.find((item) => item.id === presetId);
  if (!preset) return;

  state.councilConfig = configFromPreset(preset);
  setModelProfileSelection(null);
  document.getElementById('topicText').value = preset.topic || preset.topic_placeholder || '';
  const toggles = preset.toggles || {};
  setDeepDebate(Boolean(toggles.deep_debate ?? preset.deep_debate));
  document.getElementById('dynamicSwarmToggle').checked = Boolean(toggles.dynamic_swarm ?? preset.dynamic_swarm);
  renderSeats();
  refreshPreflight();
}

export async function attachSample(sampleId) {
  if (!state.demoCatalog) return;
  const sample = (state.demoCatalog.samples || []).find((item) => item.id === sampleId);
  if (!sample) return;

  const resp = await fetch(`/demo-samples/${sample.filename}`);
  const blob = await resp.blob();
  const file = new File([blob], sample.filename, { type: sample.content_type || blob.type || 'text/plain' });
  state.selectedFiles = [...state.selectedFiles, file];
  renderSelectedFiles();
  refreshPreflight();
}

export async function loadPresetSamples(presetId) {
  if (!state.demoCatalog) return;
  const preset = state.demoCatalog.presets.find((item) => item.id === presetId);
  if (!preset) return;
  state.selectedFiles = [];
  const sampleIds =
    preset.sample_ids ||
    (preset.sample_files || [])
      .map((filename) => (state.demoCatalog.samples || []).find((sample) => sample.filename === filename)?.id)
      .filter(Boolean);
  for (const sampleId of sampleIds) {
    await attachSample(sampleId);
  }
  renderSelectedFiles();
  refreshPreflight();
}

// Section
export async function refreshPreflight() {
  const box = document.getElementById('preflightBox');
  box.innerHTML = '<div class="status-line">Running preflight checks...</div>';
  try {
    const resp = await fetch('/ollama/check', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        council_config: state.councilConfig,
        attachment_names: state.selectedFiles.map((file) => file.name),
      }),
    });
    state.preflightState = await resp.json();
    state.installedModels = state.preflightState.installed || [];
    renderModelDatalist();

    const statusClass = state.preflightState.ready ? 'status-good' : 'status-bad';
    const warnings = state.preflightState.warnings || [];
    const warningHtml = warnings.map((item) => `<div class="status-line status-warn">${escapeHtml(item)}</div>`).join('');
    const missingHtml = (state.preflightState.missing || []).length
      ? `<div class="status-line status-bad">Missing models: ${escapeHtml(state.preflightState.missing.join(', '))}</div>`
      : `<div class="status-line status-good">All required local models are installed.</div>`;
    const imageHtml = state.selectedFiles.some((file) => file.type.startsWith('image/'))
      ? `<div class="status-line ${state.preflightState.image_seats.length ? 'status-good' : 'status-warn'}">Image seats: ${escapeHtml((state.preflightState.image_seats || []).join(', ') || 'none')}</div>`
      : '';

    box.innerHTML = `
      <div class="preset-title ${statusClass}">${state.preflightState.ready ? 'Roster ready' : 'Roster blocked'}</div>
      <div class="status-line">Installed local models: ${escapeHtml(state.installedModels.join(', ') || 'none detected')}</div>
      ${missingHtml}
      ${imageHtml}
      ${warningHtml || '<div class="status-line">No warnings for the current setup.</div>'}
      ${!state.preflightState.ready ? '<button class="btn btn-small" data-action="show-setup">Open guided setup</button>' : ''}
    `;
  } catch (e) {
    console.error('Failed to refresh preflight', e);
    box.innerHTML = '<div class="status-line status-bad">Preflight failed. Check that the backend is running.</div>';
  }
}

export async function checkFirstRun() {
  try {
    const resp = await fetch('/ollama/status');
    const status = await resp.json();
    state.installedModels = status.installed || [];
    renderModelDatalist();
    if (!status.ready) {
      renderSetupGuide(status);
    }
  } catch (e) {
    renderSetupGuide(null);
  }
}

function installedModelIds() {
  return (state.installedModels || []).map((m) => (m.startsWith('ollama/') ? m : `ollama/${m}`));
}

function pickInstalledModel(preferences, installed) {
  for (const prefix of preferences) {
    const hit = installed.find((model) => model.startsWith(prefix));
    if (hit) return hit;
  }
  return null;
}

function buildInstalledStarterConfig() {
  const installed = installedModelIds();
  if (!installed.length) return null;

  const architect = pickInstalledModel([
    'ollama/qwen2.5:7b',
    'ollama/qwen2.5:3b',
    'ollama/qwen2.5-coder:7b',
    'ollama/qwen2.5-coder:14b',
    'ollama/llama3.1:8b',
    'ollama/llama3.2:',
    'ollama/mistral:7b',
    'ollama/gemma2:9b',
    'ollama/gemma2:2b',
  ], installed);
  const security = pickInstalledModel([
    'ollama/gemma2:9b',
    'ollama/gemma2:2b',
    'ollama/deepseek-r1:8b',
    'ollama/deepseek-r1:14b',
    'ollama/qwen2.5:7b',
    'ollama/qwen2.5:3b',
    'ollama/llama3.1:8b',
    'ollama/llama3.2:',
    'ollama/mistral:7b',
  ], installed);
  const perf = pickInstalledModel([
    'ollama/llama3.1:8b',
    'ollama/llama3.2:',
    'ollama/qwen2.5:7b',
    'ollama/qwen2.5:3b',
    'ollama/mistral:7b',
    'ollama/gemma2:2b',
    'ollama/gemma2:9b',
  ], installed);

  if (!architect || !security || !perf) return null;

  const chairman = pickInstalledModel([
    architect,
    'ollama/qwen2.5:7b',
    'ollama/qwen2.5:3b',
    'ollama/llama3.1:8b',
    'ollama/llama3.2:',
    security,
    perf,
  ], installed) || architect;

  return {
    architect: { ...state.councilConfig.architect, model: architect },
    security: { ...state.councilConfig.security, model: security },
    perf: { ...state.councilConfig.perf, model: perf },
    chairman: { ...state.councilConfig.chairman, model: chairman },
  };
}

function describeRoster(config) {
  if (!config) return 'none';
  return [config.architect, config.security, config.perf]
    .filter(Boolean)
    .map((seat) => seat.model.replace(/^ollama\//, ''))
    .join(', ');
}

export function renderSetupGuide(status) {
  const panel = document.getElementById('councilPanel');
  const serviceUp = status !== null;
  const required = (status && status.required) || [];
  const missing = (status && status.missing) || [];
  const installed = (status && status.installed) || [];
  state.installedModels = installed;
  state.setupInstalledConfig = buildInstalledStarterConfig();
  const installedStarter = state.setupInstalledConfig;
  const pullCommands = missing.map((m) => `ollama pull ${m.replace(/^ollama\//, '')}`).join('\n');
  const recommendedModels = required.length
    ? escapeHtml(required.join(', '))
    : 'We will show compatible local models once Ollama is reachable.';
  const installedModels = installed.length
    ? escapeHtml(installed.join(', '))
    : 'none detected yet';
  const setupStatus = serviceUp && missing.length === 0 ? 'done' : serviceUp ? 'pending' : 'blocked';
  const installedStarterText = installedStarter ? escapeHtml(describeRoster(installedStarter)) : '';
  const canStartNow = setupStatus === 'done' || Boolean(installedStarter);
  const setupStepTitle = installedStarter ? '3. Optional model upgrade' : '3. Model setup';
  const setupStepCopy = installedStarter
    ? 'You already have a lighter installed roster that can run now. The commands below are only if you want the hardware-recommended upgrade path.'
    : missing.length
      ? `Missing for the default roster: ${escapeHtml(missing.join(', '))}`
      : serviceUp ? 'All models for the default roster are already installed.' : 'Waiting on the Ollama service check.';

  panel.innerHTML = `
    <div class="setup-card" role="region" aria-label="First run setup">
      <h2>Set up your local council</h2>
      <p class="helper-copy">We first confirm Ollama is running, then show the default hardware-matched roster, then help you install any missing models, and only then move to the first council run.</p>
      <p class="helper-copy">The council runs entirely on your machine through Ollama - free, private, no API keys.</p>

      <div class="setup-step">
        <div class="step-status">${serviceUp ? 'OK' : 'NO'}</div>
        <div class="setup-step-body">
          <strong>1. Ollama service</strong>
          <div class="helper-copy">${serviceUp
            ? 'Ollama is reachable on localhost.'
            : 'Ollama is not reachable. Install it from <a href="https://ollama.com/download" target="_blank" rel="noopener">ollama.com/download</a>, make sure the Ollama app is running, then re-check.'}</div>
        </div>
      </div>

      <div class="setup-step">
        <div class="step-status">${serviceUp && missing.length === 0 ? 'OK' : 'TODO'}</div>
        <div class="setup-step-body">
          <strong>2. Compatible model roster</strong>
          <div class="helper-copy">These are the default models the app considers compatible with your current hardware tier. They are recommendations for the default roster, not a hard requirement for using the product.</div>
          <div class="setup-detail"><span>Recommended roster</span><span>${recommendedModels}</span></div>
          <div class="setup-detail"><span>Already installed</span><span>${installedModels}</span></div>
          ${installedStarter ? `<div class="setup-detail"><span>Can start now with</span><span>${installedStarterText}</span></div>` : ''}
          <div class="helper-copy">${serviceUp
            ? installedStarter
              ? 'You can start immediately with the installed roster below, or install the recommended roster if you want the stronger default.'
              : 'You can install these, or later swap seats to smaller models you already have.'
            : 'Once Ollama is reachable, we can confirm which recommended models are already present.'}</div>
          ${installedStarter ? `
            <div class="inline-actions">
              <button class="btn btn-solid" data-action="use-installed-roster">Use installed roster now</button>
            </div>` : ''}
        </div>
      </div>

      <div class="setup-step">
        <div class="step-status">${setupStatus === 'done' ? 'OK' : setupStatus === 'blocked' ? '...' : 'DO'}</div>
        <div class="setup-step-body">
          <strong>${setupStepTitle}</strong>
          <div class="helper-copy">${setupStepCopy}</div>
          ${missing.length ? `
            <div class="cmd-row">
              <pre class="cmd-block" id="pullCmd">${escapeHtml(pullCommands)}</pre>
              <button class="btn btn-small" data-action="copy-pull-cmd">Copy</button>
            </div>
            <div class="helper-copy">These commands are one-per-line so they paste cleanly into PowerShell, Terminal, or bash.</div>
            <div class="inline-actions">
              <button class="btn btn-solid" data-action="bootstrap-models">Pull models now</button>
            </div>
            <div class="pull-progress" id="pullProgress"></div>` : ''}
        </div>
      </div>

      <div class="setup-step">
        <div class="step-status">TODO</div>
        <div class="setup-step-body">
          <strong>4. Run your first council</strong>
          <div class="helper-copy">${canStartNow
            ? installedStarter && setupStatus !== 'done'
              ? 'Use the installed roster now, or install the recommended roster first if you want the stronger default.'
              : 'Pick a preset on the left, or paste a topic and hit Run council.'
            : 'Once the missing models are installed, come back here and run the council.'}</div>
        </div>
      </div>

      <div class="inline-actions" style="margin-top:14px">
        <button class="btn" data-action="recheck-setup">Re-check</button>
      </div>
    </div>
  `;
}

export async function bootstrapModels() {
  const progress = document.getElementById('pullProgress');
  if (progress) progress.textContent = 'Pulling models - this downloads several GB and can take a while...';

  const poll = setInterval(async () => {
    try {
      const resp = await fetch('/ollama/status');
      const status = await resp.json();
      if (progress) {
        const missing = status.missing || [];
        progress.textContent = missing.length
          ? `Still pulling - waiting on: ${missing.join(', ')}`
          : 'All models installed.';
      }
    } catch {}
  }, 4000);

  try {
    const resp = await fetch('/ollama/bootstrap', { method: 'POST' });
    const status = await resp.json();
    clearInterval(poll);
    if (status.ready) {
      showToast('Models installed - the council is ready.');
      resetPanelToEmptyState();
      refreshPreflight();
    } else {
      renderSetupGuide(status);
      showToast('Some models are still missing. Check the Ollama logs and retry.');
    }
  } catch (e) {
    clearInterval(poll);
    showToast('Model pull failed: ' + (e.message || 'unknown error'));
  }
}

export function useInstalledRosterNow() {
  if (!state.setupInstalledConfig) {
    showToast('No installed starter roster is available yet.');
    return;
  }
  state.councilConfig = JSON.parse(JSON.stringify(state.setupInstalledConfig));
  setModelProfileSelection(null);
  renderSeats();
  resetPanelToEmptyState();
  refreshPreflight();
  showToast('Using the installed local roster now.');
}

export function resetPanelToEmptyState() {
  const panel = document.getElementById('councilPanel');
  panel.innerHTML = `
    <div class="panel-empty">
      <div>Ready for a project brief.</div>
      <div class="helper-copy">Choose a preset, attach context, then run the council.</div>
    </div>
  `;
}

export async function copyPullCommand() {
  const cmd = document.getElementById('pullCmd');
  if (!cmd) return;
  try {
    await navigator.clipboard.writeText(cmd.textContent);
    showToast('Pull command copied.');
  } catch {
    showToast('Copy failed - select the text manually.');
  }
}

// Section
export function renderModelDatalist() {
  let datalist = document.getElementById('installedModels');
  if (!datalist) {
    datalist = document.createElement('datalist');
    datalist.id = 'installedModels';
    document.body.appendChild(datalist);
  }
  datalist.innerHTML = state.installedModels
    .map((m) => `<option value="${escapeHtml(m.startsWith('ollama/') ? m : 'ollama/' + m)}"></option>`)
    .join('');
}

function seatModelOptions(currentModel) {
  const installed = state.installedModels.map((m) => (m.startsWith('ollama/') ? m : `ollama/${m}`));
  const seen = new Set();
  const installedOptions = [];
  const commonOptions = [];

  for (const model of [currentModel, ...installed, ...LOCAL_MODEL_CHOICES]) {
    if (!model || seen.has(model)) continue;
    seen.add(model);
    const option = `<option value="${escapeHtml(model)}">${escapeHtml(model.replace(/^ollama\//, ''))}</option>`;
    if (installed.includes(model)) {
      installedOptions.push(option);
    } else {
      commonOptions.push(option);
    }
  }

  return `
    ${installedOptions.length ? `<optgroup label="Installed locally">${installedOptions.join('')}</optgroup>` : ''}
    <optgroup label="Common roster choices">${commonOptions.join('')}</optgroup>
  `;
}

const NON_BEHAVIOR_KEYS = new Set(['label', 'color', 'icon']);

function stableValue(value) {
  if (Array.isArray(value)) return value.map((item) => stableValue(item));
  if (value && typeof value === 'object') {
    return Object.keys(value)
      .sort()
      .reduce((out, key) => {
        out[key] = stableValue(value[key]);
        return out;
      }, {});
  }
  return value;
}

function seatBehaviorSignature(seat) {
  const behavioral = {};
  Object.keys(seat || {})
    .filter((key) => !NON_BEHAVIOR_KEYS.has(key))
    .sort()
    .forEach((key) => {
      behavioral[key] = stableValue(seat[key]);
    });
  return JSON.stringify(behavioral);
}

function normalizeSeatLabel(value, fallback = 'Expert') {
  const trimmed = String(value || '').trim();
  return trimmed || fallback;
}

function nextExpertLabel() {
  const used = new Set(
    Object.values(state.councilConfig || {})
      .map((seat) => normalizeSeatLabel(seat.label, '').toLowerCase())
      .filter(Boolean)
  );
  let index = 1;
  while (used.has(`expert ${index}`)) index += 1;
  return `Expert ${index}`;
}

export function renderSeats() {
  const list = document.getElementById('seatList');
  list.innerHTML = '';
  for (const [id, seat] of Object.entries(state.councilConfig)) {
    const isChairman = id === 'chairman';
    const label = normalizeSeatLabel(seat.label, isChairman ? 'Chairman' : 'Expert');
    const div = document.createElement('div');
    div.className = 'seat-item';
    div.innerHTML = `
      <div class="seat-header">
        <div class="seat-dot" style="background: ${escapeHtml(seat.color)}; color: ${escapeHtml(seat.color)}"></div>
        <div class="seat-title">${escapeHtml(seat.icon)} ${escapeHtml(label)}</div>
        <div class="seat-model">${escapeHtml((seat.model || '').split('/').pop())}</div>
        ${!isChairman ? `<button class="seat-remove" data-action="remove-seat" data-seat="${escapeHtml(id)}" aria-label="Remove ${escapeHtml(label)}" style="background:none;border:none;">x</button>` : ''}
      </div>
      <div class="seat-edit-fields">
        ${!isChairman ? `
        <label class="seat-field-label" for="label-${escapeHtml(id)}">Expert name</label>
        <input type="text" id="label-${escapeHtml(id)}" value="${escapeHtml(label)}" data-field="label" data-seat="${escapeHtml(id)}" aria-label="Expert name for ${escapeHtml(label)}" placeholder="Expert name">
        ` : ''}
        <label class="visually-hidden" for="model-${escapeHtml(id)}">Model for ${escapeHtml(label)}</label>
        <select id="model-${escapeHtml(id)}" data-field="model" data-seat="${escapeHtml(id)}" aria-label="Model for ${escapeHtml(label)}">
          ${seatModelOptions(seat.model)}
        </select>
        <label class="visually-hidden" for="persona-${escapeHtml(id)}">Persona for ${escapeHtml(label)}</label>
        <input type="text" id="persona-${escapeHtml(id)}" value="${escapeHtml(seat.persona)}" data-field="persona" data-seat="${escapeHtml(id)}" placeholder="System Persona Prompt">
        <div class="helper-copy">Installed models appear first in the dropdown, then the common local roster options.</div>
      </div>
    `;
    list.appendChild(div);
  }
  renderRosterDiversityWarning();
}

export function renderRosterDiversityWarning() {
  ['rosterWarning', 'duplicateLabelWarning'].forEach((id) => document.getElementById(id)?.remove());
  const list = document.getElementById('seatList');
  const seatIds = councilSeatIds();
  const seatModels = seatIds.map((id) => state.councilConfig[id]?.model || '');
  const distinct = new Set(seatModels.filter(Boolean));
  const distinctBehaviors = new Set(seatIds.map((id) => seatBehaviorSignature(state.councilConfig[id])));
  const warnings = [];
  if (seatModels.length > 1 && distinct.size === 1 && distinctBehaviors.size === 1) {
    const warn = document.createElement('div');
    warn.id = 'rosterWarning';
    warn.className = 'roster-warning';
    warn.setAttribute('role', 'alert');
    warn.textContent = `All ${seatModels.length} seats use the same model and behavior (${[...distinct][0]}). Their agreement is weak evidence, and the confidence score will be capped. Change a persona, generation parameter, or model.`;
    warnings.push(warn);
  }

  const duplicateGroups = new Map();
  for (const id of seatIds) {
    const seat = state.councilConfig[id] || {};
    const label = normalizeSeatLabel(seat.label).toLowerCase();
    const model = String(seat.model || '').toLowerCase();
    const key = `${label}|||${model}`;
    duplicateGroups.set(key, [...(duplicateGroups.get(key) || []), seat]);
  }
  const duplicate = [...duplicateGroups.values()].find((group) => group.length > 1);
  if (duplicate) {
    const label = normalizeSeatLabel(duplicate[0].label);
    const model = duplicate[0].model || 'unknown model';
    const warn = document.createElement('div');
    warn.id = 'duplicateLabelWarning';
    warn.className = 'roster-warning';
    warn.setAttribute('role', 'alert');
    warn.textContent = `${duplicate.length} seats share the name "${label}" and model ${model}. Rename one seat so run output and errors are easy to read.`;
    warnings.push(warn);
  }

  let anchor = list;
  for (const warn of warnings) {
    anchor.after(warn);
    anchor = warn;
  }
}

export function addSeat() {
  const id = 'seat_' + Math.floor(Math.random() * 1000);
  state.councilConfig[id] = {
    label: nextExpertLabel(),
    model: 'ollama/qwen2.5:7b',
    color: '#' + Math.floor(Math.random() * 16777215).toString(16).padStart(6, '0'),
    icon: 'E',
    persona: 'You are an expert.',
  };
  renderSeats();
  refreshPreflight();
}

export function removeSeat(id) {
  delete state.councilConfig[id];
  renderSeats();
  refreshPreflight();
}

export function updateSeat(id, field, value) {
  if (!state.councilConfig[id]) return;
  if (field === 'label') {
    state.councilConfig[id].label = normalizeSeatLabel(value, state.councilConfig[id].label || 'Expert');
  } else {
    state.councilConfig[id][field] = value;
  }
  if (field === 'model' || field === 'label') {
    if (field === 'model') setModelProfileSelection(null);
    renderSeats();
    if (field === 'model') refreshPreflight();
  }
}

export function applyModelProfile(profile) {
  const profileConfig = MODEL_PROFILES[profile];
  if (!profileConfig) return;
  for (const [id, seat] of Object.entries(state.councilConfig)) {
    if (profileConfig[id]) {
      seat.model = profileConfig[id];
    } else if (id !== 'chairman') {
      seat.model = profileConfig.architect;
    }
  }
  setModelProfileSelection(profile);
  renderSeats();
  refreshPreflight();
}

function setModelProfileSelection(profile) {
  state.selectedModelProfile = profile;
  document.querySelectorAll('[data-action="apply-model-profile"]').forEach((el) => {
    const isSelected = el.dataset.profile === profile;
    el.classList.toggle('selected', isSelected);
    el.setAttribute('aria-pressed', String(isSelected));
  });
}

export async function autoConfigureHardware() {
  try {
    const resp = await fetch('/hardware/suggest');
    const data = await resp.json();
    showToast(`Detected ${data.ram_gb} GB RAM - ${data.tier_name}. Roster updated.`);
    state.councilConfig = data.config;
    setModelProfileSelection(null);
    renderSeats();
    refreshPreflight();
  } catch (e) {
    console.error(e);
    showToast('Failed to auto-configure hardware. Is the backend running?');
  }
}

export async function loadHardwareDefaults() {
  try {
    const resp = await fetch('/hardware/suggest');
    const data = await resp.json();
    if (data && data.config) {
      state.councilConfig = data.config;
      setModelProfileSelection(null);
      renderSeats();
      refreshPreflight();
    }
  } catch (e) {
    console.error('Failed to load hardware defaults', e);
  }
}

// Section
export function removeFile(index) {
  state.selectedFiles.splice(index, 1);
  renderSelectedFiles();
  refreshPreflight();
}

export function renderSelectedFiles() {
  const fileList = document.getElementById('fileList');
  if (!state.selectedFiles.length) {
    fileList.innerHTML = '';
    return;
  }
  fileList.innerHTML = state.selectedFiles
    .map((file, i) => {
      const sizeKb = Math.max(1, Math.round(file.size / 1024));
      return `<div class="file-list-row">
        <span>${escapeHtml(file.name)} <span style="color:var(--warm)">(${sizeKb} KB)</span></span>
        <button data-action="remove-file" data-index="${i}" style="background:none;border:none;color:var(--warm);cursor:pointer;font-size:14px;padding:0 2px;line-height:1;" aria-label="Remove ${escapeHtml(file.name)}">x</button>
      </div>`;
    })
    .join('');
}

// Section
export function setDeepDebate(enabled) {
  state.deepDebate = Boolean(enabled);
  document.querySelectorAll('.mode-option').forEach((el) => {
    const isDeep = el.dataset.mode === 'deliberate';
    el.classList.toggle('selected', isDeep === state.deepDebate);
    el.setAttribute('aria-checked', String(isDeep === state.deepDebate));
  });
}

export function setTokenBudgetProfile(profile) {
  state.tokenBudgetProfile = ['economy', 'balanced', 'performance'].includes(profile) ? profile : 'balanced';
  const summary = document.getElementById('tokenBudgetSummary');
  if (summary) {
    summary.textContent = TOKEN_BUDGET_SUMMARIES[state.tokenBudgetProfile];
  }
  document.querySelectorAll('[data-action="set-token-budget"]').forEach((el) => {
    const isSelected = el.dataset.profile === state.tokenBudgetProfile;
    el.classList.toggle('selected', isSelected);
    el.setAttribute('aria-pressed', String(isSelected));
  });
}
