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
  openDialog(modal.id);
  if (body) body.innerHTML = '<div class="replay-empty">Loading models...</div>';

  const data = await loadModelCatalog(true);
  if (!data) {
    if (body) body.innerHTML = '<div class="replay-empty">Failed to load model catalog.</div>';
    return;
  }
  renderModelCatalog(data, body);
  renderSeats();
}

function closeModelLibrary() {
  const modal = document.getElementById('modelLibraryModal');
  closeDialog(modal.id);
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

async function pullModel(tag) {
  const card = document.getElementById(`model-card-${tag}`);
  const btn = card ? card.querySelector('button') : null;
  const progressEl = document.getElementById(`model-progress-${tag}`);
  if (btn) { btn.disabled = true; btn.textContent = 'Downloading...'; }
  if (progressEl) progressEl.textContent = 'Starting download...';

  let completed = false;
  try {
    const response = await councilFetch(`/models/pull/stream?tag=${encodeURIComponent(tag)}`);
    if (!response.ok) throw new Error(`Download failed (HTTP ${response.status}).`);
    await readSse(response, data => {
    if (data.type === 'line' && progressEl) {
      progressEl.textContent = data.text;
    } else if (data.type === 'error' && progressEl) {
      progressEl.textContent = data.message;
    } else if (data.type === 'done') {
      completed = true;
      if (data.success) {
        if (progressEl) progressEl.textContent = 'Installed.';
        if (btn) btn.textContent = 'Installed';
        showToast(`${tag} installed.`);
        loadModelCatalog(true).then(() => renderSeats());
        refreshPreflight();
      } else {
        if (btn) { btn.disabled = false; btn.textContent = 'Retry download'; }
        showToast(`Failed to download ${tag}.`);
      }
    }
    });
    if (!completed) throw new Error('Download connection ended before completion.');
  } catch (error) {
    if (progressEl) progressEl.textContent = error.message || 'Connection lost.';
    if (btn) { btn.disabled = false; btn.textContent = 'Retry download'; }
  }
}
