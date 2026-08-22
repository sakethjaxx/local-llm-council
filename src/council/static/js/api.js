let projectScanTimer = null;
let modelCatalog = null;
let allLoadedReplays = [];

const CLOUD_MODEL_CHOICES = [
  { model_id: 'openai/gpt-4o-mini', label: 'gpt-4o-mini (OpenAI key)' },
  { model_id: 'openai/gpt-4o', label: 'gpt-4o (OpenAI key)' },
  { model_id: 'anthropic/claude-sonnet-4-20250514', label: 'claude-sonnet-4 (Anthropic key)' },
  { model_id: 'gemini/gemini-2.0-flash', label: 'gemini-2.0-flash (Gemini key)' },
  { model_id: 'groq/llama-3.3-70b-versatile', label: 'llama-3.3-70b (Groq key)' },
];

function projectFileBudget() {
  const raw = parseInt(document.getElementById('projectFileBudget')?.value, 10);
  if (!Number.isFinite(raw)) return 25;
  return Math.max(1, Math.min(raw, 120));
}

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

    if (typeof renderSelectedFiles === 'function') renderSelectedFiles();
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

function renderPresets() {
  const select = document.getElementById('presetSelect');
  if (!demoCatalog || !select) return;
  select.innerHTML = '<option value="">Select a demo preset...</option>' +
    demoCatalog.presets.map(preset => `<option value="${preset.id}">${escapeHtml(preset.label)}</option>`).join('');
}

function renderSampleActions() {
  const box = document.getElementById('sampleActions');
  if (!demoCatalog || !box) return;
  box.innerHTML = (demoCatalog.samples || []).map(sample => `
    <button class="btn btn-small" onclick="attachSample('${sample.id}')">${escapeHtml(sample.label)}</button>
  `).join('');
}

async function attachSample(sampleId) {
  if (!demoCatalog) return;
  const sample = (demoCatalog.samples || []).find(item => item.id === sampleId);
  if (!sample) return;

  const resp = await fetch(`/demo-samples/${sample.filename}`);
  const blob = await resp.blob();
  const file = new File([blob], sample.filename, { type: sample.content_type || blob.type || 'text/plain' });
  selectedFiles = [...selectedFiles, file];
  if (typeof renderSelectedFiles === 'function') renderSelectedFiles();
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
  if (typeof renderSelectedFiles === 'function') renderSelectedFiles();
  refreshPreflight();
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

function syncToggles(preset) {
  const toggles = preset.toggles || {};
  const deepDebate = document.getElementById('deepDebateToggle');
  const dynamicSwarm = document.getElementById('dynamicSwarmToggle');
  if (deepDebate) deepDebate.checked = Boolean(toggles.deep_debate ?? preset.deep_debate);
  if (dynamicSwarm) dynamicSwarm.checked = Boolean(toggles.dynamic_swarm ?? preset.dynamic_swarm);
}

async function onPresetSelected(presetId) {
  if (!presetId || !demoCatalog) return;
  const preset = demoCatalog.presets.find(item => item.id === presetId);
  if (!preset) return;

  const desc = document.getElementById('presetDesc');
  const topic = document.getElementById('topicText');
  if (desc) desc.textContent = preset.description || '';
  councilConfig = fitModelsToHardware(configFromPreset(preset));
  if (topic) topic.value = preset.topic || preset.topic_placeholder || '';
  syncToggles(preset);
  if (typeof renderSeats === 'function') renderSeats();
  
  await loadPresetSamples(presetId);
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
  const chairmanNote = chairmanRequired ? ` Chairman phase: ${chair.split('/').pop()} needs ~${chairmanRequired.toFixed(1)}GB.` : '';

  if (required <= budget) {
    summary.textContent = `Fits: ${analystNames} need ~${required.toFixed(1)}GB concurrently (budget ~${budget.toFixed(1)}GB).${chairmanNote}`;
  } else {
    summary.textContent = `Does not fit concurrently: ${analystNames} need ~${required.toFixed(1)}GB, above the ~${budget.toFixed(1)}GB budget. Choose smaller analysts or use a shared/mixed roster.${chairmanNote}`;
  }
}

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

function rosterStrategy() {
  return document.getElementById('rosterStrategy')?.value || 'auto';
}

function updateRosterStrategySummary(data) {
  const summary = document.getElementById('rosterStrategySummary');
  if (!summary) return;
  summary.textContent = data?.reason || 'Auto keeps the most suitable models resident when possible.';
}

async function loadHardwareDefaults() {
  try {
    const resp = await fetch('/hardware/suggest?strategy=auto');
    const data = await resp.json();
    if (data && data.config) {
      hardwareConfig = data.config;
      councilConfig = data.config;
      if (typeof renderSeats === 'function') renderSeats();
      refreshPreflight();
      const badge = document.getElementById('hardwareReason');
      if (badge && data.reason) {
        badge.textContent = `Roster fitted to ${data.ram_gb}GB — ${data.reason}`;
      }
      updateRosterStrategySummary(data);
    }
  } catch (e) {}
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
    if (typeof renderSeats === 'function') renderSeats();
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
