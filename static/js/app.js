// ── LLM COUNCIL CORE ES MODULE ENTRYPOINT ──

import { 
  state, 
  hydrateCloudKeys, 
  persistCloudKeys, 
  clearCloudKeys, 
  TOKEN_BUDGET_SUMMARIES, 
  MODEL_PROFILES, 
  configFromPreset 
} from './state.js';

import { 
  fetchDemoCatalog, 
  checkPreflight, 
  fetchHardwareSuggestion, 
  fetchSampleFileBlob, 
  streamCouncilRun, 
  streamProjectReview, 
  streamDebateChat 
} from './api.js';

import { 
  escapeHtml, 
  renderMarkdown, 
  showToast, 
  renderLoadingState, 
  renderErrorState, 
  renderPresets, 
  renderSelectedFiles, 
  renderPreflight, 
  renderActiveRosterOverview, 
  renderSeatsList, 
  buildCard, 
  resetMetrics, 
  updateCardStreamMetrics 
} from './ui.js';

import { 
  openModal, 
  closeModal, 
  renderMemoryGraph, 
  renderCodeGraph 
} from './modal.js';

let ph2Section = null;
let ph3Section = null;

// ── INITIALIZATION ──

async function init() {
  // 1. Hydrate stored API Keys
  hydrateCloudKeys();

  // 2. Set default Token Budget label
  const budgetSummary = document.getElementById('tokenBudgetSummary');
  if (budgetSummary) {
    budgetSummary.textContent = TOKEN_BUDGET_SUMMARIES.balanced;
  }

  // 3. Render seat builder and active roster summary
  renderSeatsList(state.councilConfig, removeSeat, updateSeat);
  renderActiveRosterOverview(state.councilConfig);

  // 4. Register manual file attachment input listener
  const attachmentInput = document.getElementById('attachmentInput');
  if (attachmentInput) {
    attachmentInput.addEventListener('change', (e) => {
      const files = Array.from(e.target.files || []);
      const existing = new Set(state.selectedFiles.map(f => f.name));
      for (const f of files) {
        if (!existing.has(f.name)) {
          state.selectedFiles.push(f);
        }
      }
      e.target.value = '';
      renderSelectedFiles(state.selectedFiles, removeFile);
      triggerPreflight();
    });
  }

  // 5. Fetch catalog presets and load hardware suggestions
  try {
    state.demoCatalog = await fetchDemoCatalog();
    renderPresets(state.demoCatalog.presets, applyPreset);
  } catch (e) {
    console.error('Failed to load demo catalog', e);
  }

  try {
    const hw = await fetchHardwareSuggestion();
    if (hw && hw.config) {
      state.councilConfig = hw.config;
      renderSeatsList(state.councilConfig, removeSeat, updateSeat);
      renderActiveRosterOverview(state.councilConfig);
    }
  } catch (e) {
    console.error('Failed to auto-suggest hardware config on load', e);
  }

  // 6. Fetch past runs and render in empty state
  try {
    const resp = await fetch('/runs?limit=4');
    const data = await resp.json();
    const runs = data.runs || [];
    const container = document.getElementById('recentRunsContainer');
    const list = document.getElementById('recentRunsList');
    if (container && list && runs.length > 0) {
      container.style.display = 'block';
      list.innerHTML = runs.map(run => {
        const started = run.started_at ? new Date(run.started_at * 1000).toLocaleString() : 'unknown';
        const topic = escapeHtml((run.topic || '').slice(0, 72) || 'Project Review Workspace');
        return `
          <div class="replay-run-item" data-action-run-id="${run.run_id}" style="padding:10px 12px; background:var(--surface-strong); border:1px solid var(--border); border-radius:10px; cursor:pointer;">
            <div style="font-weight:600; font-size:13px; color:var(--text);">${topic}</div>
            <div style="font-size:10.5px; color:var(--muted); font-family:'IBM Plex Mono', monospace; margin-top:2px;">
              run_id: ${run.run_id.slice(0,8)}... • status: ${run.status} • started: ${started}
            </div>
          </div>
        `;
      }).join('');

      // Add click events
      list.querySelectorAll('.replay-run-item').forEach(el => {
        el.addEventListener('click', () => {
          const runId = el.getAttribute('data-action-run-id');
          openReplayInspector(runId);
        });
      });
    }
  } catch (e) {
    console.error('Failed to load recent runs in empty state', e);
  }

  triggerPreflight();
}

// ── EVENT LISTENERS (DELEGATED CSP-COMPLIANT DATA-ACTIONS) ──

document.addEventListener('click', (e) => {
  const target = e.target.closest('[data-action]');
  if (!target) return;

  const action = target.getAttribute('data-action');

  switch (action) {
    case 'switch-tab': {
      const tabType = target.getAttribute('data-tab');
      switchContextTab(tabType);
      break;
    }
    case 'apply-profile': {
      const profile = target.getAttribute('data-profile');
      applyModelProfile(profile, target);
      break;
    }
    case 'apply-budget': {
      const budget = target.getAttribute('data-budget');
      applyTokenBudget(budget, target);
      break;
    }
    case 'toggle-advanced': {
      toggleAdvancedSection();
      break;
    }
    case 'auto-tune': {
      autoConfigureHardware();
      break;
    }
    case 'refresh-preflight': {
      triggerPreflight();
      break;
    }
    case 'add-seat': {
      addSeat();
      break;
    }
    case 'save-keys': {
      persistCloudKeys();
      break;
    }
    case 'clear-keys': {
      clearCloudKeys();
      showToast('Cloud API keys wiped successfully.');
      break;
    }
    case 'launch-council': {
      executeRun();
      break;
    }
    case 'open-replay': {
      openReplayInspector();
      break;
    }
    case 'view-code-graph': {
      openModal('🕸️ Project Dependency Graph', `
        <div style="flex:1; display:flex; flex-direction:column; overflow:hidden; min-height:300px;">
          <div id="memoryNetwork" style="flex:1; background:#f7f4ee;"></div>
        </div>
      `, (body) => {
        const net = body.querySelector('#memoryNetwork');
        renderCodeGraph(net);
      });
      break;
    }
    case 'view-memory-graph': {
      openModal('🧠 Knowledge Base Memory Graph', `
        <div style="flex:1; display:flex; flex-direction:column; overflow:hidden; min-height:300px;">
          <div id="memoryNetwork" style="flex:1; background:#f7f4ee;"></div>
        </div>
      `, (body) => {
        const net = body.querySelector('#memoryNetwork');
        renderMemoryGraph(net);
      });
      break;
    }
    case 'close-modal': {
      closeModal();
      break;
    }
    case 'chat-send': {
      sendInteractiveChat();
      break;
    }
    case 'export-report': {
      exportReport();
      break;
    }
  }
});

// Setup keypress listeners for chat
document.addEventListener('keypress', (e) => {
  if (e.key === 'Enter' && e.target.id === 'chatInput') {
    sendInteractiveChat();
  }
});

// Setup password input keysave auto triggers
document.addEventListener('change', (e) => {
  if (e.target.matches('input[type="password"][id^="key"]')) {
    persistCloudKeys();
    showToast('Saved API Key to local session.');
  }
});

// ── HANDLERS ──

function switchContextTab(tabType) {
  state.activeTab = tabType;
  
  // Update buttons state
  document.querySelectorAll('[data-tab]').forEach(btn => {
    btn.classList.remove('active');
    btn.setAttribute('aria-selected', 'false');
  });

  const activeBtn = document.getElementById(`${tabType}Tab`);
  if (activeBtn) {
    activeBtn.classList.add('active');
    activeBtn.setAttribute('aria-selected', 'true');
  }

  // Update containers
  const textContent = document.getElementById('textTabContent');
  const projectContent = document.getElementById('projectTabContent');

  if (tabType === 'text') {
    if (textContent) textContent.style.display = 'block';
    if (projectContent) projectContent.style.display = 'none';
  } else {
    if (textContent) textContent.style.display = 'none';
    if (projectContent) projectContent.style.display = 'block';
  }
  
  triggerPreflight();
}

async function triggerPreflight() {
  try {
    state.preflightState = await checkPreflight(state.councilConfig, state.selectedFiles);
    renderPreflight(state.preflightState, state.selectedFiles.length > 0);
  } catch (e) {
    console.error('Preflight error', e);
    const box = document.getElementById('preflightBox');
    if (box) {
      box.innerHTML = '<div class="status-line status-bad">Preflight failed. Make sure Ollama or the local backend server is running.</div>';
      box.classList.remove('collapsed');
    }
  }
}

function applyModelProfile(profile, btn) {
  const profileConfig = MODEL_PROFILES[profile];
  if (!profileConfig) return;

  // Render button active state
  btn.parentNode.querySelectorAll('button').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');

  for (const [id, seat] of Object.entries(state.councilConfig)) {
    if (profileConfig[id]) {
      seat.model = profileConfig[id];
    } else if (id !== 'chairman') {
      seat.model = profileConfig.architect;
    }
  }

  renderSeatsList(state.councilConfig, removeSeat, updateSeat);
  renderActiveRosterOverview(state.councilConfig);
  triggerPreflight();
  showToast(`Applied ${profile.toUpperCase()} profile models.`);
}

function applyTokenBudget(budget, btn) {
  state.tokenBudgetProfile = budget;
  
  btn.parentNode.querySelectorAll('button').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');

  const summary = document.getElementById('tokenBudgetSummary');
  if (summary) {
    summary.textContent = TOKEN_BUDGET_SUMMARIES[budget];
  }
  showToast(`Switched token budget to ${budget.toUpperCase()}.`);
}

function toggleAdvancedSection() {
  state.isAdvancedExpanded = !state.isAdvancedExpanded;
  const section = document.getElementById('advancedSection');
  const btn = document.getElementById('advancedToggleBtn');

  if (section && btn) {
    if (state.isAdvancedExpanded) {
      section.classList.add('expanded');
      btn.setAttribute('aria-expanded', 'true');
      btn.textContent = '⚙️ Hide Advanced Settings';
    } else {
      section.classList.remove('expanded');
      btn.setAttribute('aria-expanded', 'false');
      btn.textContent = '⚙️ Show Advanced Settings';
    }
  }
}

async function autoConfigureHardware() {
  try {
    const hw = await fetchHardwareSuggestion();
    showToast(`Detected RAM: ${hw.ram_gb} GB (${hw.tier_name}). Applied auto-tuned models.`);
    state.councilConfig = hw.config;
    renderSeatsList(state.councilConfig, removeSeat, updateSeat);
    renderActiveRosterOverview(state.councilConfig);
    triggerPreflight();
  } catch (e) {
    console.error(e);
    showToast('Failed to auto-configure hardware.');
  }
}

function addSeat() {
  const id = 'seat_' + Math.floor(Math.random() * 10000);
  state.councilConfig[id] = {
    label: "Expert Seat",
    model: "ollama/qwen2.5:7b",
    color: "#" + Math.floor(Math.random()*16777215).toString(16),
    icon: "🤖",
    persona: "You are a code review expert."
  };
  renderSeatsList(state.councilConfig, removeSeat, updateSeat);
  renderActiveRosterOverview(state.councilConfig);
  triggerPreflight();
}

function removeSeat(id) {
  delete state.councilConfig[id];
  renderSeatsList(state.councilConfig, removeSeat, updateSeat);
  renderActiveRosterOverview(state.councilConfig);
  triggerPreflight();
}

function updateSeat(id, field, value) {
  if (state.councilConfig[id]) {
    state.councilConfig[id][field] = value;
  }
  if (field === 'model') {
    renderActiveRosterOverview(state.councilConfig);
    triggerPreflight();
  }
}

function removeFile(index) {
  state.selectedFiles.splice(index, 1);
  renderSelectedFiles(state.selectedFiles, removeFile);
  triggerPreflight();
}

async function attachSample(sampleId) {
  if (!state.demoCatalog) return;
  const sample = (state.demoCatalog.samples || []).find(item => item.id === sampleId);
  if (!sample) return;

  try {
    const blob = await fetchSampleFileBlob(sample.filename);
    const file = new File([blob], sample.filename, { type: sample.content_type || blob.type || 'text/plain' });
    state.selectedFiles.push(file);
    renderSelectedFiles(state.selectedFiles, removeFile);
  } catch (e) {
    console.error('Failed to attach sample file', sample.filename, e);
  }
}

async function applyPreset(presetId) {
  if (!state.demoCatalog) return;
  const preset = state.demoCatalog.presets.find(p => p.id === presetId);
  if (!preset) return;

  renderLoadingState(document.getElementById('councilPanel'), 'Applying preset & loading demo files...');

  // Set configs
  state.councilConfig = configFromPreset(preset);
  
  // Set prompts
  document.getElementById('topicText').value = preset.topic || preset.topic_placeholder || '';
  
  // Set tab
  if (preset.active_tab) {
    switchContextTab(preset.active_tab);
  } else {
    switchContextTab('text');
  }

  // Load sample attachments
  state.selectedFiles = [];
  const sampleIds = preset.sample_ids || (preset.sample_files || [])
    .map(filename => (state.demoCatalog.samples || []).find(s => s.filename === filename)?.id)
    .filter(Boolean);

  for (const sId of sampleIds) {
    await attachSample(sId);
  }

  renderSeatsList(state.councilConfig, removeSeat, updateSeat);
  renderActiveRosterOverview(state.councilConfig);
  
  // Collapse Advanced Settings just in case
  if (state.isAdvancedExpanded) toggleAdvancedSection();

  // Redraw Empty State or active output box
  document.getElementById('councilPanel').innerHTML = `
    <div class="panel-empty">
      <h2 style="font-family: 'IBM Plex Sans', sans-serif; font-size: 20px; color: var(--text); font-weight:650;">Preset Applied!</h2>
      <div class="helper-copy" style="max-width:400px; margin-bottom: 20px;">The config roster and demo files for <strong>${preset.label}</strong> have been loaded successfully. Hit "Run council" below to execute the local analysis stream!</div>
      <button class="btn btn-solid" data-action="launch-council" style="font-size: 14px; padding: 10px 20px;">Run preset council</button>
    </div>
  `;

  triggerPreflight();
  showToast(`Loaded "${preset.label}" preset successfully.`);
}

// ── STREAM STREAM STREAM RUNNERS ──

async function executeRun() {
  const panel = document.getElementById('councilPanel');
  const btn = document.getElementById('launchBtn');
  if (!btn || !panel) return;

  const topic = document.getElementById('topicText').value.trim();
  const path = document.getElementById('projectPathInput').value.trim();

  // Preflight validation
  await triggerPreflight();
  if (!state.preflightState || !state.preflightState.ready) {
    return alert('Preflight blocked: Ensure Ollama models are running or configure valid local endpoints.');
  }

  // Choose tab route
  if (state.activeTab === 'text') {
    if (!topic && !state.selectedFiles.length) {
      return alert('Context error: Please paste a topic prompt or attach source files first.');
    }
  } else {
    if (!path) {
      return alert('Context error: Please specify an absolute path to a local directory.');
    }
  }

  // Setup UI loading states
  btn.disabled = true;
  btn.innerHTML = '🕒 Streaming Council...';
  renderLoadingState(panel, 'Initializing Council models and preparing context...');
  
  state.rawCardContents = {};
  state.thinkingCards = {};
  state.chatHistory = [];
  resetMetrics();

  ph2Section = null;
  ph3Section = null;

  try {
    if (state.activeTab === 'text') {
      const dynamicSwarm = document.getElementById('dynamicSwarmToggle')?.checked || false;
      const deepDebate = document.getElementById('deepDebateToggle')?.checked || false;

      await streamCouncilRun({
        topic,
        councilConfig: state.councilConfig,
        tokenBudgetProfile: state.tokenBudgetProfile,
        selectedFiles: state.selectedFiles,
        dynamicSwarm,
        deepDebate,
        onEvent: (ev) => handleSSEEvent(ev, panel),
        onError: (err) => {
          showToast(err.message);
          renderErrorState(panel, err.message);
        }
      });
    } else {
      const deepDebate = document.getElementById('deepDebateToggle')?.checked || false;
      const infoDiv = document.getElementById('projectScanInfo');
      if (infoDiv) infoDiv.textContent = 'Scanning files...';

      await streamProjectReview({
        path,
        deepDebate,
        councilConfig: state.councilConfig,
        tokenBudgetProfile: state.tokenBudgetProfile,
        onEvent: (ev) => {
          if (ev.type === 'project_info') {
            if (infoDiv) infoDiv.textContent = `Scanned ${ev.total_files} files → reviewing ${ev.files_selected.length} core files`;
          } else {
            handleSSEEvent(ev, panel);
          }
        },
        onError: (err) => {
          showToast(err.message);
          renderErrorState(panel, err.message);
        }
      });
    }
  } catch (err) {
    console.error(err);
  } finally {
    btn.disabled = false;
    btn.innerHTML = 'Run council';
  }
}

function handleSSEEvent(ev, panel) {
  if (ev.type === 'error') {
    showToast(ev.message);
    panel.appendChild(Object.assign(document.createElement('div'), {
      className: 'status-card',
      style: 'border-left: 4px solid var(--danger); margin-top:16px;',
      innerHTML: `<div class="preset-title status-bad">Runtime Error</div><div class="status-line status-bad">${escapeHtml(ev.message)}</div>`
    }));
    return;
  }

  if (ev.type === 'warning') {
    showToast(ev.message);
    panel.appendChild(Object.assign(document.createElement('div'), {
      className: 'status-card',
      style: 'border-left: 4px solid var(--warm); margin-top:16px;',
      innerHTML: `<div class="preset-title status-warn">Fallback Warning</div><div class="status-line status-warn">${escapeHtml(ev.message)}</div>`
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

    const seatMeta = state.councilConfig[ev.member] || { label: ev.member, color: '#888', icon: '🤖' };
    const card = buildCard(ev.member, seatMeta, phase);
    grid.appendChild(card);
    state.thinkingCards[`${ev.member}-${phase}`] = card;
    card.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    return;
  }

  if (ev.type === 'member_token') {
    let phase = 1;
    if (ph3Section && ph3Section.contains(state.thinkingCards[`${ev.member}-3`])) phase = 3;
    else if (ph2Section && ph2Section.contains(state.thinkingCards[`${ev.member}-2`])) phase = 2;
    
    const key = `${ev.member}-${phase}`;
    const card = state.thinkingCards[key];
    
    if (card) {
      const body = card.querySelector('.card-body');
      const pulse = card.querySelector('.typing');
      if (pulse) { 
        pulse.remove(); 
        body.style.display = 'block'; 
      }
      
      if (!state.rawCardContents[key]) state.rawCardContents[key] = '';
      state.rawCardContents[key] += ev.chunk;

      if (ev.member !== 'chairman') {
        body.innerHTML = renderMarkdown(state.rawCardContents[key]);
      } else {
        body.innerHTML = `<pre>${escapeHtml(state.rawCardContents[key])}</pre>`;
      }

      // Calculate live speeds
      updateCardStreamMetrics(ev.member, phase, ev.chunk.length);
    }
    return;
  }
  
  if (ev.type === 'member_done') {
    let phase = 1;
    if (ph3Section && ph3Section.contains(state.thinkingCards[`${ev.member}-3`])) phase = 3;
    else if (ph2Section && ph2Section.contains(state.thinkingCards[`${ev.member}-2`])) phase = 2;
    const key = `${ev.member}-${phase}`;
    const card = state.thinkingCards[key];
    
    if (card && ev.member === 'chairman') {
      const body = card.querySelector('.card-body');
      try {
        const data = JSON.parse(ev.full_text);
        let riskColor = "var(--accent)";
        if (data.risk_score >= 8) riskColor = "var(--danger)";
        else if (data.risk_score >= 5) riskColor = "var(--warm)";

        const riskScore = escapeHtml(data.risk_score ?? '');
        let html = `
          <h2>VERDICT: ${escapeHtml(data.verdict || '')}</h2>
          <div style="font-size: 24px; color: ${riskColor}; font-weight:700; margin: 10px 0;">RISK SCORE: ${riskScore}/10</div>
          <h3>Action Items:</h3>
          <ul>${(data.action_items || []).map(a => `<li>${escapeHtml(a)}</li>`).join('')}</ul>
        `;
        if (data.consensus && data.consensus.length > 0) {
          html += `<h3>Consensus:</h3><ul>${data.consensus.map(c => `<li>${escapeHtml(c)}</li>`).join('')}</ul>`;
        }
        if (data.disputes && data.disputes.length > 0) {
          html += `<h3>Disputes:</h3><ul>${data.disputes.map(d => `<li>${escapeHtml(d)}</li>`).join('')}</ul>`;
        }
        body.innerHTML = html;
      } catch (e) {
        body.innerHTML = renderMarkdown(ev.full_text);
      }
    }
    return;
  }

  if (ev.type === 'done') {
    showDebatePanel(panel);
  }
}

// ── INTERACTIVE DEBATE ──

function showDebatePanel(panel) {
  const div = document.createElement('div');
  div.innerHTML = `
    <div class="debate-panel" style="display:block">
      <div class="debate-header">
        <span>💬 Interactive Council Debate</span>
        <button class="btn btn-small btn-solid" data-action="export-report">Export Full Report</button>
      </div>
      <div class="chat-history" id="chatHistory"></div>
      <div class="chat-input-row">
        <select id="chatTarget" class="chat-select">
          ${Object.entries(state.councilConfig).map(([id, cfg]) => `<option value="${id}">@${cfg.label}</option>`).join('')}
        </select>
        <input type="text" id="chatInput" placeholder="Ask a question to any seat...">
        <button class="btn btn-solid" data-action="chat-send" id="chatBtn">Send</button>
      </div>
    </div>
  `;
  panel.appendChild(div);
  div.scrollIntoView({ behavior: 'smooth', block: 'end' });
}

async function sendInteractiveChat() {
  const input = document.getElementById('chatInput');
  const targetId = document.getElementById('chatTarget')?.value;
  const msg = input?.value.trim();
  if (!msg || !targetId) return;

  const historyDiv = document.getElementById('chatHistory');
  const sendBtn = document.getElementById('chatBtn');
  if (!historyDiv || !sendBtn) return;

  // Update user
  state.chatHistory.push({ role: 'user', content: msg });
  const uEl = document.createElement('div');
  uEl.className = 'chat-msg chat-user';
  uEl.textContent = msg;
  historyDiv.appendChild(uEl);
  input.value = '';

  // Update assistant placeholder
  const aEl = document.createElement('div');
  aEl.className = 'chat-msg chat-agent';
  aEl.innerHTML = '<div class="typing"><span></span><span></span><span></span></div>';
  historyDiv.appendChild(aEl);
  historyDiv.scrollTop = historyDiv.scrollHeight;

  sendBtn.disabled = true;

  try {
    let fullReply = '';
    await streamDebateChat({
      targetId,
      chatHistory: state.chatHistory,
      councilConfig: state.councilConfig,
      tokenBudgetProfile: state.tokenBudgetProfile,
      onToken: (chunk) => {
        const pulse = aEl.querySelector('.typing');
        if (pulse) pulse.remove();

        fullReply += chunk;
        aEl.innerHTML = renderMarkdown(fullReply);
        historyDiv.scrollTop = historyDiv.scrollHeight;
      },
      onError: (err) => {
        aEl.innerHTML = `<span style="color:var(--danger)">Connection failed: ${escapeHtml(err.message)}</span>`;
      }
    });

    state.chatHistory.push({ role: 'assistant', content: fullReply });
  } catch (err) {
    console.error(err);
  } finally {
    sendBtn.disabled = false;
  }
}

function exportReport() {
  let md = "# Local LLM Council Review Report\n\n";
  const topicText = document.getElementById('topicText')?.value || '';
  const dirText = document.getElementById('projectPathInput')?.value || '';

  md += `## Review Context\n`;
  if (state.activeTab === 'text') {
    md += `**Review Type:** Topic / Code Files review\n`;
    md += `**Prompt Brief:**\n${topicText}\n\n`;
  } else {
    md += `**Review Type:** Local project workspace review\n`;
    md += `**Directory Path:** \`${dirText}\`\n\n`;
  }
  
  md += "## Council Roster & Configurations\n";
  for (const [id, seat] of Object.entries(state.councilConfig)) {
    md += `- **${seat.label}** (${seat.model}) [${seat.icon}]\n`;
  }
  md += "\n---\n\n";

  // Compile raw cards
  for (const [key, content] of Object.entries(state.rawCardContents)) {
    const [member, phase] = key.split('-');
    const meta = state.councilConfig[member] || { label: member };
    const phaseName = phase == 1 ? "Analysis" : (phase == 2 ? "Review" : "Final Verdict");
    md += `## ${meta.label} - Phase ${phase} (${phaseName})\n\n`;
    md += content + "\n\n---\n\n";
  }

  if (state.chatHistory.length > 0) {
    md += "## Interactive Debate & Follow-ups\n\n";
    state.chatHistory.forEach(msg => {
      md += `**${msg.role.toUpperCase()}**: ${msg.content}\n\n`;
    });
  }

  const blob = new Blob([md], { type: 'text/markdown' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `council_report_${Date.now()}.md`;
  a.click();
  showToast('Markdown report generated and downloading.');
}

// ── REPLAYS HISTORICAL LOGS RENDERING ──

function openReplayInspector(highlightRunId = null) {
  openModal('📂 Historical Run Inspector', `
    <div class="replay-layout">
      <div class="replay-sidebar" id="replayRunList"></div>
      <div class="replay-detail" id="replayRunDetail"></div>
    </div>
  `, (body) => {
    loadReplayRuns(body, highlightRunId);
  });
}

async function loadReplayRuns(container, highlightRunId = null) {
  const list = container.querySelector('#replayRunList');
  const detail = container.querySelector('#replayRunDetail');

  if (!list || !detail) return;

  list.innerHTML = '<div class="replay-empty">Loading runs from disk...</div>';
  detail.innerHTML = '<div class="replay-empty">Select any historical run from the sidebar.</div>';

  try {
    const resp = await fetch('/runs?limit=25');
    const data = await resp.json();
    const runs = data.runs || [];

    if (!runs.length) {
      list.innerHTML = '<div class="replay-empty">No persisted sqlite runs database.</div>';
      return;
    }

    list.innerHTML = runs.map(run => {
      const started = run.started_at ? new Date(run.started_at * 1000).toLocaleString() : 'unknown';
      const topic = escapeHtml((run.topic || '').slice(0, 52) || 'Project Review Workspace');
      return `
        <div class="replay-run-item" data-run-id="${run.run_id}">
          <div class="replay-run-title">${topic}</div>
          <div class="replay-run-meta">
            run_id: ${escapeHtml(run.run_id.slice(0, 8))}<br>
            status: ${escapeHtml(run.status)}<br>
            started: ${escapeHtml(started)}
          </div>
        </div>
      `;
    }).join('');

    // Wire up clicks
    list.querySelectorAll('.replay-run-item').forEach(el => {
      el.addEventListener('click', () => {
        list.querySelectorAll('.replay-run-item').forEach(x => x.classList.remove('active'));
        el.classList.add('active');
        const rId = el.getAttribute('data-run-id');
        loadReplayRunDetail(rId, detail);
      });
    });

    // Auto-load first or highlight
    let initialRunId = highlightRunId;
    if (!initialRunId && runs.length > 0) {
      initialRunId = runs[0].run_id;
    }

    if (initialRunId) {
      const activeEl = list.querySelector(`[data-run-id="${initialRunId}"]`);
      if (activeEl) {
        list.querySelectorAll('.replay-run-item').forEach(x => x.classList.remove('active'));
        activeEl.classList.add('active');
        activeEl.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      }
      loadReplayRunDetail(initialRunId, detail);
    }

  } catch (e) {
    console.error(e);
    list.innerHTML = '<div class="replay-empty">Failed to query historical runs.</div>';
  }
}

async function loadReplayRunDetail(runId, container) {
  container.innerHTML = '<div class="replay-empty">Loading execution record...</div>';

  try {
    const resp = await fetch(`/runs/${encodeURIComponent(runId)}`);
    const run = await resp.json();

    if (!run || !run.run_id) {
      container.innerHTML = '<div class="replay-empty">Run profile not found on server.</div>';
      return;
    }

    const roster = run.roster || {};
    const phases = run.phases || [];
    const started = run.started_at ? new Date(run.started_at * 1000).toLocaleString() : 'unknown';
    const finished = run.finished_at ? new Date(run.finished_at * 1000).toLocaleString() : 'in progress';
    
    const chairmanPhase = phases.find(p => p.phase === 3 && p.member_id === 'chairman');
    let verdictSummary = '';
    if (chairmanPhase) {
      try {
        const cJson = JSON.parse(chairmanPhase.output || '{}');
        let riskColor = "var(--accent)";
        if (cJson.risk_score >= 8) riskColor = "var(--danger)";
        else if (cJson.risk_score >= 5) riskColor = "var(--warm)";

        verdictSummary = `
          <div class="status-card" style="border-left:4px solid ${riskColor}; margin: 12px 0;">
            <div class="preset-title" style="color:${riskColor}">Verdict: ${escapeHtml(cJson.verdict)}</div>
            <div class="status-line">Risk score: <strong>${cJson.risk_score}/10</strong></div>
            <div class="status-line">Action items: ${(cJson.action_items || []).join(', ')}</div>
          </div>
        `;
      } catch {}
    }

    const phasesHtml = phases.map(phase => {
      const seat = roster[phase.member_id] || {};
      const label = seat.label || phase.member_id;
      const color = seat.color || 'var(--accent)';
      const icon = seat.icon || '•';

      let outBody = '';
      if (phase.phase === 3 && phase.member_id === 'chairman') {
        try {
          const parsed = JSON.parse(phase.output || '{}');
          outBody = `
            <h3>Verdict Summary</h3>
            <p><strong>Verdict:</strong> ${escapeHtml(parsed.verdict)}</p>
            <p><strong>Risk Rating:</strong> ${parsed.risk_score}/10</p>
            <p><strong>Proposed Remedies:</strong></p>
            <ul>${(parsed.action_items || []).map(x => `<li>${escapeHtml(x)}</li>`).join('')}</ul>
          `;
        } catch {
          outBody = renderMarkdown(phase.output);
        }
      } else {
        outBody = renderMarkdown(phase.output);
      }

      return `
        <div class="replay-phase">
          <div class="replay-phase-head">
            <div class="replay-member" style="color:${color}">${icon} ${escapeHtml(label)}</div>
            <div class="replay-phase-meta">Phase ${phase.phase} • ${escapeHtml(phase.member_id)}</div>
          </div>
          <div class="card-body" style="display:block; margin-top:8px;">${outBody}</div>
        </div>
      `;
    }).join('');

    container.innerHTML = `
      <div class="preset-title">${escapeHtml(run.topic || 'Untitled Project Review')}</div>
      <div class="replay-run-meta" style="margin-top:4px;">
        run_id: ${escapeHtml(run.run_id)}<br>
        status: ${escapeHtml(run.status)}<br>
        started: ${escapeHtml(started)}<br>
        finished: ${escapeHtml(finished)}
      </div>
      ${verdictSummary}
      ${phasesHtml || '<div class="replay-empty">No streams recorded.</div>'}
    `;

  } catch (e) {
    console.error(e);
    container.innerHTML = '<div class="replay-empty">Error fetching run details.</div>';
  }
}

// ── LAUNCH ──
init();
export default {};
