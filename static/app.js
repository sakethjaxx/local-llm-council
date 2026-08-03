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
  return String(value)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

marked.setOptions({
  gfm: true,
  breaks: true
});

function sanitizeHtml(html) {
  if (window.DOMPurify) {
    return DOMPurify.sanitize(html, { USE_PROFILES: { html: true } });
  }
  return escapeHtml(html || '');
}

function renderMarkdown(text) {
  return sanitizeHtml(marked.parse(text || ''));
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
  setTimeout(() => toast.remove(), 6500);
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
    console.error('Failed to parse stored cloud keys', e);
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
  document.getElementById('keyOpenAI').value = keys.openai || '';
  document.getElementById('keyAnthropic').value = keys.anthropic || '';
  document.getElementById('keyGemini').value = keys.gemini || '';
  document.getElementById('keyGroq').value = keys.groq || '';
}

function clearCloudKeys() {
  localStorage.removeItem(CLOUD_KEY_STORAGE_KEY);
  hydrateCloudKeys();
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
  const grid = document.getElementById('presetGrid');
  if (!demoCatalog) {
    grid.innerHTML = '<div class="status-line">Loading demo presets...</div>';
    return;
  }

  grid.innerHTML = demoCatalog.presets.map(preset => `
    <div class="preset-card">
      <div class="preset-title">${escapeHtml(preset.label)}</div>
      <div class="preset-desc">${escapeHtml(preset.description)}</div>
      <div class="inline-actions">
        <button class="btn btn-small" onclick="applyDemoPreset('${preset.id}')">Use preset</button>
        <button class="btn btn-small" onclick="loadPresetSamples('${preset.id}')">Load sample files</button>
      </div>
    </div>
  `).join('');
}

function renderSampleActions() {
  const box = document.getElementById('sampleActions');
  if (!demoCatalog) {
    box.innerHTML = '';
    return;
  }
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

async function applyDemoPreset(presetId) {
  if (!demoCatalog) return;
  const preset = demoCatalog.presets.find(item => item.id === presetId);
  if (!preset) return;

  councilConfig = fitModelsToHardware(configFromPreset(preset));
  document.getElementById('topicText').value = preset.topic || preset.topic_placeholder || '';
  syncToggles(preset);
  renderSeats();
  refreshPreflight();
}

async function refreshPreflight() {
  const box = document.getElementById('preflightBox');
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
      : `<div class="status-line status-good">All required local models are installed.</div>`;
    const imageHtml = selectedFiles.some(file => file.type.startsWith('image/'))
      ? `<div class="status-line ${preflightState.image_seats.length ? 'status-good' : 'status-warn'}">Image seats: ${escapeHtml((preflightState.image_seats || []).join(', ') || 'none')}</div>`
      : '';

    box.innerHTML = `
      <div class="preset-title ${statusClass}">${preflightState.ready ? 'Demo roster ready' : 'Demo roster blocked'}</div>
      <div class="status-line">Installed local models: ${escapeHtml((preflightState.installed || []).join(', ') || 'none detected')}</div>
      ${missingHtml}
      ${imageHtml}
      ${warningHtml || '<div class="status-line">No demo warnings for the current setup.</div>'}
    `;
  } catch (e) {
    console.error('Failed to refresh preflight', e);
    box.innerHTML = '<div class="status-line status-bad">Preflight failed. Check that the backend is running.</div>';
  }
}

// ── SEAT BUILDER UI ──
function renderSeats() {
  const list = document.getElementById('seatList');
  list.innerHTML = '';
  for (const [id, seat] of Object.entries(councilConfig)) {
    const isChairman = id === 'chairman';
    const div = document.createElement('div');
    div.className = 'seat-item';
    div.innerHTML = `
      <div class="seat-header">
        <div class="seat-dot" style="background: ${seat.color}; color: ${seat.color}"></div>
        <div class="seat-title">${seat.icon} ${seat.label}</div>
        <div class="seat-model">${seat.model.split('/').pop()}</div>
        ${!isChairman ? `<div class="seat-remove" onclick="removeSeat('${id}')">✕</div>` : ''}
      </div>
      <div class="seat-edit-fields">
        <input type="text" value="${seat.model}" onchange="updateSeat('${id}', 'model', this.value)" placeholder="Model, e.g. ollama/qwen2.5:3b">
        <input type="text" value="${seat.persona}" onchange="updateSeat('${id}', 'persona', this.value)" placeholder="System Persona Prompt">
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
  if (!selectedFiles.length) {
    fileList.innerHTML = '';
    return;
  }
  fileList.innerHTML = selectedFiles.map((file, i) => {
    const sizeKb = Math.max(1, Math.round(file.size / 1024));
    return `<div style="display:flex;align-items:center;gap:8px;">
      <span>${file.name} <span style="color:var(--warm)">(${sizeKb} KB)</span></span>
      <button onclick="removeFile(${i})" style="background:none;border:none;color:var(--warm);cursor:pointer;font-size:14px;padding:0 2px;line-height:1;" title="Remove">×</button>
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
    console.error(e);
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
  } catch (e) {
    console.error('Failed to load hardware defaults', e);
  }
}

renderSeats();
hydrateCloudKeys();
setTokenBudgetProfile('balanced');
fetchDemoCatalog();
loadHardwareDefaults();
document.getElementById('attachmentInput').addEventListener('change', (event) => {
  const incoming = Array.from(event.target.files || []);
  const existingNames = new Set(selectedFiles.map(f => f.name));
  for (const f of incoming) {
    if (!existingNames.has(f.name)) selectedFiles.push(f);
  }
  event.target.value = '';
  renderSelectedFiles();
  refreshPreflight();
});

// ── COUNCIL EXECUTION ──
async function launchCouncil() {
  const topic = document.getElementById('topicText').value.trim();
  if (!topic && !selectedFiles.length) return alert('Enter a topic or attach at least one file.');
  await refreshPreflight();
  if (!preflightState || !preflightState.ready) {
    return alert('Demo preflight failed. Install the missing models or switch to a preset that matches your local setup.');
  }
  if ((preflightState.warnings || []).some(item => item.includes('no seat is using a known image-capable local model'))) {
    return alert('You selected image attachments without an image-capable seat. Switch to the Image Review preset or change one model before launching.');
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
  
  const swarmToggle = document.getElementById('dynamicSwarmToggle');
  if (swarmToggle && swarmToggle.checked) {
      formData.append('dynamic_swarm', true);
  }
  
  const debateToggle = document.getElementById('deepDebateToggle');
  if (debateToggle && debateToggle.checked) {
      formData.append('deep_debate', true);
  }

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
    let sawDone = false;

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
            if (ev.type === 'done') sawDone = true;
            handleEvent(ev, panel);
          } catch {}
        }
      }
    }
    if (!sawDone) {
      showToast('The stream ended before the council reported completion.');
    }
  } catch (err) {
    showToast(err.message || 'SSE connection failed.');
    renderErrorState(panel, err.message);
  }
  
  btn.disabled = false;
  btn.innerHTML = 'INITIALIZE COUNCIL';
}

function toggleProjectReview() {
  const section = document.getElementById('projectReviewSection');
  section.style.display = section.style.display === 'none' ? 'block' : 'none';
}

async function launchProjectReview() {
  const path = document.getElementById('projectPathInput').value.trim();
  if (!path) return alert('Enter a project directory path.');

  const btn = document.getElementById('projectReviewBtn');
  const launchBtn = document.getElementById('launchBtn');
  const panel = document.getElementById('councilPanel');
  const infoDiv = document.getElementById('projectScanInfo');

  btn.disabled = true;
  btn.textContent = 'Scanning...';
  launchBtn.disabled = true;
  renderLoadingState(panel, 'Scanning project and preparing review...');
  rawCardContents = {};
  thinkingCards = {};
  chatHistory = [];
  infoDiv.textContent = '';

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
      const err = await resp.json();
      const message = err.detail || 'Unknown error';
      showToast(message);
      renderErrorState(panel, message);
      return;
    }

    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let sawDone = false;

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
            if (ev.type === 'done') sawDone = true;
            if (ev.type === 'project_info') {
              infoDiv.textContent = `Scanning ${ev.total_files} files → reviewing ${ev.files_selected.length} core files`;
            } else {
              handleEvent(ev, panel);
            }
          } catch {}
        }
      }
    }
    if (!sawDone) {
      showToast('The project review stream ended before completion.');
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

  if (ev.type === 'warning') {
    const warning = document.createElement('div');
    warning.className = 'status-card';
    warning.innerHTML = `<div class="preset-title status-warn">Runtime fallback</div><div class="status-line status-warn">${escapeHtml(ev.message || 'A warning occurred.')}</div>`;
    panel.appendChild(warning);
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
        let riskColor = "var(--cyan)";
        if (data.risk_score >= 8) riskColor = "var(--danger)";
        else if (data.risk_score >= 5) riskColor = "var(--pink)";

        const riskScore = escapeHtml(data.risk_score ?? '');
        let html = `
          <h2>VERDICT: ${escapeHtml(data.verdict || '')}</h2>
          <div style="font-size: 24px; color: ${riskColor}; font-family: 'Orbitron'; margin: 10px 0;">RISK SCORE: ${riskScore}/10</div>
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

  if (ev.type === 'done') {
    showDebatePanel(panel);
    return;
  }
}

function buildCard(member, meta, content, phase) {
  const isChairman = member === 'chairman';
  const card = document.createElement('div');
  card.className = isChairman ? 'council-card chairman-card' : 'council-card';

  const color = meta.color || '#888';
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

// ── DEBATE MODE & EXPORT ──
function showDebatePanel(panel) {
  const wrapper = document.createElement('div');
  wrapper.innerHTML = `
    <div class="debate-panel" style="display:block">
      <div class="debate-header">
        <span>> INTERACTIVE DEBATE MODE</span>
        <button class="btn btn-small btn-solid" onclick="exportReport()">EXPORT REPORT</button>
      </div>
      <div class="chat-history" id="chatHistory"></div>
      <div class="chat-input-row">
        <select id="chatTarget" class="chat-select">
          ${Object.entries(councilConfig).map(([id, cfg]) => `<option value="${id}">@${cfg.label}</option>`).join('')}
        </select>
        <input type="text" id="chatInput" placeholder="Ask a question..." onkeypress="if(event.key === 'Enter') sendChat()">
        <button class="btn btn-solid" onclick="sendChat()" id="chatBtn">SEND</button>
      </div>
    </div>
  `;
  panel.appendChild(wrapper);
  wrapper.scrollIntoView({ behavior: 'smooth', block: 'end' });
}

async function sendChat() {
  const input = document.getElementById('chatInput');
  const targetId = document.getElementById('chatTarget').value;
  const msg = input.value.trim();
  if (!msg) return;

  const historyDiv = document.getElementById('chatHistory');
  
  chatHistory.push({ role: 'user', content: msg });
  const uMsg = document.createElement('div');
  uMsg.className = 'chat-msg chat-user';
  uMsg.textContent = msg;
  historyDiv.appendChild(uMsg);
  input.value = '';

  const aMsg = document.createElement('div');
  aMsg.className = 'chat-msg chat-agent';
  aMsg.innerHTML = '<div class="typing"><span></span><span></span><span></span></div>';
  historyDiv.appendChild(aMsg);
  historyDiv.scrollTop = historyDiv.scrollHeight;

  document.getElementById('chatBtn').disabled = true;

  try {
    const resp = await fetch('/council/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...cloudKeyHeaders() },
      body: JSON.stringify({
        member_id: targetId,
        messages: chatHistory,
        council_config: councilConfig,
        token_budget_profile: tokenBudgetProfile
      })
    });

    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let fullReply = '';
    aMsg.innerHTML = '';

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
            if (ev.type === 'chat_token') {
              fullReply += ev.chunk;
              aMsg.innerHTML = renderMarkdown(fullReply);
              historyDiv.scrollTop = historyDiv.scrollHeight;
            }
          } catch {}
        }
      }
    }
    chatHistory.push({ role: 'assistant', content: fullReply });
  } catch (err) {
    aMsg.innerHTML = `<span style="color:red">Error: ${err.message}</span>`;
  }
  document.getElementById('chatBtn').disabled = false;
}

function exportReport() {
  let md = "# Universal Council Report\n\n";
  md += "## Topic\n" + document.getElementById('topicText').value + "\n\n";
  
  for (const [key, content] of Object.entries(rawCardContents)) {
    const [member, phase] = key.split('-');
    const meta = councilConfig[member];
    const phaseName = phase == 1 ? "Analysis" : (phase == 2 ? "Review" : "Verdict");
    md += `## ${meta.label} - Phase ${phase} (${phaseName})\n\n`;
    md += content + "\n\n---\n\n";
  }

  if (chatHistory.length > 0) {
    md += "## Interactive Debate\n\n";
    chatHistory.forEach(msg => {
      md += `**${msg.role.toUpperCase()}**: ${msg.content}\n\n`;
    });
  }

  const blob = new Blob([md], { type: 'text/markdown' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `council_report_${Date.now()}.md`;
  a.click();
}

async function openReplayModal() {
  const modal = document.getElementById('replayModal');
  modal.style.display = 'flex';
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
    console.error('Failed to load replay runs', e);
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
    const finished = run.finished_at ? new Date(run.finished_at * 1000).toLocaleString() : 'in progress';
    const chairmanPhase = phases.find(phase => phase.phase === 3 && phase.member_id === 'chairman');
    let verdictSummary = '';
    if (chairmanPhase) {
      try {
        const chairmanJson = JSON.parse(chairmanPhase.output || '{}');
        verdictSummary = `<div class="status-card"><div class="preset-title">Chairman verdict</div><div class="status-line">${escapeHtml(chairmanJson.verdict || 'Unavailable')}</div></div>`;
      } catch (e) {
        verdictSummary = '';
      }
    }

    detail.innerHTML = `
      <div class="preset-title">${escapeHtml(run.topic || 'Untitled run')}</div>
      <div class="replay-run-meta" style="margin-top:8px;">run_id: ${escapeHtml(run.run_id)}<br>status: ${escapeHtml(run.status)}<br>started: ${escapeHtml(started)}<br>finished: ${escapeHtml(finished)}</div>
      ${verdictSummary}
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
            <div class="replay-phase-meta">finish_reason: ${escapeHtml(String(phase.finish_reason || 'n/a'))} • attempt: ${escapeHtml(String(phase.attempt_number || 1))}</div>
            <div class="card-body" style="display:block; margin-top:10px;">${formatReplayPhaseOutput(phase)}</div>
          </div>
        `;
      }).join('') || '<div class="replay-empty">No phase outputs stored for this run.</div>'}
    `;
  } catch (e) {
    console.error('Failed to load replay detail', e);
    detail.innerHTML = '<div class="replay-empty">Failed to load run detail.</div>';
  }
}

// ── MEMORY GRAPH VISUALIZATION ──
async function viewMemory() {
  const modal = document.getElementById('memoryModal');
  document.getElementById('modalTitle').textContent = 'Knowledge graph';
  modal.style.display = 'flex';
  
  try {
    const resp = await fetch('/council/memory');
    const data = await resp.json();
    
    const container = document.getElementById('memoryNetwork');
    const options = {
      nodes: {
        shape: 'dot', size: 16,
        font: { color: '#E8E8EE', face: 'Rajdhani', size: 14 },
        color: { background: '#00f0ff', border: '#ff00ff' },
        shadow: true
      },
      edges: {
        width: 2,
        color: { color: 'rgba(0, 240, 255, 0.4)', highlight: '#ff00ff' },
        font: { color: '#8A8A9E', face: 'Fira Code', size: 11, align: 'horizontal' },
        arrows: { to: { enabled: true, scaleFactor: 0.5 } },
        smooth: { type: 'continuous' }
      },
      physics: { barnesHut: { gravitationalConstant: -3000, centralGravity: 0.3 } }
    };
    
    new vis.Network(container, data, options);
  } catch (e) {
    console.error(e);
    alert("Failed to load memory graph.");
  }
}

function closeMemory() {
  document.getElementById('memoryModal').style.display = 'none';
}

async function viewCodeGraph() {
  const modal = document.getElementById('memoryModal');
  document.getElementById('modalTitle').textContent = 'Project code graph';
  modal.style.display = 'flex';

  try {
    const resp = await fetch('/project/code-graph');
    const data = await resp.json();

    const container = document.getElementById('memoryNetwork');
    const options = {
      nodes: {
        shape: 'dot',
        size: 14,
        font: { color: '#1f2823', face: 'IBM Plex Mono', size: 12 },
        color: { background: '#dbe5df', border: '#2f5d50' }
      },
      edges: {
        width: 1.5,
        color: { color: 'rgba(47, 93, 80, 0.35)', highlight: '#9c7a4d' },
        font: { color: '#6b756f', face: 'IBM Plex Mono', size: 10, align: 'horizontal' },
        arrows: { to: { enabled: true, scaleFactor: 0.45 } },
        smooth: { type: 'continuous' }
      },
      physics: { barnesHut: { gravitationalConstant: -2200, centralGravity: 0.28 } }
    };

    new vis.Network(container, { nodes: data.nodes, edges: data.edges }, options);
  } catch (e) {
    console.error(e);
    alert("Failed to load code graph.");
  }
}
