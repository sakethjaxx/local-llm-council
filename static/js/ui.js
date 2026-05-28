// ── DOM RENDERING & UI UX Polish MODULE ──

export function escapeHtml(value) {
  return String(value || '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

export function renderMarkdown(text) {
  if (window.marked && window.DOMPurify) {
    const rawHtml = window.marked.parse(text || '');
    return window.DOMPurify.sanitize(rawHtml, { USE_PROFILES: { html: true } });
  }
  return `<p>${escapeHtml(text).replaceAll('\n', '<br>')}</p>`;
}

/**
 * Modern notification stack.
 */
export function showToast(message) {
  const stack = document.getElementById('toastStack');
  if (!stack) return;

  const toast = document.createElement('div');
  toast.className = 'toast';
  toast.textContent = message || 'Something went wrong.';
  
  // Set default border color if it represents success or warning
  if (message.toLowerCase().includes('success') || message.toLowerCase().includes('ready') || message.toLowerCase().includes('complete')) {
    toast.style.borderLeftColor = 'var(--accent)';
  } else if (message.toLowerCase().includes('warning') || message.toLowerCase().includes('wait')) {
    toast.style.borderLeftColor = 'var(--warm)';
  } else {
    toast.style.borderLeftColor = 'var(--danger)';
  }

  stack.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transform = 'translateY(8px)';
    toast.style.transition = 'all 0.3s ease';
    setTimeout(() => toast.remove(), 300);
  }, 6000);
}

/**
 * Skeletal loading state for output window.
 */
export function renderLoadingState(panel, message) {
  panel.innerHTML = `
    <div class="run-skeleton">
      <div style="font-weight:600; display:flex; align-items:center; gap:8px;">
        <span class="typing" style="padding:0;"><span style="animation-delay:0s"></span><span style="animation-delay:0.2s"></span><span style="animation-delay:0.4s"></span></span>
        ${escapeHtml(message || 'Initializing council...')}
      </div>
      <div class="skeleton-line"></div>
      <div class="skeleton-line short"></div>
    </div>
  `;
}

export function renderErrorState(panel, message) {
  panel.innerHTML = `
    <div class="status-card" style="border-left: 4px solid var(--danger);">
      <div class="preset-title status-bad" style="display:flex; align-items:center; gap:6px;">⚠️ Run Blocked</div>
      <div class="status-line status-bad" style="margin-top:6px;">${escapeHtml(message || 'Unknown error occurred')}</div>
    </div>
  `;
}

/**
 * Preset empty state cards CTA.
 */
export function renderPresets(presets, onPresetSelect) {
  const grid = document.getElementById('presetGrid');
  if (!grid) return;

  if (!presets || presets.length === 0) {
    grid.innerHTML = '<div class="status-line">No presets loaded. Is the server online?</div>';
    return;
  }

  grid.innerHTML = presets.map(preset => `
    <div class="preset-card" data-preset-id="${preset.id}">
      <div>
        <div class="preset-title">${preset.icon || '🚀'} ${escapeHtml(preset.label)}</div>
        <div class="preset-desc">${escapeHtml(preset.description)}</div>
      </div>
      <div style="margin-top:12px; font-weight:600; font-size:11px; color:var(--accent); text-transform:uppercase; letter-spacing:0.04em;">
        Apply Preset &amp; Samples →
      </div>
    </div>
  `).join('');

  // Wire up clicks
  grid.querySelectorAll('.preset-card').forEach(card => {
    card.addEventListener('click', () => {
      const presetId = card.getAttribute('data-preset-id');
      onPresetSelect(presetId);
    });
  });
}

/**
 * File attachment pills.
 */
export function renderSelectedFiles(selectedFiles, onRemove) {
  const fileList = document.getElementById('fileList');
  if (!fileList) return;

  if (!selectedFiles.length) {
    fileList.innerHTML = '';
    return;
  }

  fileList.innerHTML = selectedFiles.map((file, i) => {
    const sizeKb = Math.max(1, Math.round(file.size / 1024));
    return `
      <div class="file-list-item">
        <span>📄 ${escapeHtml(file.name)} <span style="color:var(--muted); font-size:10px;">(${sizeKb} KB)</span></span>
        <button class="btn btn-small" data-action="remove-file" data-index="${i}" style="background:none; border:none; color:var(--danger); cursor:pointer; padding:0;" title="Remove attachment">✕</button>
      </div>
    `;
  }).join('');

  // Wire up removes
  fileList.querySelectorAll('[data-action="remove-file"]').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const index = parseInt(btn.getAttribute('data-index'));
      onRemove(index);
    });
  });
}

/**
 * Environment Preflight collapses when passed successfully.
 */
export function renderPreflight(preflightState, hasFiles) {
  const box = document.getElementById('preflightBox');
  if (!box) return;

  if (!preflightState) {
    box.innerHTML = '<div class="status-line">Running environment preflight...</div>';
    box.classList.remove('collapsed');
    return;
  }

  // Preflight auto-collapses when ready (Zero warnings / missing models)
  const isReady = preflightState.ready;
  const warnings = preflightState.warnings || [];
  const missing = preflightState.missing || [];

  if (isReady && warnings.length === 0 && missing.length === 0) {
    box.innerHTML = `
      <div class="status-good" style="font-size:12px; display:flex; align-items:center; gap:6px;">
        ✅ Local environment checks passed. All models online.
      </div>
    `;
    box.classList.add('collapsed');
    return;
  }

  // Otherwise, expand and assist
  box.classList.remove('collapsed');
  const statusClass = isReady ? 'status-good' : 'status-bad';
  
  const missingHtml = missing.length
    ? `<div class="status-line status-bad">⚠️ Missing local models: ${escapeHtml(missing.join(', '))}</div>`
    : `<div class="status-line status-good">✓ Required local models are available.</div>`;

  const warningHtml = warnings.map(w => `<div class="status-line status-warn">⚠ ${escapeHtml(w)}</div>`).join('');

  box.innerHTML = `
    <div class="preset-title ${statusClass}">${isReady ? 'Environment Ready' : 'Environment Blocked'}</div>
    <div class="status-line">Detected local models: ${escapeHtml((preflightState.installed || []).join(', ') || 'None')}</div>
    ${missingHtml}
    ${warningHtml}
  `;
}

/**
 * Render compact Roster overview for Step 2 list.
 */
export function renderActiveRosterOverview(councilConfig) {
  const container = document.getElementById('activeRosterOverview');
  if (!container) return;

  const items = Object.entries(councilConfig).map(([id, seat]) => {
    return `
      <div class="active-roster-item">
        <span style="color:${seat.color}; font-size:14px;">${seat.icon}</span>
        <span style="font-weight:600;">${escapeHtml(seat.label)}</span>
        <span style="font-family:'IBM Plex Mono', monospace; font-size:10px; color:var(--muted)">(${seat.model.split('/').pop()})</span>
      </div>
    `;
  }).join('');

  container.innerHTML = items || '<div class="status-line">Roster is empty. Add a seat below.</div>';
}

/**
 * Render Advanced manual seats customization list.
 */
export function renderSeatsList(councilConfig, onRemove, onUpdate) {
  const list = document.getElementById('seatList');
  if (!list) return;

  list.innerHTML = '';

  for (const [id, seat] of Object.entries(councilConfig)) {
    const isChairman = id === 'chairman';
    const div = document.createElement('div');
    div.className = 'seat-item';
    div.innerHTML = `
      <div class="seat-header">
        <span style="color: ${seat.color}; font-size: 14px;">${seat.icon}</span>
        <div class="seat-title">${escapeHtml(seat.label)}</div>
        <div class="seat-model">${escapeHtml(seat.model.split('/').pop())}</div>
        ${!isChairman ? `<button class="btn btn-small" data-action="remove-seat" data-id="${id}" style="border:none; background:none; color:var(--danger); cursor:pointer; font-size:12px; margin-left:auto; padding:0;">✕</button>` : ''}
      </div>
      <div class="seat-edit-fields">
        <label style="font-size:11px; color:var(--muted); font-weight:600;">Model Endpoint</label>
        <input type="text" value="${escapeHtml(seat.model)}" data-field="model" data-id="${id}" placeholder="Model, e.g. ollama/qwen2.5:3b">
        <label style="font-size:11px; color:var(--muted); font-weight:600;">System Persona Prompt</label>
        <textarea style="min-height:50px; font-family:sans-serif; font-size:12px; padding:8px 10px;" data-field="persona" data-id="${id}" placeholder="Persona Instructions...">${escapeHtml(seat.persona)}</textarea>
      </div>
    `;
    list.appendChild(div);
  }

  // Wire up removes
  list.querySelectorAll('[data-action="remove-seat"]').forEach(btn => {
    btn.addEventListener('click', () => {
      const id = btn.getAttribute('data-id');
      onRemove(id);
    });
  });

  // Wire up inputs changes
  list.querySelectorAll('input, textarea').forEach(el => {
    el.addEventListener('change', () => {
      const id = el.getAttribute('data-id');
      const field = el.getAttribute('data-field');
      onUpdate(id, field, el.value.trim());
    });
  });
}

/**
 * Builds standard card for streaming output.
 * Color-blind accessible: Uses prominent labels and icon graphics, color is secondary.
 */
export function buildCard(member, meta, phase) {
  const isChairman = member === 'chairman';
  const card = document.createElement('div');
  card.className = isChairman ? 'council-card chairman-card' : 'council-card';
  card.id = `card-${member}-${phase}`;

  const color = meta.color || '#888';
  card.innerHTML = `
    <div class="card-header" style="border-bottom-color: ${color}33">
      <div class="card-icon" style="color:${color}; filter: drop-shadow(0 0 6px ${color}33);">${meta.icon}</div>
      <div class="card-name" style="color:${color}">${escapeHtml(meta.label.toUpperCase())}</div>
    </div>
    <div class="typing"><span></span><span></span><span></span></div>
    <div class="card-body" style="display:none" aria-live="polite"></div>
    <div class="card-metrics" id="metrics-${member}-${phase}" style="display:none;"></div>
  `;
  return card;
}

// ── REAL TIME SPEED METRICS TRACKER ──

const metricsTracker = {};

export function resetMetrics() {
  for (const k in metricsTracker) delete metricsTracker[k];
}

export function updateCardStreamMetrics(member, phase, chunkLength) {
  const key = `${member}-${phase}`;
  const now = Date.now();

  if (!metricsTracker[key]) {
    metricsTracker[key] = {
      firstTokenTime: now,
      totalChars: 0
    };
  }

  metricsTracker[key].totalChars += chunkLength;

  const data = metricsTracker[key];
  const elapsedSecs = (now - data.firstTokenTime) / 1000;
  const tokensCount = Math.round(data.totalChars / 4.0); // 1 token approx 4 characters

  const badge = document.getElementById(`metrics-${member}-${phase}`);
  if (badge && tokensCount > 0) {
    const elapsed = Math.max(0.1, elapsedSecs);
    const speed = (tokensCount / elapsed).toFixed(1);
    badge.style.display = 'flex';
    badge.innerHTML = `<span>⚡ ${tokensCount} tokens • ${speed} tok/s</span>`;
  }
}
