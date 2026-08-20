// ── UTIL ──
function cssVar(name, fallback) {
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback;
}

function prefersReducedMotion() {
  return window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

function scrollWithMotion(element, block = 'nearest') {
  element?.scrollIntoView({ behavior: prefersReducedMotion() ? 'auto' : 'smooth', block });
}

// ── STATE ──
let councilConfig = {
  "architect": { label: "Lead Architect", model: "ollama/qwen2.5:7b", color: "#0071E3", icon: "A", persona: "You are the Lead Architect. Focus on SOLID principles, design patterns, maintainability, and code structure. Favor pragmatic, local-first solutions and call out unnecessary complexity." },
  "security": { label: "Security Auditor", model: "ollama/gemma2:9b", color: "#D70015", icon: "S", persona: "You are the Senior Security Auditor. Focus strictly on OWASP vulnerabilities, injection flaws, unsafe defaults, and exposure risk. Prefer defenses that work in local self-hosted deployments." },
  "perf": { label: "Performance Eng", model: "ollama/llama3.1:8b", color: "#248A3D", icon: "P", persona: "You are the Performance Engineer. Focus on algorithmic cost, memory pressure, context bloat, and latency. Optimize for hardware-constrained local inference." },
  "chairman": { label: "Chairman", model: "ollama/qwen2.5:7b", color: "#5856D6", icon: "C", persona: "You are the Chairman. Synthesize the council and make a final verdict. Prefer recommendations that preserve free, open-weight, local execution." }
};

let chatHistory = [];
let rawCardContents = {};
let thinkingCards = {};
let ph2Section, ph3Section;
let selectedFiles = [];
let demoCatalog = null;
let preflightState = null;
const CLOUD_KEY_STORAGE_KEY = 'llmCouncilCloudKeys';
const THEME_STORAGE_KEY = 'llmCouncilTheme';
let tokenBudgetProfile = 'balanced';

const TOKEN_BUDGET_SUMMARIES = {
  economy: 'Economy profile: shorter answers for lower latency on smaller local models.',
  balanced: 'Balanced profile: standard council token caps.',
  performance: 'Performance profile: longer answers with higher latency and memory cost.',
  quality: 'Quality profile: ample analysis and synthesis space; expect slower local runs.'
};

const MODEL_PROFILES = {
  turbo: {
    architect: "ollama/qwen2.5:3b",
    security: "ollama/gemma2:2b",
    perf: "ollama/llama3.2:3b",
    chairman: "ollama/qwen2.5:3b"
  },
  balanced: {
    architect: "ollama/qwen2.5:7b",
    security: "ollama/gemma2:9b",
    perf: "ollama/llama3.1:8b",
    chairman: "ollama/qwen2.5:7b"
  },
  quality: {
    architect: "ollama/qwen2.5:14b",
    security: "ollama/deepseek-r1:14b",
    perf: "ollama/llama3.1:8b",
    chairman: "ollama/qwen2.5:14b"
  }
};

function escapeHtml(value) {
  return String(value || '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

marked.setOptions({ gfm: true, breaks: true });

function sanitizeHtml(html) {
  if (window.DOMPurify) {
    return DOMPurify.sanitize(html, { USE_PROFILES: { html: true } });
  }
  return escapeHtml(html || '');
}

function renderMarkdown(text) {
  return sanitizeHtml(marked.parse(text || ''));
}

// ── 1-CLICK RESET SESSION ──
function resetSession() {
  selectedFiles = [];
  rawCardContents = {};
  thinkingCards = {};
  chatHistory = [];
  ph2Section = null;
  ph3Section = null;

  document.getElementById('topicText').value = '';
  document.getElementById('projectPathInput').value = '';
  document.getElementById('projectScanInfo').textContent = '';
  document.getElementById('presetSelect').value = '';
  document.getElementById('presetDesc').textContent = 'Choose a preset to set models, starter topic text, and sample files.';
  
  renderSelectedFiles();
  
  const panel = document.getElementById('councilPanel');
  panel.innerHTML = `
    <div class="panel-empty">
      <div class="empty-material">
        <div class="empty-eyebrow">Ready</div>
        <div class="empty-title">Choose context, then run the council.</div>
        <div class="helper-copy">Start from a preset, attach files, or scan a local project. Output streams here phase by phase.</div>
        <div class="empty-steps" aria-label="Council run phases">
          <span>Analyze</span>
          <span>Review</span>
          <span>Synthesize</span>
        </div>
        <div class="helper-copy hardware-reason" id="hardwareReason"></div>
      </div>
    </div>
  `;

  const btn = document.getElementById('launchBtn');
  btn.disabled = false;
  btn.innerHTML = 'Run council';

  showToast('Session reset cleanly.');
}

// ── THEME TOGGLE ──
function toggleTheme() {
  const toggle = document.getElementById('themeToggle');
  const isDark = toggle ? toggle.checked : (document.body.getAttribute('data-theme') !== 'dark');

  if (isDark) {
    document.body.setAttribute('data-theme', 'dark');
    localStorage.setItem(THEME_STORAGE_KEY, 'dark');
  } else {
    document.body.removeAttribute('data-theme');
    localStorage.setItem(THEME_STORAGE_KEY, 'light');
  }
}

function initTheme() {
  const saved = localStorage.getItem(THEME_STORAGE_KEY);
  const prefersDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
  const shouldBeDark = saved === 'dark' || (!saved && prefersDark);

  if (shouldBeDark) {
    document.body.setAttribute('data-theme', 'dark');
  } else {
    document.body.removeAttribute('data-theme');
  }

  const toggle = document.getElementById('themeToggle');
  if (toggle) {
    toggle.checked = shouldBeDark;
  }
}

// ── LOCAL PROJECT HELPER FUNCTIONS ──
let projectScanTimer = null;

function projectFileBudget() {
  const raw = parseInt(document.getElementById('projectFileBudget')?.value, 10);
  if (!Number.isFinite(raw)) return 25;
  return Math.max(1, Math.min(raw, 120));
}

/** Debounced dry-run scan so you see what the council will actually read
 *  BEFORE burning a full run on a wrong path. */
function scheduleProjectScan() {
  clearTimeout(projectScanTimer);
  projectScanTimer = setTimeout(previewProjectScan, 600);
}

async function previewProjectScan() {
  const path = document.getElementById('projectPathInput')?.value.trim();
  const infoDiv = document.getElementById('projectScanInfo');
  const preview = document.getElementById('projectFilePreview');
  if (!path) {
    if (infoDiv) infoDiv.textContent = '';
    if (preview) preview.innerHTML = '';
    return;
  }

  if (infoDiv) infoDiv.textContent = 'Scanning...';
  try {
    const resp = await fetch(`/project/code-graph?path=${encodeURIComponent(path)}`);
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      if (infoDiv) infoDiv.textContent = err.detail || `Cannot scan path (HTTP ${resp.status}).`;
      if (preview) preview.innerHTML = '';
      return;
    }
    const data = await resp.json();
    const total = data.stats?.files || 0;
    if (!total) {
      if (infoDiv) infoDiv.textContent = 'No supported source files found at this path.';
      if (preview) preview.innerHTML = '';
      return;
    }
    const budget = projectFileBudget();
    const willRead = Math.min(total, budget);
    if (infoDiv) infoDiv.textContent = `Found ${total} source files · council will read ${willRead}`;
    if (preview) {
      const names = (data.nodes || []).slice(0, willRead).map(n => n.id);
      preview.innerHTML = names.map(n => `<span class="file-chip">${escapeHtml(n)}</span>`).join('');
    }
  } catch (e) {
    if (infoDiv) infoDiv.textContent = 'Scan failed. Is the backend running?';
  }
}

async function bulkIngestFolder() {
  const path = document.getElementById('projectPathInput')?.value.trim();
  if (!path) return alert('Enter a local folder path to ingest.');
  
  const infoDiv = document.getElementById('projectScanInfo');
  const budget = projectFileBudget();
  if (infoDiv) infoDiv.textContent = `Bulk ingesting up to ${budget} files...`;
  
  try {
    const resp = await fetch('/ingest/folder', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ folder_path: path, max_files: budget })
    });
    
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      const msg = err.detail || 'Folder ingestion failed';
      alert(`Ingest failed: ${msg}`);
      if (infoDiv) infoDiv.textContent = msg;
      return;
    }
    
    const data = await resp.json();
    const attachments = data.attachments || [];
    if (!attachments.length) {
      if (infoDiv) infoDiv.textContent = 'No supported code or text files found in that folder.';
      return;
    }

    const existingNames = new Set(selectedFiles.map(f => f.name));
    let addedCount = 0;
    for (const att of attachments) {
      const fname = att.filename || 'attachment.txt';
      if (!existingNames.has(fname) && att.text) {
        const file = new File([att.text], fname, { type: att.content_type || 'text/plain' });
        selectedFiles.push(file);
        existingNames.add(fname);
        addedCount++;
      }
    }

    renderSelectedFiles();
    refreshPreflight();

    const topic = document.getElementById('topicText');
    if (topic && !topic.value.trim()) {
      const folderName = path.split('/').filter(Boolean).pop() || 'project';
      topic.value = `Review architecture, code quality, and potential risks for ${folderName}.`;
    }
    
    if (infoDiv) infoDiv.textContent = `Ingested ${data.file_count} files as active attachments.`;
    showToast(`Added ${addedCount} file(s) from ${path.split('/').pop() || 'folder'} as attachments.`);
  } catch (e) {
    alert(`Folder ingest error: ${e.message}`);
    if (infoDiv) infoDiv.textContent = '';
  }
}

// ── RESIZABLE SIDEBAR SPLITTER ──
function initResizer() {
  const resizer = document.getElementById('dragResizer');
  if (!resizer) return;

  let activePointerId = null;

  const setSidebarWidth = (clientX) => {
    const windowWidth = window.innerWidth;
    const maxSidebar = Math.min(500, Math.floor(windowWidth * 0.46));
    const newWidth = Math.min(Math.max(clientX, 300), maxSidebar);
    document.documentElement.style.setProperty('--sidebar-width', `${newWidth}px`);
  };

  const finishDrag = () => {
    activePointerId = null;
    resizer.classList.remove('dragging');
    document.body.style.cursor = '';
    document.body.style.userSelect = '';
  };

  resizer.addEventListener('pointerdown', (event) => {
    activePointerId = event.pointerId;
    resizer.classList.add('dragging');
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
    try { resizer.setPointerCapture(event.pointerId); } catch {}
    setSidebarWidth(event.clientX);
    event.preventDefault();
  });

  resizer.addEventListener('pointermove', (event) => {
    if (activePointerId !== event.pointerId) return;
    setSidebarWidth(event.clientX);
  });

  ['pointerup', 'pointercancel', 'lostpointercapture'].forEach((type) => {
    resizer.addEventListener(type, finishDrag);
  });
}

function initPressFeedback() {
  document.addEventListener('pointerdown', (event) => {
    if (event.target.closest('input, textarea, select')) return;
    const target = event.target.closest('.btn, .replay-run-item');
    if (!target || target.disabled) return;

    target.classList.add('is-pressed');
    const release = () => target.classList.remove('is-pressed');
    target.addEventListener('pointerup', release, { once: true });
    target.addEventListener('pointercancel', release, { once: true });
    target.addEventListener('lostpointercapture', release, { once: true });
    try { target.setPointerCapture(event.pointerId); } catch {}
  });
}

function showToast(message) {
  let stack = document.getElementById('toastStack');
  if (!stack) {
    stack = document.createElement('div');
    stack.id = 'toastStack';
    stack.className = 'toast-stack';
    document.body.appendChild(stack);
  }
  const toast = document.createElement('div');
  toast.className = 'toast';
  toast.textContent = message || 'Something went wrong.';
  stack.appendChild(toast);
  setTimeout(() => toast.remove(), 5500);
}

function renderLoadingState(panel, message) {
  panel.innerHTML = `
    <div class="run-skeleton">
      <div class="empty-material">
        <div class="empty-eyebrow">Running</div>
        <div class="empty-title">${escapeHtml(message || 'Starting council run...')}</div>
        <div class="helper-copy">Streaming will begin as soon as the first model starts producing tokens.</div>
        <div class="skeleton-line"></div>
        <div class="skeleton-line short"></div>
      </div>
    </div>
  `;
}

function renderErrorState(panel, message) {
  panel.innerHTML = `
    <div class="status-card">
      <div class="preset-title status-bad">Run failed</div>
      <div class="status-line status-bad">${escapeHtml(message || 'Unknown error')}</div>
    </div>
  `;
}

function loadCloudKeys() {
  try {
    return JSON.parse(localStorage.getItem(CLOUD_KEY_STORAGE_KEY) || '{}');
  } catch (e) {
    return {};
  }
}

function persistCloudKeys() {
  const keys = {
    openai: document.getElementById('keyOpenAI')?.value.trim() || '',
    anthropic: document.getElementById('keyAnthropic')?.value.trim() || '',
    gemini: document.getElementById('keyGemini')?.value.trim() || '',
    groq: document.getElementById('keyGroq')?.value.trim() || ''
  };
  localStorage.setItem(CLOUD_KEY_STORAGE_KEY, JSON.stringify(keys));
}

function hydrateCloudKeys() {
  const keys = loadCloudKeys();
  if (document.getElementById('keyOpenAI')) document.getElementById('keyOpenAI').value = keys.openai || '';
  if (document.getElementById('keyAnthropic')) document.getElementById('keyAnthropic').value = keys.anthropic || '';
  if (document.getElementById('keyGemini')) document.getElementById('keyGemini').value = keys.gemini || '';
  if (document.getElementById('keyGroq')) document.getElementById('keyGroq').value = keys.groq || '';
}

function clearCloudKeys() {
  localStorage.removeItem(CLOUD_KEY_STORAGE_KEY);
  hydrateCloudKeys();
  showToast('Cloud API keys cleared.');
}

function setTokenBudgetProfile(profile) {
  tokenBudgetProfile = ['economy', 'balanced', 'performance', 'quality'].includes(profile) ? profile : 'balanced';
  const summary = document.getElementById('tokenBudgetSummary');
  if (summary) {
    summary.textContent = TOKEN_BUDGET_SUMMARIES[tokenBudgetProfile];
  }
}

function rosterStrategy() {
  return document.getElementById('rosterStrategy')?.value || 'auto';
}

function updateRosterStrategySummary(data) {
  const summary = document.getElementById('rosterStrategySummary');
  if (!summary) return;
  summary.textContent = data?.reason || 'Auto keeps the most suitable models resident when possible.';
}

function cloudKeyHeaders() {
  const keys = loadCloudKeys();
  const headers = {};
  if (keys.openai) headers['X-OpenAI-API-Key'] = keys.openai;
  if (keys.anthropic) headers['X-Anthropic-API-Key'] = keys.anthropic;
  if (keys.gemini) headers['X-Gemini-API-Key'] = keys.gemini;
  if (keys.groq) headers['X-Groq-API-Key'] = keys.groq;
  return headers;
}

function syncToggles(preset) {
  const toggles = preset.toggles || {};
  document.getElementById('deepDebateToggle').checked = Boolean(toggles.deep_debate ?? preset.deep_debate);
  document.getElementById('dynamicSwarmToggle').checked = Boolean(toggles.dynamic_swarm ?? preset.dynamic_swarm);
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
      icon: seat.icon || ['◆', '◇', '○'][index],
      persona: seat.persona || ''
    };
  });
  config.chairman = {
    label: 'Chairman',
    model: preset.chairman_model || 'ollama/qwen2.5:7b',
    color: '#F5C842',
    icon: '👑',
    persona: preset.chairman_persona || 'You are the Chairman. Synthesize the council into a decisive summary with concrete next steps.'
  };
  return config;
}

function renderPresets() {
  const select = document.getElementById('presetSelect');
  if (!demoCatalog || !select) return;

  select.innerHTML = '<option value="">Select a demo preset...</option>' +
    demoCatalog.presets.map(preset => `
      <option value="${preset.id}">${escapeHtml(preset.label)}</option>
    `).join('');
}

async function onPresetSelected(presetId) {
  if (!presetId || !demoCatalog) return;
  const preset = demoCatalog.presets.find(item => item.id === presetId);
  if (!preset) return;

  document.getElementById('presetDesc').textContent = preset.description || '';
  councilConfig = fitModelsToHardware(configFromPreset(preset));
  document.getElementById('topicText').value = preset.topic || preset.topic_placeholder || '';
  syncToggles(preset);
  renderSeats();
  
  await loadPresetSamples(presetId);
  refreshPreflight();
}

function renderSampleActions() {
  const box = document.getElementById('sampleActions');
  if (!demoCatalog || !box) return;
  box.innerHTML = (demoCatalog.samples || []).map(sample => `
    <button class="btn btn-small" onclick="attachSample('${sample.id}')">${escapeHtml(sample.label)}</button>
  `).join('');
}

async function fetchDemoCatalog() {
  try {
    const resp = await fetch('/config/presets');
    demoCatalog = await resp.json();
    renderPresets();
    renderSampleActions();
  } catch (e) {
    console.error('Failed to load demo catalog', e);
  }
}

async function attachSample(sampleId) {
  if (!demoCatalog) return;
  const sample = (demoCatalog.samples || []).find(item => item.id === sampleId);
  if (!sample) return;

  const resp = await fetch(`/demo-samples/${sample.filename}`);
  const blob = await resp.blob();
  const file = new File([blob], sample.filename, { type: sample.content_type || blob.type || 'text/plain' });
  selectedFiles = [...selectedFiles, file];
  renderSelectedFiles();
  refreshPreflight();
}

async function loadPresetSamples(presetId) {
  if (!demoCatalog) return;
  const preset = demoCatalog.presets.find(item => item.id === presetId);
  if (!preset) return;
  selectedFiles = [];
  const sampleIds = preset.sample_ids || (preset.sample_files || [])
    .map(filename => (demoCatalog.samples || []).find(sample => sample.filename === filename)?.id)
    .filter(Boolean);
  for (const sampleId of sampleIds) {
    await attachSample(sampleId);
  }
  renderSelectedFiles();
  refreshPreflight();
}

async function refreshPreflight() {
  const box = document.getElementById('preflightBox');
  if (!box) return;
  box.innerHTML = '<div class="status-line">Running preflight checks...</div>';
  try {
    const resp = await fetch('/ollama/check', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        council_config: councilConfig,
        attachment_names: selectedFiles.map(file => file.name)
      })
    });
    preflightState = await resp.json();

    const statusClass = preflightState.ready ? 'status-good' : 'status-bad';
    const warnings = preflightState.warnings || [];
    const warningHtml = warnings.map(item => `<div class="status-line status-warn">${escapeHtml(item)}</div>`).join('');
    const missingHtml = (preflightState.missing || []).length
      ? `<div class="status-line status-bad">Missing models: ${escapeHtml(preflightState.missing.join(', '))}</div>`
      : `<div class="status-line status-good">All required local models installed.</div>`;

    box.innerHTML = `
      <div class="preset-title ${statusClass}">${preflightState.ready ? 'Demo roster ready' : 'Demo roster blocked'}</div>
      ${missingHtml}
      ${warningHtml || '<div class="status-line">No demo warnings for current setup.</div>'}
    `;
  } catch (e) {
    box.innerHTML = '<div class="status-line status-bad">Preflight failed. Backend check offline.</div>';
  }
}

// ── MODEL CATALOG (shared by the roster picker and the model library) ──
let modelCatalog = null;

const CLOUD_MODEL_CHOICES = [
  { model_id: 'openai/gpt-4o-mini', label: 'gpt-4o-mini (OpenAI key)' },
  { model_id: 'openai/gpt-4o', label: 'gpt-4o (OpenAI key)' },
  { model_id: 'anthropic/claude-sonnet-4-20250514', label: 'claude-sonnet-4 (Anthropic key)' },
  { model_id: 'gemini/gemini-2.0-flash', label: 'gemini-2.0-flash (Gemini key)' },
  { model_id: 'groq/llama-3.3-70b-versatile', label: 'llama-3.3-70b (Groq key)' },
];

async function loadModelCatalog(force = false) {
  if (modelCatalog && !force) return modelCatalog;
  try {
    const resp = await fetch('/models/catalog');
    if (!resp.ok) return null;
    modelCatalog = await resp.json();
  } catch (e) {
    modelCatalog = null;
  }
  return modelCatalog;
}

function installedModelIds() {
  if (!modelCatalog) return [];
  return modelCatalog.models.filter(m => m.installed).map(m => m.model_id);
}

function updateRosterFitSummary() {
  const summary = document.getElementById('rosterFitSummary');
  if (!summary || !modelCatalog) return;
  if (document.getElementById('dynamicSwarmToggle')?.checked) {
    summary.textContent = 'Dynamic Swarm adapts analyst personas while keeping the selected hardware-fitted model slots.';
    return;
  }

  const modelById = new Map(modelCatalog.models.map(model => [model.model_id, model]));
  const analystModels = Object.entries(councilConfig)
    .filter(([id]) => id !== 'chairman')
    .map(([, seat]) => seat.model);
  const distinctLocal = [...new Set(analystModels.filter(model => model.startsWith('ollama/')))];
  const unknown = distinctLocal.filter(model => !modelById.has(model));
  if (unknown.length) {
    summary.textContent = 'Combination estimate is unavailable for a custom local model. Verify its Ollama size before running it in parallel.';
    return;
  }

  const factor = modelCatalog.concurrency_factor || 1.4;
  const required = distinctLocal.reduce((total, model) => total + modelById.get(model).size_gb, 0) * factor;
  const budget = modelCatalog.budget_gb;
  const chair = councilConfig.chairman?.model;
  const chairmanSize = modelById.get(chair)?.size_gb;
  const chairmanRequired = chairmanSize ? chairmanSize * factor : null;
  const analystNames = distinctLocal.map(model => model.split('/').pop()).join(' + ') || 'cloud/custom analysts';
  const chairmanNote = chairmanRequired
    ? ` Chairman phase: ${chair.split('/').pop()} needs ~${chairmanRequired.toFixed(1)}GB.`
    : '';

  if (required <= budget) {
    summary.textContent = `Fits: ${analystNames} need ~${required.toFixed(1)}GB concurrently (budget ~${budget.toFixed(1)}GB).${chairmanNote}`;
  } else {
    summary.textContent = `Does not fit concurrently: ${analystNames} need ~${required.toFixed(1)}GB, above the ~${budget.toFixed(1)}GB budget. Choose smaller analysts or use a shared/mixed roster.${chairmanNote}`;
  }
}

/** Options for one seat's model <select>, grouped by what actually runs today. */
function buildModelOptions(selectedModel) {
  const installed = [];
  const available = [];
  const tooBig = [];

  for (const m of (modelCatalog ? modelCatalog.models : [])) {
    const size = `${m.size_gb.toFixed(1)}GB`;
    if (m.installed) installed.push({ id: m.model_id, label: `${m.tag} · ${size}` });
    else if (m.fits_now) available.push({ id: m.model_id, label: `${m.tag} · ${size} · not downloaded` });
    else tooBig.push({ id: m.model_id, label: `${m.tag} · ${size} · needs ~${m.min_ram_gb.toFixed(0)}GB RAM` });
  }

  const groups = [
    ['Installed locally', installed],
    ['Available to download', available],
    ['Cloud (needs API key)', CLOUD_MODEL_CHOICES.map(c => ({ id: c.model_id, label: c.label }))],
    ['Too large for this machine', tooBig],
  ];

  const known = new Set(groups.flatMap(([, items]) => items.map(i => i.id)));
  let html = '';
  if (selectedModel && !known.has(selectedModel)) {
    html += `<option value="${escapeHtml(selectedModel)}" selected>${escapeHtml(selectedModel)} (custom)</option>`;
  }
  for (const [label, items] of groups) {
    if (!items.length) continue;
    html += `<optgroup label="${escapeHtml(label)}">`;
    for (const item of items) {
      const sel = item.id === selectedModel ? ' selected' : '';
      html += `<option value="${escapeHtml(item.id)}"${sel}>${escapeHtml(item.label)}</option>`;
    }
    html += `</optgroup>`;
  }
  html += `<option value="__custom__">Enter a custom model id…</option>`;
  return html;
}

// ── SEAT BUILDER UI ──
function renderSeats() {
  const list = document.getElementById('seatList');
  if (!list) return;
  list.innerHTML = '';
  const installed = new Set(installedModelIds());
  for (const [id, seat] of Object.entries(councilConfig)) {
    const isChairman = id === 'chairman';
    const isLocal = seat.model.startsWith('ollama/');
    const ready = !isLocal || installed.has(seat.model) || !modelCatalog;
    const div = document.createElement('div');
    div.className = 'seat-item';
    div.innerHTML = `
      <div class="seat-header">
        <div class="seat-dot" style="background: ${seat.color}; color: ${seat.color}"></div>
        <div class="seat-title">${seat.icon} ${seat.label}</div>
        <div class="seat-model ${ready ? '' : 'seat-model-missing'}" title="${escapeHtml(seat.model)}${ready ? '' : ' — not installed'}">${escapeHtml(seat.model.split('/').pop())}${ready ? '' : ' ⚠'}</div>
        ${!isChairman ? `<div class="seat-remove" onclick="removeSeat('${id}')" title="Remove seat">✕</div>` : ''}
      </div>
      <div class="seat-edit-fields">
        <select class="seat-model-select" onchange="onSeatModelPicked('${id}', this)" aria-label="Model for ${escapeHtml(seat.label)}">
          ${buildModelOptions(seat.model)}
        </select>
        <input type="text" value="${escapeHtml(seat.persona)}" onchange="updateSeat('${id}', 'persona', this.value)" placeholder="System Persona Prompt">
      </div>
    `;
    list.appendChild(div);
  }
  updateRosterFitSummary();
}

function onSeatModelPicked(id, selectEl) {
  if (selectEl.value === '__custom__') {
    const current = councilConfig[id] ? councilConfig[id].model : '';
    const entered = prompt('Model id (LiteLLM format, e.g. ollama/qwen2.5:7b):', current);
    if (!entered) return renderSeats();
    return updateSeat(id, 'model', entered.trim());
  }
  updateSeat(id, 'model', selectEl.value);
}

function addSeat() {
  const id = 'seat_' + Math.floor(Math.random() * 1000);
  councilConfig[id] = {
    label: "New Expert",
    model: "ollama/qwen2.5:7b",
    color: "#" + Math.floor(Math.random()*16777215).toString(16),
    icon: "N",
    persona: "You are an expert."
  };
  renderSeats();
  refreshPreflight();
}

function removeSeat(id) {
  delete councilConfig[id];
  renderSeats();
  refreshPreflight();
}

function updateSeat(id, field, value) {
  if(councilConfig[id]) councilConfig[id][field] = value;
  if (field === 'model') {
    renderSeats();
    refreshPreflight();
  }
}

/** Pick a model from what is actually installed, sized for the requested profile.
 *  Falls back to the hardcoded table only when the catalog is unavailable, so
 *  Turbo/Quality stop pointing at models this machine has never downloaded. */
function pickInstalledModel(profile, fallback) {
  if (!modelCatalog) return fallback;
  const installed = modelCatalog.models
    .filter(m => m.installed)
    .sort((a, b) => a.size_gb - b.size_gb);
  if (!installed.length) return fallback;

  if (profile === 'turbo') return installed[0].model_id;
  if (profile === 'quality') return installed[installed.length - 1].model_id;
  return installed[Math.floor((installed.length - 1) / 2)].model_id;
}

function applyModelProfile(profile) {
  const profileConfig = MODEL_PROFILES[profile];
  if (!profileConfig) return;

  for (const [id, seat] of Object.entries(councilConfig)) {
    const fallback = profileConfig[id] || profileConfig.architect;
    seat.model = pickInstalledModel(profile, fallback);
  }

  renderSeats();
  refreshPreflight();
  showToast(`${profile[0].toUpperCase()}${profile.slice(1)} profile applied to all seats.`);
}

function removeFile(index) {
  selectedFiles.splice(index, 1);
  renderSelectedFiles();
  refreshPreflight();
}

const PROMPT_TEMPLATES = {
  security: "Conduct an OWASP Top 10 security audit. Focus on authentication/authorization gaps, injection vectors, unauthenticated endpoints, and secrets exposure risk.",
  perf: "Audit this codebase for runtime performance bottlenecks, memory pressure, unbounded loops, inefficient DB queries, and latency optimization opportunities.",
  refactor: "Analyze this code for SOLID principles, coupling, code duplication, maintainability risks, and propose the top 3 highest-value refactoring steps.",
  pr: "Review this pull request diff for correctness bugs, edge cases, breaking API changes, and code quality before merging.",
  incident: "Triage this incident / error log. Identify the root cause, cascading failure vectors, immediate mitigation steps, and long-term prevention mechanisms."
};

function insertPromptTemplate(type) {
  const textarea = document.getElementById('topicText');
  if (!textarea) return;
  const template = PROMPT_TEMPLATES[type] || '';
  textarea.value = template;
  textarea.focus();
  showToast(`Inserted ${type.toUpperCase()} review template.`);
}

function renderSelectedFiles() {
  const fileList = document.getElementById('fileList');
  if (!fileList) return;
  if (!selectedFiles.length) {
    fileList.innerHTML = '';
    return;
  }
  fileList.innerHTML = selectedFiles.map((file, i) => {
    const sizeKb = Math.max(1, Math.round(file.size / 1024));
    const estTokens = Math.max(1, Math.round(file.size / 4));
    return `<div class="file-row">
      <span>${escapeHtml(file.name)} <span class="file-size">(${sizeKb} KB)</span> <span class="file-token-chip">~${estTokens.toLocaleString()} tokens</span></span>
      <button class="remove-file-button" onclick="removeFile(${i})" title="Remove">X</button>
    </div>`;
  }).join('');
}

async function autoConfigureHardware(silent = false) {
  try {
    const resp = await fetch(`/hardware/suggest?strategy=${encodeURIComponent(rosterStrategy())}`);
    const data = await resp.json();
    if (!resp.ok) throw new Error('Hardware suggestion failed');
    if (!silent) {
      const swapNotice = data.requires_phase_model_swap ? '\n\nThe chairman model reloads before synthesis for a stronger final answer.' : '';
      alert(`Hardware Scan Complete.\n\nDetected RAM: ${data.ram_gb} GB\nHardware Tier: ${data.tier_name}\n\n${data.reason}${swapNotice}`);
    }
    councilConfig = data.config;
    updateRosterStrategySummary(data);
    renderSeats();
    refreshPreflight();
  } catch (e) {
    alert("Failed to auto-configure hardware. Is the backend running?");
  }
}

async function enableQualityMode() {
  const strategy = document.getElementById('rosterStrategy');
  if (strategy) strategy.value = 'mixed';
  setTokenBudgetProfile('quality');
  const dynamic = document.getElementById('dynamicSwarmToggle');
  if (dynamic) dynamic.checked = false;
  const debate = document.getElementById('deepDebateToggle');
  if (debate) debate.checked = true;
  await autoConfigureHardware(true);
  showToast('Quality run enabled: mixed roster, deeper debate, and larger token budgets.');
}

let hardwareConfig = null;

function fitModelsToHardware(config) {
  if (!hardwareConfig) return config;
  for (const key of Object.keys(config)) {
    if (hardwareConfig[key] && hardwareConfig[key].model) {
      config[key].model = hardwareConfig[key].model;
    }
  }
  return config;
}

async function loadHardwareDefaults() {
  try {
    const resp = await fetch('/hardware/suggest?strategy=auto');
    const data = await resp.json();
    if (data && data.config) {
      hardwareConfig = data.config;
      councilConfig = data.config;
      renderSeats();
      refreshPreflight();
      const badge = document.getElementById('hardwareReason');
      if (badge && data.reason) {
        badge.textContent = `Roster fitted to ${data.ram_gb}GB — ${data.reason}`;
      }
      updateRosterStrategySummary(data);
    }
  } catch (e) {}
}

let activeCouncilAbortController = null;

function stopActiveRun() {
  if (activeCouncilAbortController) {
    activeCouncilAbortController.abort();
    activeCouncilAbortController = null;
    showToast('Council run stopped.');
  }
}

// ── COUNCIL EXECUTION ──
async function launchCouncil() {
  if (activeCouncilAbortController) {
    stopActiveRun();
    return;
  }

  const topic = document.getElementById('topicText').value.trim();
  if (!topic && !selectedFiles.length) return alert('Enter a topic or attach at least one file.');
  await refreshPreflight();
  if (!preflightState || !preflightState.ready) {
    return alert('Demo preflight failed. Install the missing models or switch to a preset that matches your local setup.');
  }

  const btn = document.getElementById('launchBtn');
  const panel = document.getElementById('councilPanel');
  btn.disabled = false;
  btn.classList.add('btn-danger');
  btn.innerHTML = 'Stop council';

  renderLoadingState(panel, 'Starting council run...');
  rawCardContents = {};
  thinkingCards = {};
  chatHistory = [];

  const formData = new FormData();
  formData.append('topic_text', topic);
  formData.append('council_config', JSON.stringify(councilConfig));
  formData.append('token_budget_profile', tokenBudgetProfile);
  for (const file of selectedFiles) {
    formData.append('attachments', file);
  }
  
  if (document.getElementById('dynamicSwarmToggle')?.checked) formData.append('dynamic_swarm', true);
  if (document.getElementById('deepDebateToggle')?.checked) formData.append('deep_debate', true);

  activeCouncilAbortController = new AbortController();

  try {
    const resp = await fetch('/council/stream', {
      method: 'POST',
      headers: cloudKeyHeaders(),
      body: formData,
      signal: activeCouncilAbortController.signal
    });
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      const message = err.detail || err.message || `Request failed with status ${resp.status}`;
      showToast(message);
      renderErrorState(panel, message);
      return;
    }

    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop();
      for (const line of lines) {
        if (line.startsWith('data: ')) {
          try {
            const ev = JSON.parse(line.slice(6));
            handleEvent(ev, panel);
          } catch {}
        }
      }
    }
  } catch (err) {
    if (err.name !== 'AbortError') {
      showToast(err.message || 'SSE connection failed.');
      renderErrorState(panel, err.message);
    }
  } finally {
    activeCouncilAbortController = null;
    btn.disabled = false;
    btn.classList.remove('btn-danger');
    btn.innerHTML = 'Run council';
  }
}

async function launchProjectReview() {
  if (activeCouncilAbortController) {
    stopActiveRun();
    return;
  }

  const path = document.getElementById('projectPathInput').value.trim();
  if (!path) return alert('Enter a project directory path to review.');

  const btn = document.getElementById('projectReviewBtn');
  const launchBtn = document.getElementById('launchBtn');
  const panel = document.getElementById('councilPanel');
  const infoDiv = document.getElementById('projectScanInfo');

  btn.disabled = true;
  btn.textContent = 'Scanning...';
  launchBtn.disabled = false;
  launchBtn.classList.add('btn-danger');
  launchBtn.textContent = 'Stop council';
  renderLoadingState(panel, `Scanning project at ${path.split('/').pop()} and preparing review...`);
  rawCardContents = {};
  thinkingCards = {};
  chatHistory = [];
  if (infoDiv) infoDiv.textContent = '';

  activeCouncilAbortController = new AbortController();

  try {
    const resp = await fetch('/council/review-project', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...cloudKeyHeaders() },
      body: JSON.stringify({
        path,
        deep_debate: document.getElementById('deepDebateToggle')?.checked || false,
        council_config: councilConfig,
        token_budget_profile: tokenBudgetProfile,
        max_files: projectFileBudget(),
      }),
      signal: activeCouncilAbortController.signal
    });

    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      const message = err.detail || err.message || `HTTP ${resp.status}: Path outside allowed root or unreadable`;
      showToast(message);
      renderErrorState(panel, message);
      return;
    }

    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop();
      for (const line of lines) {
        if (line.startsWith('data: ')) {
          try {
            const ev = JSON.parse(line.slice(6));
            if (ev.type === 'project_info' && infoDiv) {
              infoDiv.textContent = `Scanned ${ev.total_files} files → reviewing ${ev.files_selected.length} files`;
              const preview = document.getElementById('projectFilePreview');
              if (preview) {
                preview.innerHTML = ev.files_selected
                  .map(n => `<span class="file-chip">${escapeHtml(n)}</span>`).join('');
              }
            } else {
              handleEvent(ev, panel);
            }
          } catch {}
        }
      }
    }
  } catch (err) {
    if (err.name !== 'AbortError') {
      showToast(err.message || 'Project review connection failed.');
      renderErrorState(panel, err.message);
    }
  } finally {
    activeCouncilAbortController = null;
    btn.disabled = false;
    btn.textContent = 'Scan & Review';
    launchBtn.disabled = false;
    launchBtn.classList.remove('btn-danger');
    launchBtn.textContent = 'Run council';
  }
}

let memberTokenStats = {};
let latestChairmanPayload = null;

function playCompletionChime() {
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    const now = ctx.currentTime;
    
    const osc1 = ctx.createOscillator();
    const gain1 = ctx.createGain();
    osc1.type = 'sine';
    osc1.frequency.setValueAtTime(587.33, now); // D5
    gain1.gain.setValueAtTime(0.10, now);
    gain1.gain.exponentialRampToValueAtTime(0.001, now + 0.3);
    osc1.connect(gain1);
    gain1.connect(ctx.destination);
    osc1.start(now);
    osc1.stop(now + 0.3);

    const osc2 = ctx.createOscillator();
    const gain2 = ctx.createGain();
    osc2.type = 'sine';
    osc2.frequency.setValueAtTime(880.00, now + 0.12); // A5
    gain2.gain.setValueAtTime(0.12, now + 0.12);
    gain2.gain.exponentialRampToValueAtTime(0.001, now + 0.55);
    osc2.connect(gain2);
    gain2.connect(ctx.destination);
    osc2.start(now + 0.12);
    osc2.stop(now + 0.55);
  } catch (e) {}
}

function sendDesktopNotification(title, body) {
  if (!("Notification" in window)) return;
  if (Notification.permission === "granted") {
    new Notification(title, { body });
  } else if (Notification.permission !== "denied") {
    Notification.requestPermission().then(permission => {
      if (permission === "granted") new Notification(title, { body });
    });
  }
}

function toggleActionDone(checkbox, idx) {
  const row = document.getElementById(`action-row-${idx}`);
  if (row) {
    if (checkbox.checked) row.classList.add('is-done');
    else row.classList.remove('is-done');
  }
}

async function copyVerdictForGitHub() {
  if (!latestChairmanPayload) return showToast("No completed verdict to copy.");
  const data = latestChairmanPayload;
  const isUncalibrated = data.risk_score === -1 || data.risk_score === '-1' || data.risk_score === null || data.risk_score === undefined;
  const riskDisplay = isUncalibrated ? '⚠️ Uncalibrated' : `${data.risk_score}/10`;
  md += `**Risk Score:** \`${riskDisplay}\`\n\n`;
  
  if (data.action_items && data.action_items.length) {
    md += `### 📋 Required Action Items\n`;
    data.action_items.forEach(item => {
      md += `- [ ] ${item}\n`;
    });
    md += `\n`;
  }
  
  if (data.consensus && data.consensus.length) {
    md += `### ✅ Consensus\n`;
    data.consensus.forEach(c => { md += `- ${c}\n`; });
    md += `\n`;
  }
  
  if (data.disputes && data.disputes.length) {
    md += `### ⚠️ Disagreements & Risk Warnings\n`;
    data.disputes.forEach(d => { md += `- ${d}\n`; });
    md += `\n`;
  }

  md += `<details>\n<summary>🔍 Expand Individual Council Member Critiques</summary>\n\n`;
  for (const [key, content] of Object.entries(rawCardContents)) {
    if (!key.startsWith('chairman')) {
      md += `#### ${key.toUpperCase()}\n\n${content}\n\n---\n`;
    }
  }
  md += `</details>\n\n*Generated locally with [LLM Council](https://github.com/sakethjaxx/local-llm-council)*`;

  try {
    await navigator.clipboard.writeText(md);
    showToast("📋 Copied GitHub PR Markdown to clipboard!");
  } catch (e) {
    showToast("Failed to copy to clipboard.");
  }
}

async function copyVerdictForSlack() {
  if (!latestChairmanPayload) return showToast("No completed verdict to copy.");
  const data = latestChairmanPayload;
  const isUncalibrated = data.risk_score === -1 || data.risk_score === '-1' || data.risk_score === null || data.risk_score === undefined;
  const riskDisplay = isUncalibrated ? '⚠️ Uncalibrated' : `${data.risk_score}/10`;
  let text = `👑 *LLM Council Verdict:* ${data.verdict || 'COMPLETE'} (Risk: ${riskDisplay})\n\n`;
  if (data.action_items && data.action_items.length) {
    text += `*Action Items:*\n`;
    data.action_items.forEach((item, i) => { text += `${i+1}. ${item}\n`; });
  }
  try {
    await navigator.clipboard.writeText(text);
    showToast("💬 Copied Slack summary to clipboard!");
  } catch (e) {
    showToast("Failed to copy to clipboard.");
  }
}

function handleEvent(ev, panel) {
  if (ev.type === 'error') {
    const message = ev.message || 'The council run failed.';
    showToast(message);
    panel.appendChild(Object.assign(document.createElement('div'), {
      className: 'status-card',
      innerHTML: `<div class="preset-title status-bad">Runtime error</div><div class="status-line status-bad">${escapeHtml(message)}</div>`
    }));
    return;
  }

  if (ev.type === 'phase_start') {
    const banner = document.createElement('div');
    banner.className = 'phase-banner';
    banner.innerHTML = `<span>PHASE ${ev.phase} // ${ev.label.toUpperCase()}</span>`;
    panel.appendChild(banner);

    const grid = document.createElement('div');
    grid.className = 'cards-grid';
    grid.id = `grid-phase${ev.phase}`;
    panel.appendChild(grid);

    if (ev.phase === 2) ph2Section = grid;
    if (ev.phase === 3) ph3Section = grid;
    scrollWithMotion(grid, 'end');
    return;
  }

  if (ev.type === 'member_thinking') {
    const phase = ev.phase || 1;
    const grid = document.getElementById(`grid-phase${phase}`);
    if (!grid) return;

    const card = buildCard(ev.member, ev.meta, null, phase);
    grid.appendChild(card);
    thinkingCards[`${ev.member}-${phase}`] = card;
    scrollWithMotion(card, 'nearest');
    return;
  }

  if (ev.type === 'member_token') {
    let phase = 1;
    if (ph3Section && ph3Section.contains(thinkingCards[`${ev.member}-3`])) phase = 3;
    else if (ph2Section && ph2Section.contains(thinkingCards[`${ev.member}-2`])) phase = 2;
    
    const key = `${ev.member}-${phase}`;
    const existing = thinkingCards[key];
    
    if (existing) {
      const body = existing.querySelector('.card-body');
      const pulse = existing.querySelector('.typing');
      if (pulse) { pulse.remove(); body.style.display = 'block'; }
      
      if (!rawCardContents[key]) rawCardContents[key] = '';
      rawCardContents[key] += ev.chunk;

      if (!memberTokenStats[key]) {
        memberTokenStats[key] = { count: 0, startTime: performance.now() };
      }
      memberTokenStats[key].count++;
      const speedEl = existing.querySelector('.card-speedometer');
      if (speedEl) {
        const elapsed = Math.max(0.1, (performance.now() - memberTokenStats[key].startTime) / 1000);
        const tps = (memberTokenStats[key].count / elapsed).toFixed(1);
        speedEl.textContent = `⚡ ${tps} tok/s · ${memberTokenStats[key].count} tok`;
      }

      if (ev.member !== 'chairman') {
        body.innerHTML = renderMarkdown(rawCardContents[key]);
      } else {
        body.innerHTML = `<pre>${escapeHtml(rawCardContents[key])}</pre>`;
      }
    }
    return;
  }
  
  if (ev.type === 'member_done') {
    let phase = 1;
    if (ph3Section && ph3Section.contains(thinkingCards[`${ev.member}-3`])) phase = 3;
    else if (ph2Section && ph2Section.contains(thinkingCards[`${ev.member}-2`])) phase = 2;
    const key = `${ev.member}-${phase}`;
    const existing = thinkingCards[key];
    
    if (existing && ev.member === 'chairman') {
      const body = existing.querySelector('.card-body');
      try {
        const data = JSON.parse(ev.full_text);
        latestChairmanPayload = data;
        let riskColor = "var(--accent)";
        if (data.risk_score >= 8) riskColor = "var(--danger)";
        else if (data.risk_score >= 5) riskColor = "var(--warm)";

        const isUncalibrated = data.risk_score === -1 || data.risk_score === '-1' || data.risk_score === null || data.risk_score === undefined;
        const riskDisplay = isUncalibrated ? '⚠️ Uncalibrated' : `${escapeHtml(data.risk_score)}/10`;
        let html = `
          <h2>VERDICT: ${escapeHtml(data.verdict || '')}</h2>
          <div class="risk-score" style="color: ${riskColor};">RISK SCORE: ${riskDisplay}</div>
          <h3>Action Items:</h3>
          <div class="action-item-list">
            ${(data.action_items || []).map((a, idx) => `
              <label class="action-item-row" id="action-row-${idx}">
                <input type="checkbox" class="action-checkbox" onchange="toggleActionDone(this, ${idx})">
                <span class="action-text">${escapeHtml(a)}</span>
              </label>
            `).join('')}
          </div>
          <div style="display:flex; gap:8px; margin: 12px 0 16px 0; flex-wrap:wrap;">
            <button class="btn btn-small copy-pr-btn" onclick="copyVerdictForGitHub()">📋 Copy for GitHub PR</button>
            <button class="btn btn-small copy-pr-btn" onclick="copyVerdictForSlack()">💬 Copy for Slack</button>
          </div>
        `;
        if (data.consensus && data.consensus.length > 0) html += `<h3>Consensus:</h3><ul>${data.consensus.map(c => `<li>${escapeHtml(c)}</li>`).join('')}</ul>`;
        if (data.disputes && data.disputes.length > 0) html += `<h3>Disputes:</h3><ul>${data.disputes.map(d => `<li>${escapeHtml(d)}</li>`).join('')}</ul>`;
        body.innerHTML = sanitizeHtml(html);
      } catch (e) {
        body.innerHTML = renderMarkdown(ev.full_text);
      }
    }
    return;
  }

  if (ev.type === 'done') {
    playCompletionChime();
    sendDesktopNotification("👑 Council Deliberation Complete", "Chairman has synthesized the verdict and action items.");
    return;
  }

  if (ev.type === 'warning') {
    showToast(ev.message || 'Council warning.');
    panel.appendChild(Object.assign(document.createElement('div'), {
      className: 'status-card',
      innerHTML: `<div class="status-line status-warn">${escapeHtml(ev.message || '')}</div>`
    }));
    return;
  }

  if (ev.type === 'shutdown') {
    showToast(ev.message || 'Server is shutting down.');
    panel.appendChild(Object.assign(document.createElement('div'), {
      className: 'status-card',
      innerHTML: `<div class="status-line status-bad">${escapeHtml(ev.message || 'Server shutdown requested.')}</div>`
    }));
    return;
  }
}

function buildCard(member, meta, content, phase) {
  const isChairman = member === 'chairman';
  const card = document.createElement('div');
  card.className = isChairman ? 'council-card chairman-card' : 'council-card';

  // Dynamic Swarm metadata is LLM-generated, so escape text and restrict the
  // value interpolated into the style attribute to a safe color literal.
  const rawColor = String(meta.color || '');
  const color = /^(#[0-9a-fA-F]{3,8}|[a-zA-Z]+)$/.test(rawColor) ? rawColor : 'var(--accent)';
  const label = escapeHtml(String(meta.label || member).toUpperCase());
  const icon = escapeHtml(meta.icon || member.slice(0, 1).toUpperCase());
  card.style.setProperty('--member-color', color);
  card.innerHTML = `
    <div class="card-header">
      <div style="display:flex; align-items:center; gap:8px;">
        <div class="card-icon">${icon}</div>
        <div class="card-name">${label}</div>
      </div>
      <div class="card-speedometer" id="speed-${member}-${phase}">⚡ 0.0 tok/s</div>
    </div>
    <div class="typing"><span></span><span></span><span></span></div>
    <div class="card-body" style="display:none"></div>
  `;
  return card;
}

// ── KNOWLEDGE GRAPH EXPORT ──
async function exportMemoryGraph() {
  try {
    const resp = await fetch('/memory-graph/export');
    if (!resp.ok) return showToast('Failed to export knowledge graph.');
    const data = await resp.json();
    const jsonStr = JSON.stringify(data, null, 2);
    const blob = new Blob([jsonStr], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `council_memory_${Date.now()}.graph.json`;
    a.click();
    showToast('Exported knowledge graph JSON successfully!');
  } catch (e) {
    showToast('Failed to export knowledge graph JSON.');
  }
}

// ── MEMORY GRAPH & CODE GRAPH VISUALIZATION ──
async function viewMemory() {
  const modal = document.getElementById('memoryModal');
  document.getElementById('modalTitle').textContent = 'Council Knowledge Graph';
  modal.style.display = 'flex';
  
  try {
    const resp = await fetch('/council/memory');
    const data = await resp.json();

    const edgeColors = {
      supports: '#2f5d50',
      contradicts: '#9f3d32',
      decision_about: '#9c7a4d',
      depends_on: '#2b5876',
      causes: '#73552f'
    };

    const formattedEdges = (data.edges || []).map(edge => ({
      ...edge,
      color: { color: edgeColors[edge.label] || 'rgba(47, 93, 80, 0.4)', highlight: '#9c7a4d' }
    }));
    
    const container = document.getElementById('memoryNetwork');
    const options = {
      nodes: {
        shape: 'dot', size: 14,
        font: { color: cssVar('--text', '#1f2823'), face: 'SFMono-Regular', size: 12 },
        color: { background: cssVar('--accent-soft', '#dde7e1'), border: cssVar('--accent', '#2f5d50') }
      },
      edges: {
        width: 2,
        font: { color: cssVar('--muted', '#58635d'), face: 'SFMono-Regular', size: 10, align: 'horizontal' },
        arrows: { to: { enabled: true, scaleFactor: 0.5 } },
        smooth: { type: 'continuous' }
      },
      physics: { barnesHut: { gravitationalConstant: -2800, centralGravity: 0.3 } }
    };

    new vis.Network(container, { nodes: data.nodes, edges: formattedEdges }, options);
  } catch (e) {
    alert("Failed to load memory graph.");
  }
}

function closeMemory() {
  document.getElementById('memoryModal').style.display = 'none';
}

async function viewCodeGraph() {
  const modal = document.getElementById('memoryModal');
  const pathInput = document.getElementById('projectPathInput')?.value.trim();
  const title = pathInput ? `Code Graph: ${pathInput.split('/').pop()}` : 'Project Code Graph';
  document.getElementById('modalTitle').textContent = title;
  modal.style.display = 'flex';

  try {
    const url = pathInput ? `/project/code-graph?path=${encodeURIComponent(pathInput)}` : '/project/code-graph';
    const resp = await fetch(url);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();

    const container = document.getElementById('memoryNetwork');
    const options = {
      nodes: {
        shape: 'dot', size: 14,
        font: { color: cssVar('--text', '#1f2823'), face: 'SFMono-Regular', size: 11 },
        color: { background: cssVar('--accent-soft', '#dde7e1'), border: cssVar('--accent', '#2f5d50') }
      },
      edges: {
        width: 1.5,
        color: { color: 'rgba(47, 93, 80, 0.35)', highlight: '#9c7a4d' },
        font: { color: cssVar('--muted', '#58635d'), face: 'SFMono-Regular', size: 10, align: 'horizontal' },
        arrows: { to: { enabled: true, scaleFactor: 0.45 } },
        smooth: { type: 'continuous' }
      },
      physics: { barnesHut: { gravitationalConstant: -2200, centralGravity: 0.28 } }
    };

    new vis.Network(container, { nodes: data.nodes, edges: data.edges }, options);
  } catch (e) {
    alert("Failed to load project code graph.");
  }
}

// ── MODEL LIBRARY ──
const MODEL_TIER_LABELS = {
  light: 'Light — fits any machine',
  medium: 'Medium',
  heavy: 'Heavy',
  very_heavy: 'Very Heavy — needs a lot of RAM'
};
const MODEL_TIER_ORDER = ['light', 'medium', 'heavy', 'very_heavy'];

async function openModelLibrary() {
  const modal = document.getElementById('modelLibraryModal');
  const body = document.getElementById('modelLibraryBody');
  modal.style.display = 'flex';
  body.innerHTML = '<div class="replay-empty">Loading models...</div>';

  const data = await loadModelCatalog(true);
  if (!data) {
    body.innerHTML = '<div class="replay-empty">Failed to load model catalog.</div>';
    return;
  }
  renderModelCatalog(data, body);
  renderSeats();
}

function closeModelLibrary() {
  document.getElementById('modelLibraryModal').style.display = 'none';
}

function renderModelCatalog(data, body) {
  const groups = {};
  for (const m of data.models) {
    (groups[m.tier] = groups[m.tier] || []).push(m);
  }

  let html = `<div class="helper-copy">
    Detected ${escapeHtml(String(data.ram_gb))}GB RAM · ~${escapeHtml(String(data.budget_gb))}GB usable for concurrent models.<br>
    ${escapeHtml(data.recommendation_reason || '')}
  </div>`;

  for (const tier of MODEL_TIER_ORDER) {
    const models = groups[tier];
    if (!models || !models.length) continue;
    html += `<div class="model-tier-title">${MODEL_TIER_LABELS[tier]}</div><div class="model-grid">`;
    for (const m of models) {
      const badges = [];
      if (m.installed) badges.push('<span class="badge badge-good">Installed</span>');
      if (m.recommended) badges.push('<span class="badge badge-accent">Recommended for you</span>');
      if (!m.installed && !m.fits_now) badges.push('<span class="badge badge-bad">Likely too large</span>');

      html += `
        <div class="model-card" id="model-card-${escapeHtml(m.tag)}">
          <div class="model-card-title">${escapeHtml(m.tag)}</div>
          <div class="model-card-meta">${m.size_gb.toFixed(1)}GB weights · needs ~${m.min_ram_gb.toFixed(0)}GB RAM</div>
          <div class="model-card-notes">${escapeHtml(m.notes || '')}</div>
          <div class="model-card-badges">${badges.join('')}</div>
          <div class="model-card-actions">
            ${m.installed
              ? `<button class="btn btn-small" disabled>Installed</button>`
              : `<button class="btn btn-small btn-solid" onclick="pullModel('${escapeHtml(m.tag)}')">Download</button>`}
          </div>
          <div class="model-card-progress" id="model-progress-${escapeHtml(m.tag)}"></div>
        </div>`;
    }
    html += `</div>`;
  }

  body.innerHTML = html;
}

function pullModel(tag) {
  const card = document.getElementById(`model-card-${tag}`);
  const btn = card ? card.querySelector('button') : null;
  const progressEl = document.getElementById(`model-progress-${tag}`);
  if (btn) { btn.disabled = true; btn.textContent = 'Downloading...'; }
  if (progressEl) progressEl.textContent = 'Starting download...';

  const es = new EventSource(`/models/pull/stream?tag=${encodeURIComponent(tag)}`);
  es.onmessage = (ev) => {
    let data;
    try { data = JSON.parse(ev.data); } catch { return; }

    if (data.type === 'line' && progressEl) {
      progressEl.textContent = data.text;
    } else if (data.type === 'error' && progressEl) {
      progressEl.textContent = data.message;
    } else if (data.type === 'done') {
      es.close();
      if (data.success) {
        if (progressEl) progressEl.textContent = 'Installed.';
        if (btn) btn.textContent = 'Installed';
        showToast(`${tag} installed.`);
        refreshPreflight();
      } else {
        if (btn) { btn.disabled = false; btn.textContent = 'Retry download'; }
        showToast(`Failed to download ${tag}.`);
      }
    }
  };
  es.onerror = () => {
    es.close();
    if (progressEl) progressEl.textContent = 'Connection lost.';
    if (btn) { btn.disabled = false; btn.textContent = 'Retry download'; }
  };
}

async function openReplayModal() {
  document.getElementById('replayModal').style.display = 'flex';
  await loadReplayRuns();
}

function closeReplayModal() {
  document.getElementById('replayModal').style.display = 'none';
}

let allLoadedReplays = [];

async function loadReplayRuns() {
  const list = document.getElementById('replayRunList');
  const detail = document.getElementById('replayRunDetail');
  if (list) list.innerHTML = '<div class="replay-empty">Loading past runs...</div>';
  if (detail) detail.innerHTML = '<div class="replay-empty">Select a run to inspect its phases.</div>';

  try {
    const resp = await fetch('/runs?limit=50');
    const data = await resp.json();
    allLoadedReplays = data.runs || [];
    renderFilteredReplays(allLoadedReplays);
    if (allLoadedReplays.length > 0) {
      await loadReplayRunDetail(allLoadedReplays[0].run_id);
    }
  } catch (e) {
    if (list) list.innerHTML = '<div class="replay-empty">Failed to load persisted runs.</div>';
  }
}

function filterReplayRuns(query) {
  const q = (query || '').trim().toLowerCase();
  if (!q) {
    renderFilteredReplays(allLoadedReplays);
    return;
  }
  const filtered = allLoadedReplays.filter(r => 
    (r.topic || '').toLowerCase().includes(q) || 
    (r.run_id || '').toLowerCase().includes(q) ||
    (r.status || '').toLowerCase().includes(q)
  );
  renderFilteredReplays(filtered);
}

function renderFilteredReplays(runs) {
  const list = document.getElementById('replayRunList');
  if (!list) return;
  if (!runs.length) {
    list.innerHTML = '<div class="replay-empty">No matching runs found.</div>';
    return;
  }
  list.innerHTML = runs.map(run => {
    const started = run.started_at ? new Date(run.started_at * 1000).toLocaleString() : 'unknown';
    const topic = escapeHtml((run.topic || '').slice(0, 72) || 'Untitled run');
    return `
      <div class="replay-run-item" onclick="loadReplayRunDetail('${escapeHtml(run.run_id)}')">
        <div style="display:flex; justify-content:space-between; align-items:flex-start; gap:8px;">
          <div class="replay-run-title">${topic}</div>
          <button class="btn btn-small btn-danger replay-delete-btn" onclick="event.stopPropagation(); deleteSingleReplay('${escapeHtml(run.run_id)}')" title="Delete this run">🗑️</button>
        </div>
        <div class="replay-run-meta">run_id: ${escapeHtml(run.run_id)}<br>status: ${escapeHtml(run.status)}<br>started: ${escapeHtml(started)}</div>
      </div>
    `;
  }).join('');
}

async function deleteSingleReplay(runId) {
  if (!runId) return;
  if (!confirm(`Delete run ${runId}? This will remove all associated phase outputs and skills.`)) return;
  try {
    const resp = await fetch(`/runs/${encodeURIComponent(runId)}`, { method: 'DELETE' });
    if (resp.ok) {
      showToast('Replay deleted.');
      await loadReplayRuns();
    } else {
      showToast('Failed to delete replay.');
    }
  } catch (e) {
    showToast('Network error deleting replay.');
  }
}

async function deleteAllReplays() {
  if (!confirm('Are you sure you want to delete ALL replay history? This cannot be undone.')) return;
  try {
    const resp = await fetch('/runs', { method: 'DELETE' });
    if (resp.ok) {
      showToast('All replay history cleared.');
      await loadReplayRuns();
      document.getElementById('replayRunDetail').innerHTML = '<div class="replay-empty">No persisted runs.</div>';
    } else {
      showToast('Failed to clear replay history.');
    }
  } catch (e) {
    showToast('Network error clearing replay history.');
  }
}

function formatReplayPhaseOutput(phase, runId) {
  if (phase.phase === 3 && phase.member_id === 'chairman') {
    try {
      const data = JSON.parse(phase.output || '{}');
      const isUncalibrated = data.risk_score === -1 || data.risk_score === '-1' || data.risk_score === null || data.risk_score === undefined;
      const riskDisplay = isUncalibrated ? '⚠️ Uncalibrated' : `${escapeHtml(String(data.risk_score))}/10`;
      return `
        <h3>Verdict: ${escapeHtml(data.verdict || 'unknown')}</h3>
        <p><strong>Risk score:</strong> ${riskDisplay}</p>
        <p><strong>Action items:</strong></p>
        <ul>${(data.action_items || []).map((item, index) => `
          <li>${escapeHtml(item)}
            <button class="btn btn-small replay-feedback" data-run-id="${escapeHtml(runId)}" data-action-index="${index}" data-rating="thumbs_up" title="Mark this action useful">Useful</button>
            <button class="btn btn-small replay-feedback" data-run-id="${escapeHtml(runId)}" data-action-index="${index}" data-rating="thumbs_down" title="Mark this action unhelpful">Not useful</button>
          </li>`).join('')}</ul>
      `;
    } catch (e) {
      return renderMarkdown(phase.output || '');
    }
  }
  return renderMarkdown(phase.output || '');
}

async function loadReplayRunDetail(runId) {
  const detail = document.getElementById('replayRunDetail');
  detail.innerHTML = '<div class="replay-empty">Loading run detail...</div>';

  try {
    const resp = await fetch(`/runs/${encodeURIComponent(runId)}`);
    const run = await resp.json();
    if (!run || !run.run_id) {
      detail.innerHTML = '<div class="replay-empty">Run not found.</div>';
      return;
    }

    const roster = run.roster || {};
    const phases = run.phases || [];
    const started = run.started_at ? new Date(run.started_at * 1000).toLocaleString() : 'unknown';

    detail.innerHTML = `
      <div class="preset-title">${escapeHtml(run.topic || 'Untitled run')}</div>
      <div class="replay-run-meta replay-detail-meta">run_id: ${escapeHtml(run.run_id)} • status: ${escapeHtml(run.status)} • started: ${escapeHtml(started)}</div>
      <div class="inline-actions replay-actions">
        <button class="btn btn-small" id="replayExportButton">Download report</button>
        <button class="btn btn-small btn-danger" onclick="deleteSingleReplay('${escapeHtml(run.run_id)}')">Delete replay</button>
      </div>
      ${phases.map(phase => {
        const seat = roster[phase.member_id] || {};
        const label = seat.label || phase.member_id;
        const color = seat.color || 'var(--accent)';
        const icon = seat.icon || '•';
        return `
          <div class="replay-phase">
            <div class="replay-phase-head">
              <div class="replay-member" style="color:${escapeHtml(color)}">${escapeHtml(icon)} ${escapeHtml(label)}</div>
              <div class="replay-phase-meta">phase ${escapeHtml(String(phase.phase))} • ${escapeHtml(phase.member_id)}</div>
            </div>
            <div class="card-body replay-output">${formatReplayPhaseOutput(phase, run.run_id)}</div>
          </div>
        `;
      }).join('') || '<div class="replay-empty">No phase outputs stored for this run.</div>'}
    `;
    detail.querySelector('#replayExportButton')?.addEventListener('click', () => downloadRunExport(run.run_id));
    detail.querySelectorAll('.replay-feedback').forEach(button => {
      button.addEventListener('click', () => recordActionFeedback(
        button.dataset.runId,
        Number(button.dataset.actionIndex),
        button.dataset.rating,
        button,
      ));
    });
  } catch (e) {
    detail.innerHTML = '<div class="replay-empty">Failed to load run detail.</div>';
  }
}

function downloadRunExport(runId) {
  window.location.assign(`/runs/${encodeURIComponent(runId)}/export?format=md`);
}

async function recordActionFeedback(runId, actionIndex, rating, button) {
  if (!runId || !Number.isInteger(actionIndex)) return;
  button.disabled = true;
  try {
    const resp = await fetch(`/runs/${encodeURIComponent(runId)}/feedback`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action_index: actionIndex, rating }),
    });
    if (!resp.ok) throw new Error('Feedback request failed');
    button.textContent = rating === 'thumbs_up' ? '✓ Useful' : '✓ Noted';
    showToast('Feedback saved; it will inform run-quality metrics.');
  } catch (e) {
    button.disabled = false;
    showToast('Could not save feedback.');
  }
}

// ── DRAG AND DROP & KEYBOARD SHORTCUTS ──
async function extractDroppedFiles(dataTransfer) {
  const files = [];
  const items = dataTransfer?.items;
  if (items && items.length > 0 && items[0].webkitGetAsEntry) {
    const queue = [];
    for (let i = 0; i < items.length; i++) {
      const entry = items[i].webkitGetAsEntry();
      if (entry) queue.push(entry);
    }
    
    async function readEntry(entry, currentPath = '') {
      if (entry.isFile) {
        return new Promise((resolve) => {
          entry.file((file) => {
            const relPath = currentPath ? `${currentPath}/${file.name}` : file.name;
            const renamed = new File([file], relPath, { type: file.type || 'text/plain' });
            files.push(renamed);
            resolve();
          }, () => resolve());
        });
      } else if (entry.isDirectory) {
        const dirName = entry.name;
        if (['.git', 'node_modules', '__pycache__', 'venv', '.venv', 'dist', 'build', '.next', '.nuxt'].includes(dirName)) {
          return;
        }
        const dirReader = entry.createReader();
        return new Promise((resolve) => {
          dirReader.readEntries(async (entries) => {
            for (const subEntry of entries) {
              await readEntry(subEntry, currentPath ? `${currentPath}/${dirName}` : dirName);
            }
            resolve();
          }, () => resolve());
        });
      }
    }
    
    for (const entry of queue) {
      await readEntry(entry);
    }
  } else {
    for (const file of Array.from(dataTransfer?.files || [])) {
      files.push(file);
    }
  }
  return files;
}

function initDragAndDrop() {
  const topicInput = document.getElementById('topicText');
  const fileList = document.getElementById('fileList');
  const dropTargets = [topicInput, fileList].filter(Boolean);

  ['dragenter', 'dragover'].forEach(eventName => {
    document.body.addEventListener(eventName, (e) => {
      e.preventDefault();
      e.stopPropagation();
    }, false);
  });

  dropTargets.forEach(target => {
    target.addEventListener('dragover', (e) => {
      e.preventDefault();
      target.classList.add('drag-active');
    });
    target.addEventListener('dragleave', () => {
      target.classList.remove('drag-active');
    });
    target.addEventListener('drop', async (e) => {
      e.preventDefault();
      target.classList.remove('drag-active');
      const files = await extractDroppedFiles(e.dataTransfer);
      if (!files.length) return;
      const existingNames = new Set(selectedFiles.map(f => f.name));
      let added = 0;
      for (const f of files) {
        if (!existingNames.has(f.name)) {
          selectedFiles.push(f);
          existingNames.add(f.name);
          added++;
        }
      }
      renderSelectedFiles();
      refreshPreflight();
      showToast(`Added ${added} attachment(s) via drag-and-drop.`);
    });
  });
}

function initKeyboardShortcuts() {
  document.addEventListener('keydown', (e) => {
    // Escape key closes modals
    if (e.key === 'Escape') {
      const modals = ['memoryModal', 'modelLibraryModal', 'replayModal'];
      for (const modalId of modals) {
        const modal = document.getElementById(modalId);
        if (modal && modal.style.display !== 'none' && modal.style.display !== '') {
          modal.style.display = 'none';
        }
      }
    }

    // Cmd+Enter or Ctrl+Enter launches council when typing in topicText
    if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
      if (document.activeElement === document.getElementById('topicText')) {
        e.preventDefault();
        launchCouncil();
      } else if (document.activeElement === document.getElementById('projectPathInput')) {
        e.preventDefault();
        launchProjectReview();
      }
    }
  });
}

// ── INITIALIZATION ──
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
