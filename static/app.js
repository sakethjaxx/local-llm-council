// ── STATE ──
let councilConfig = {
  "architect": { label: "Lead Architect", model: "ollama/qwen2.5:7b", color: "#4D6BFE", icon: "🐋", persona: "You are the Lead Architect. Focus on SOLID principles, design patterns, maintainability, and code structure. Favor pragmatic, local-first solutions and call out unnecessary complexity." },
  "security": { label: "Security Auditor", model: "ollama/gemma2:9b", color: "#FF4444", icon: "🛡️", persona: "You are the Senior Security Auditor. Focus strictly on OWASP vulnerabilities, injection flaws, unsafe defaults, and exposure risk. Prefer defenses that work in local self-hosted deployments." },
  "perf": { label: "Performance Eng", model: "ollama/llama3.1:8b", color: "#00FF00", icon: "⚡", persona: "You are the Performance Engineer. Focus on algorithmic cost, memory pressure, context bloat, and latency. Optimize for hardware-constrained local inference." },
  "chairman": { label: "Chairman", model: "ollama/qwen2.5:7b", color: "#F5C842", icon: "👑", persona: "You are the Chairman. Synthesize the council and make a final verdict. Prefer recommendations that preserve free, open-weight, local execution." }
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
  performance: 'Performance profile: longer answers with higher latency and memory cost.'
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
      <div>Ready for a project brief.</div>
      <div class="helper-copy">Choose a preset, attach context, or enter a local project path to start.</div>
      <div class="helper-copy" id="hardwareReason" style="margin-top:6px;opacity:0.8;"></div>
    </div>
  `;

  const btn = document.getElementById('launchBtn');
  btn.disabled = false;
  btn.innerHTML = 'Run council';

  showToast('Session reset cleanly.');
}

// ── THEME TOGGLE ──
function toggleTheme() {
  const currentTheme = document.body.getAttribute('data-theme');
  const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
  
  if (newTheme === 'dark') {
    document.body.setAttribute('data-theme', 'dark');
  } else {
    document.body.removeAttribute('data-theme');
  }
  localStorage.setItem(THEME_STORAGE_KEY, newTheme);
  
  const themeBtn = document.getElementById('themeBtn');
  if (themeBtn) themeBtn.textContent = newTheme === 'dark' ? '☀️ Theme' : '🌙 Theme';
}

function initTheme() {
  const saved = localStorage.getItem(THEME_STORAGE_KEY);
  const prefersDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
  if (saved === 'dark' || (!saved && prefersDark)) {
    document.body.setAttribute('data-theme', 'dark');
    const themeBtn = document.getElementById('themeBtn');
    if (themeBtn) themeBtn.textContent = '☀️ Theme';
  }
}

// ── LOCAL PROJECT HELPER FUNCTIONS ──
function useCurrentProject() {
  const input = document.getElementById('projectPathInput');
  if (input) input.value = '/Users/sakethjaggaiahgari/Desktop/Projects/Fable_graph';
  showToast('Set project path to Fable_graph.');
}

async function bulkIngestFolder() {
  const path = document.getElementById('projectPathInput')?.value.trim();
  if (!path) return alert('Enter a local folder path to ingest.');
  
  const infoDiv = document.getElementById('projectScanInfo');
  if (infoDiv) infoDiv.textContent = 'Bulk ingesting folder files...';
  
  try {
    const resp = await fetch('/ingest/folder', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ folder_path: path, max_files: 50 })
    });
    
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      alert(`Ingest failed: ${err.detail || 'Unknown error'}`);
      if (infoDiv) infoDiv.textContent = '';
      return;
    }
    
    const data = await resp.json();
    if (infoDiv) infoDiv.textContent = `Ingested ${data.file_count} project files into prompt context.`;
    
    // Auto populate topic text if empty
    const topic = document.getElementById('topicText');
    if (topic && !topic.value.trim() && data.formatted_prompt_text) {
      topic.value = `[Review Request for ${path.split('/').pop()}]\n\n${data.formatted_prompt_text}`;
    }
    
    showToast(`Bulk ingested ${data.file_count} files successfully!`);
  } catch (e) {
    alert(`Folder ingest error: ${e.message}`);
    if (infoDiv) infoDiv.textContent = '';
  }
}

// ── RESIZABLE SIDEBAR SPLITTER ──
function initResizer() {
  const resizer = document.getElementById('dragResizer');
  if (!resizer) return;

  let isDragging = false;

  resizer.addEventListener('mousedown', (e) => {
    isDragging = true;
    resizer.classList.add('dragging');
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
  });

  document.addEventListener('mousemove', (e) => {
    if (!isDragging) return;
    const newWidth = Math.min(Math.max(e.clientX, 280), 650);
    document.documentElement.style.setProperty('--sidebar-width', `${newWidth}px`);
  });

  document.addEventListener('mouseup', () => {
    if (isDragging) {
      isDragging = false;
      resizer.classList.remove('dragging');
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
    }
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
      <div>${escapeHtml(message || 'Starting council run...')}</div>
      <div class="skeleton-line"></div>
      <div class="skeleton-line short"></div>
    </div>
  `;
}

function renderErrorState(panel, message) {
  panel.innerHTML = `<div class="status-card"><div class="preset-title status-bad">Run failed</div><div class="status-line status-bad">${escapeHtml(message || 'Unknown error')}</div></div>`;
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
  tokenBudgetProfile = ['economy', 'balanced', 'performance'].includes(profile) ? profile : 'balanced';
  const summary = document.getElementById('tokenBudgetSummary');
  if (summary) {
    summary.textContent = TOKEN_BUDGET_SUMMARIES[tokenBudgetProfile];
  }
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

// ── SEAT BUILDER UI (STRICT NON-OVERLAPPING DELETE BUTTON) ──
function renderSeats() {
  const list = document.getElementById('seatList');
  if (!list) return;
  list.innerHTML = '';
  for (const [id, seat] of Object.entries(councilConfig)) {
    const isChairman = id === 'chairman';
    const div = document.createElement('div');
    div.className = 'seat-item';
    div.innerHTML = `
      <div class="seat-header">
        <div class="seat-dot" style="background: ${seat.color}; color: ${seat.color}"></div>
        <div class="seat-title">${seat.icon} ${seat.label}</div>
        <div class="seat-model" title="${escapeHtml(seat.model)}">${escapeHtml(seat.model.split('/').pop())}</div>
        ${!isChairman ? `<div class="seat-remove" onclick="removeSeat('${id}')" title="Remove seat">✕</div>` : ''}
      </div>
      <div class="seat-edit-fields">
        <input type="text" value="${escapeHtml(seat.model)}" onchange="updateSeat('${id}', 'model', this.value)" placeholder="Model, e.g. ollama/qwen2.5:3b">
        <input type="text" value="${escapeHtml(seat.persona)}" onchange="updateSeat('${id}', 'persona', this.value)" placeholder="System Persona Prompt">
      </div>
    `;
    list.appendChild(div);
  }
}

function addSeat() {
  const id = 'seat_' + Math.floor(Math.random() * 1000);
  councilConfig[id] = {
    label: "New Expert",
    model: "ollama/qwen2.5:7b",
    color: "#" + Math.floor(Math.random()*16777215).toString(16),
    icon: "🤖",
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

function applyModelProfile(profile) {
  const profileConfig = MODEL_PROFILES[profile];
  if (!profileConfig) return;

  for (const [id, seat] of Object.entries(councilConfig)) {
    if (profileConfig[id]) {
      seat.model = profileConfig[id];
    } else if (id !== 'chairman') {
      seat.model = profileConfig.architect;
    }
  }

  renderSeats();
  refreshPreflight();
}

function removeFile(index) {
  selectedFiles.splice(index, 1);
  renderSelectedFiles();
  refreshPreflight();
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
    return `<div style="display:flex;align-items:center;gap:6px;">
      <span>${escapeHtml(file.name)} <span style="color:var(--warm)">(${sizeKb} KB)</span></span>
      <button onclick="removeFile(${i})" style="background:none;border:none;color:var(--danger);cursor:pointer;font-size:13px;padding:0 2px;" title="Remove">✕</button>
    </div>`;
  }).join('');
}

async function autoConfigureHardware() {
  try {
    const resp = await fetch('/hardware/suggest');
    const data = await resp.json();
    alert(`Hardware Scan Complete.\n\nDetected RAM: ${data.ram_gb} GB\nHardware Tier: ${data.tier_name}\n\nUpdating Council Config to use optimized local Ollama models...`);
    councilConfig = data.config;
    renderSeats();
    refreshPreflight();
  } catch (e) {
    alert("Failed to auto-configure hardware. Is the backend running?");
  }
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
    const resp = await fetch('/hardware/suggest');
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
    }
  } catch (e) {}
}

// ── COUNCIL EXECUTION ──
async function launchCouncil() {
  const topic = document.getElementById('topicText').value.trim();
  if (!topic && !selectedFiles.length) return alert('Enter a topic or attach at least one file.');
  await refreshPreflight();
  if (!preflightState || !preflightState.ready) {
    return alert('Demo preflight failed. Install the missing models or switch to a preset that matches your local setup.');
  }

  const btn = document.getElementById('launchBtn');
  const panel = document.getElementById('councilPanel');
  btn.disabled = true;
  btn.innerHTML = '> PROCESSING...';

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

  try {
    const resp = await fetch('/council/stream', {
      method: 'POST',
      headers: cloudKeyHeaders(),
      body: formData
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
    showToast(err.message || 'SSE connection failed.');
    renderErrorState(panel, err.message);
  }
  
  btn.disabled = false;
  btn.innerHTML = 'Run council';
}

async function launchProjectReview() {
  const path = document.getElementById('projectPathInput').value.trim();
  if (!path) return alert('Enter a project directory path (e.g. /Users/sakethjaggaiahgari/Desktop/Projects/Fable_graph).');

  const btn = document.getElementById('projectReviewBtn');
  const launchBtn = document.getElementById('launchBtn');
  const panel = document.getElementById('councilPanel');
  const infoDiv = document.getElementById('projectScanInfo');

  btn.disabled = true;
  btn.textContent = 'Scanning...';
  launchBtn.disabled = true;
  renderLoadingState(panel, `Scanning project at ${path.split('/').pop()} and preparing review...`);
  rawCardContents = {};
  thinkingCards = {};
  chatHistory = [];
  if (infoDiv) infoDiv.textContent = '';

  try {
    const resp = await fetch('/council/review-project', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...cloudKeyHeaders() },
      body: JSON.stringify({
        path,
        deep_debate: document.getElementById('deepDebateToggle')?.checked || false,
        council_config: councilConfig,
        token_budget_profile: tokenBudgetProfile,
      }),
    });

    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      const message = err.detail || err.message || `HTTP ${resp.status}: Path outside allowed root or unreadable`;
      showToast(message);
      renderErrorState(panel, message);
      btn.disabled = false;
      btn.textContent = 'Scan & Review';
      launchBtn.disabled = false;
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
              infoDiv.textContent = `Scanned ${ev.total_files} files → reviewing ${ev.files_selected.length} core files`;
            } else {
              handleEvent(ev, panel);
            }
          } catch {}
        }
      }
    }
  } catch (err) {
    showToast(err.message || 'Project review connection failed.');
    renderErrorState(panel, err.message);
  }

  btn.disabled = false;
  btn.textContent = 'Scan & Review';
  launchBtn.disabled = false;
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
    grid.scrollIntoView({ behavior: 'smooth', block: 'end' });
    return;
  }

  if (ev.type === 'member_thinking') {
    const phase = ev.phase || 1;
    const grid = document.getElementById(`grid-phase${phase}`);
    if (!grid) return;

    const card = buildCard(ev.member, ev.meta, null, phase);
    grid.appendChild(card);
    thinkingCards[`${ev.member}-${phase}`] = card;
    card.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
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
        let riskColor = "var(--accent)";
        if (data.risk_score >= 8) riskColor = "var(--danger)";
        else if (data.risk_score >= 5) riskColor = "var(--warm)";

        const riskScore = escapeHtml(data.risk_score ?? '');
        let html = `
          <h2>VERDICT: ${escapeHtml(data.verdict || '')}</h2>
          <div style="font-size: 20px; color: ${riskColor}; font-weight:bold; margin: 8px 0;">RISK SCORE: ${riskScore}/10</div>
          <h3>Action Items:</h3>
          <ul>${(data.action_items || []).map(a => `<li>${escapeHtml(a)}</li>`).join('')}</ul>
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
}

function buildCard(member, meta, content, phase) {
  const isChairman = member === 'chairman';
  const card = document.createElement('div');
  card.className = isChairman ? 'council-card chairman-card' : 'council-card';

  const color = meta.color || 'var(--accent)';
  card.innerHTML = `
    <div class="card-header">
      <div class="card-icon" style="color:${color}">${meta.icon}</div>
      <div class="card-name" style="color:${color}">${meta.label.toUpperCase()}</div>
    </div>
    <div class="typing"><span></span><span></span><span></span></div>
    <div class="card-body" style="display:none"></div>
  `;
  return card;
}

// ── FABLE GRAPH EXPORT ──
async function exportFableGraph() {
  try {
    const resp = await fetch('/fable-graph/export');
    if (!resp.ok) return showToast('Failed to export Fable Graph.');
    const data = await resp.json();
    const jsonStr = JSON.stringify(data, null, 2);
    const blob = new Blob([jsonStr], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `council_brain_${Date.now()}.fable.json`;
    a.click();
    showToast('Exported .fable.json corpus successfully!');
  } catch (e) {
    showToast('Failed to export Fable Graph JSON.');
  }
}

// ── MEMORY GRAPH & CODE GRAPH VISUALIZATION ──
async function viewMemory() {
  const modal = document.getElementById('memoryModal');
  document.getElementById('modalTitle').textContent = 'Fable Knowledge Graph';
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
        font: { color: 'var(--text)', face: 'IBM Plex Mono', size: 12 },
        color: { background: 'var(--accent-soft)', border: 'var(--accent)' }
      },
      edges: {
        width: 2,
        font: { color: 'var(--muted)', face: 'IBM Plex Mono', size: 10, align: 'horizontal' },
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
        font: { color: 'var(--text)', face: 'IBM Plex Mono', size: 11 },
        color: { background: 'var(--accent-soft)', border: 'var(--accent)' }
      },
      edges: {
        width: 1.5,
        color: { color: 'rgba(47, 93, 80, 0.35)', highlight: '#9c7a4d' },
        font: { color: 'var(--muted)', face: 'IBM Plex Mono', size: 10, align: 'horizontal' },
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

async function openReplayModal() {
  document.getElementById('replayModal').style.display = 'flex';
  await loadReplayRuns();
}

function closeReplayModal() {
  document.getElementById('replayModal').style.display = 'none';
}

async function loadReplayRuns() {
  const list = document.getElementById('replayRunList');
  const detail = document.getElementById('replayRunDetail');
  list.innerHTML = '<div class="replay-empty">Loading past runs...</div>';
  detail.innerHTML = '<div class="replay-empty">Select a run to inspect its phases.</div>';

  try {
    const resp = await fetch('/runs?limit=25');
    const data = await resp.json();
    const runs = data.runs || [];
    if (!runs.length) {
      list.innerHTML = '<div class="replay-empty">No persisted runs yet.</div>';
      return;
    }

    list.innerHTML = runs.map(run => {
      const started = run.started_at ? new Date(run.started_at * 1000).toLocaleString() : 'unknown';
      const topic = escapeHtml((run.topic || '').slice(0, 72) || 'Untitled run');
      return `
        <div class="replay-run-item" onclick="loadReplayRunDetail('${escapeHtml(run.run_id)}')">
          <div class="replay-run-title">${topic}</div>
          <div class="replay-run-meta">run_id: ${escapeHtml(run.run_id)}<br>status: ${escapeHtml(run.status)}<br>started: ${escapeHtml(started)}</div>
        </div>
      `;
    }).join('');

    await loadReplayRunDetail(runs[0].run_id);
  } catch (e) {
    list.innerHTML = '<div class="replay-empty">Failed to load persisted runs.</div>';
  }
}

function formatReplayPhaseOutput(phase) {
  if (phase.phase === 3 && phase.member_id === 'chairman') {
    try {
      const data = JSON.parse(phase.output || '{}');
      return `
        <h3>Verdict: ${escapeHtml(data.verdict || 'unknown')}</h3>
        <p><strong>Risk score:</strong> ${escapeHtml(String(data.risk_score ?? 'n/a'))}</p>
        <p><strong>Action items:</strong></p>
        <ul>${(data.action_items || []).map(item => `<li>${escapeHtml(item)}</li>`).join('')}</ul>
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
      <div class="replay-run-meta" style="margin-top:6px;">run_id: ${escapeHtml(run.run_id)} • status: ${escapeHtml(run.status)} • started: ${escapeHtml(started)}</div>
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
            <div class="card-body" style="display:block; margin-top:8px;">${formatReplayPhaseOutput(phase)}</div>
          </div>
        `;
      }).join('') || '<div class="replay-empty">No phase outputs stored for this run.</div>'}
    `;
  } catch (e) {
    detail.innerHTML = '<div class="replay-empty">Failed to load run detail.</div>';
  }
}

// ── INITIALIZATION ──
initTheme();
initResizer();
renderSeats();
hydrateCloudKeys();
setTokenBudgetProfile('balanced');
fetchDemoCatalog();
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
