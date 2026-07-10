// Run replay modal: browse persisted runs and their phase outputs.

import { escapeHtml, renderMarkdown } from './utils.js';

export async function openReplayModal() {
  const modal = document.getElementById('replayModal');
  modal.style.display = 'flex';
  await loadReplayRuns();
}

export function closeReplayModal() {
  document.getElementById('replayModal').style.display = 'none';
}

export async function loadReplayRuns() {
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

    list.innerHTML = runs
      .map((run) => {
        const started = run.started_at ? new Date(run.started_at * 1000).toLocaleString() : 'unknown';
        const topic = escapeHtml((run.topic || '').slice(0, 72) || 'Untitled run');
        const confidence = run.council_confidence != null ? ` · confidence ${escapeHtml(String(run.council_confidence))}` : '';
        return `
          <button class="replay-run-item" data-action="load-replay-run" data-run="${escapeHtml(run.run_id)}" style="display:block;width:100%;text-align:left;">
            <div class="replay-run-title">${topic}</div>
            <div class="replay-run-meta">run_id: ${escapeHtml(run.run_id)}<br>status: ${escapeHtml(run.status)}${confidence}<br>started: ${escapeHtml(started)}</div>
          </button>
        `;
      })
      .join('');

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
        <ul>${(data.action_items || []).map((item) => `<li>${escapeHtml(item)}</li>`).join('')}</ul>
        ${(data.consensus || []).length ? `<p><strong>Consensus:</strong></p><ul>${data.consensus.map((c) => `<li>${escapeHtml(c)}</li>`).join('')}</ul>` : ''}
        ${(data.disputes || []).length ? `<p><strong>Disputes:</strong></p><ul>${data.disputes.map((d) => `<li>${escapeHtml(d)}</li>`).join('')}</ul>` : ''}
      `;
    } catch (e) {
      return renderMarkdown(phase.output || '');
    }
  }
  return renderMarkdown(phase.output || '');
}

export async function loadReplayRunDetail(runId) {
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

    const trustBits = [];
    if (run.council_confidence != null) trustBits.push(`council confidence: ${escapeHtml(String(run.council_confidence))}/100`);
    if (run.grounding_ratio != null) trustBits.push(`grounding: ${Math.round(run.grounding_ratio * 100)}%`);
    if (run.stance_summary && run.stance_summary.agreement) trustBits.push(`agreement: ${escapeHtml(run.stance_summary.agreement)}`);
    const trustSummary = trustBits.length
      ? `<div class="status-card"><div class="preset-title">Trust signals</div><div class="status-line">${trustBits.join(' · ')}</div></div>`
      : '';

    const chairmanPhase = phases.find((phase) => phase.phase === 3 && phase.member_id === 'chairman');
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
      ${trustSummary}
      ${verdictSummary}
      ${phases
        .map((phase) => {
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
        })
        .join('') || '<div class="replay-empty">No phase outputs stored for this run.</div>'}
    `;
  } catch (e) {
    console.error('Failed to load replay detail', e);
    detail.innerHTML = '<div class="replay-empty">Failed to load run detail.</div>';
  }
}
