let activeCouncilAbortController = null;
let memberTokenStats = {};
let latestChairmanPayload = null;

function stopActiveRun() {
  if (activeCouncilAbortController) {
    activeCouncilAbortController.abort();
    activeCouncilAbortController = null;
    showToast('Council run stopped.');
  }
}

async function launchCouncil() {
  if (activeCouncilAbortController) {
    stopActiveRun();
    return;
  }

  const topic = document.getElementById('topicText')?.value.trim();
  if (!topic && !selectedFiles.length) return alert('Enter a topic or attach at least one file.');
  await refreshPreflight();
  if (!preflightState || !preflightState.ready) {
    return alert('Demo preflight failed. Install the missing models or switch to a preset that matches your local setup.');
  }

  const btn = document.getElementById('launchBtn');
  const panel = document.getElementById('councilPanel');
  if (btn) {
    btn.disabled = false;
    btn.classList.add('btn-danger');
    btn.innerHTML = 'Stop council';
  }

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
    if (btn) {
      btn.disabled = false;
      btn.classList.remove('btn-danger');
      btn.innerHTML = 'Run council';
    }
  }
}

async function launchProjectReview() {
  if (activeCouncilAbortController) {
    stopActiveRun();
    return;
  }

  const path = document.getElementById('projectPathInput')?.value.trim();
  if (!path) return alert('Enter a project directory path to review.');

  const btn = document.getElementById('projectReviewBtn');
  const launchBtn = document.getElementById('launchBtn');
  const panel = document.getElementById('councilPanel');
  const infoDiv = document.getElementById('projectScanInfo');

  if (btn) { btn.disabled = true; btn.textContent = 'Scanning...'; }
  if (launchBtn) {
    launchBtn.disabled = false;
    launchBtn.classList.add('btn-danger');
    launchBtn.textContent = 'Stop council';
  }
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
    if (btn) { btn.disabled = false; btn.textContent = 'Scan & Review'; }
    if (launchBtn) {
      launchBtn.disabled = false;
      launchBtn.classList.remove('btn-danger');
      launchBtn.textContent = 'Run council';
    }
  }
}

function playCompletionChime() {
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    const now = ctx.currentTime;
    
    const osc1 = ctx.createOscillator();
    const gain1 = ctx.createGain();
    osc1.type = 'sine';
    osc1.frequency.setValueAtTime(587.33, now);
    gain1.gain.setValueAtTime(0.10, now);
    gain1.gain.exponentialRampToValueAtTime(0.001, now + 0.3);
    osc1.connect(gain1);
    gain1.connect(ctx.destination);
    osc1.start(now);
    osc1.stop(now + 0.3);

    const osc2 = ctx.createOscillator();
    const gain2 = ctx.createGain();
    osc2.type = 'sine';
    osc2.frequency.setValueAtTime(880.00, now + 0.12);
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
  let md = `## 👑 LLM Council Verdict: ${data.verdict || 'COMPLETE'}\n\n`;
  md += `**Risk Score:** \`${riskDisplay}\`\n\n`;
  
  if (data.action_items && data.action_items.length) {
    md += `### 📋 Required Action Items\n`;
    data.action_items.forEach(item => { md += `- [ ] ${item}\n`; });
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
