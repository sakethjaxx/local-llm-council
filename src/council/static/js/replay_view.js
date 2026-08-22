async function openReplayModal() {
  const modal = document.getElementById('replayModal');
  if (modal) modal.style.display = 'flex';
  await loadReplayRuns();
}

function closeReplayModal() {
  const modal = document.getElementById('replayModal');
  if (modal) modal.style.display = 'none';
}

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
      const detail = document.getElementById('replayRunDetail');
      if (detail) detail.innerHTML = '<div class="replay-empty">No persisted runs.</div>';
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
  if (!detail) return;
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
