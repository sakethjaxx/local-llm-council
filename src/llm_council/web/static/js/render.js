// All DOM construction for the run view. The deliberation is the hero:
// Render section

import { state } from './state.js?v=20260709-editable-names';
import { escapeHtml, renderMarkdown, sanitizeHtml, extractStanceClient } from './utils.js';

export function renderErrorCard(panel, message, { retryAction = null, hint = null } = {}) {
  const card = document.createElement('div');
  card.className = 'status-card error-card';
  card.setAttribute('role', 'alert');
  card.innerHTML = `
    <div class="preset-title status-bad">Run failed</div>
    <div class="status-line status-bad">${escapeHtml(message || 'Unknown error')}</div>
    ${hint ? `<div class="status-line">${escapeHtml(hint)}</div>` : ''}
    ${retryAction ? `<button class="btn" data-action="${retryAction}">Retry run</button>` : ''}
  `;
  panel.appendChild(card);
  return card;
}

// Render section
export function mountStanceStrip(panel) {
  const strip = document.createElement('div');
  strip.className = 'stance-strip';
  strip.id = 'stanceStrip';
  strip.setAttribute('role', 'status');
  strip.setAttribute('aria-label', 'Council stances');
  const seats = Object.entries(state.councilConfig).filter(([id]) => id !== 'chairman');
  strip.innerHTML = seats
    .map(([id, cfg]) => `
      <span class="stance-chip stance-pending" id="stance-${escapeHtml(id)}">
        <span style="color:${escapeHtml(cfg.color || '#888')}">${escapeHtml(cfg.icon || '')}</span>
        <span>${escapeHtml(cfg.label || id)}</span>
        <span class="verdict">thinking...</span>
      </span>`)
    .join('');
  panel.appendChild(strip);
}

export function updateStanceChip(memberId, stance, source) {
  const chip = document.getElementById(`stance-${memberId}`);
  if (!chip || !stance) return;
  chip.className = `stance-chip stance-${(stance.verdict || '').toLowerCase() || 'pending'}`;
  const conf = stance.confidence != null ? ` ${stance.confidence}/10` : '';
  const verdictEl = chip.querySelector('.verdict');
  if (verdictEl) verdictEl.textContent = `${stance.verdict}${conf}`;
  const existingTag = chip.querySelector('.source-tag');
  if (existingTag) existingTag.remove();
  if (source && source !== 'native') {
    const tag = document.createElement('span');
    tag.className = 'source-tag';
    tag.title = source === 'fallback'
      ? 'This member did not emit a STANCE line; a follow-up classification recovered it.'
      : 'Stance updated during the rebuttal round.';
    tag.textContent = source;
    chip.appendChild(tag);
  }
}

export function updateStanceFromText(memberId, fullText) {
  const stance = extractStanceClient(fullText);
  if (stance) updateStanceChip(memberId, stance, 'native');
}

// Render section
export function renderGateCard(panel, ev) {
  const card = document.createElement('div');
  card.className = `status-card gate-card ${ev.split ? 'gate-split' : ''}`;
  const headline = ev.skip
    ? 'Council agrees - debate skipped'
    : ev.split
      ? 'Council split - debate begins'
      : 'Agreement unverified - debating to be safe';
  card.innerHTML = `
    <div class="preset-title">${escapeHtml(headline)}</div>
    <div class="status-line">${escapeHtml(ev.reason || '')}</div>
  `;
  panel.appendChild(card);

  for (const [member, stance] of Object.entries(ev.stances || {})) {
    updateStanceChip(member, stance, (ev.stance_sources || {})[member]);
  }
}

export function renderRebuttalResult(panel, ev) {
  const card = document.createElement('div');
  card.className = 'status-card';
  card.innerHTML = ev.converged
    ? `<div class="preset-title status-good">Rebuttal converged</div><div class="status-line">After hearing critiques, all members now hold the same stance.</div>`
    : `<div class="preset-title status-warn">Positions held</div><div class="status-line">Members defended their stances - the split stands for the Chairman to resolve.</div>`;
  panel.appendChild(card);
  for (const [member, stance] of Object.entries(ev.stances || {})) {
    updateStanceChip(member, stance, 'rebuttal');
  }
}

// Render section
function memberChipsFor(point) {
  const labels = Object.entries(state.councilConfig)
    .filter(([id]) => id !== 'chairman')
    .map(([id, cfg]) => ({ id, label: cfg.label || id }));
  const lowered = String(point).toLowerCase();
  const named = labels.filter(({ label }) => lowered.includes(label.toLowerCase()));
  if (!named.length) return '';
  return `<span class="receipt-members">${named
    .map(({ id, label }) => `<button type="button" class="receipt-member-chip" data-action="jump-to-member" data-member="${escapeHtml(id)}">${escapeHtml(label)}</button>`)
    .join('')}</span>`;
}

function receiptList(title, points) {
  if (!points || !points.length) return '';
  return `
    <h3>${escapeHtml(title)}</h3>
    ${points.map((p) => `<div class="receipt-point">${memberChipsFor(p)}${escapeHtml(p)}</div>`).join('')}
  `;
}

export function renderVerdictHero(panel, ev) {
  const container = state.ph3Section || panel;
  const hero = document.createElement('div');
  hero.className = 'verdict-hero';
  hero.setAttribute('role', 'region');
  hero.setAttribute('aria-label', "Chairman's verdict");

  const risk = Number.isFinite(+ev.risk_score) ? Math.max(0, Math.min(10, +ev.risk_score)) : null;
  const riskColor = risk == null ? 'var(--muted)' : risk >= 8 ? 'var(--danger)' : risk >= 5 ? 'var(--warm)' : 'var(--accent)';

  hero.innerHTML = sanitizeHtml(`
    <h2>VERDICT: ${escapeHtml(ev.verdict || 'unavailable')}</h2>
    ${risk != null ? `
      <div class="risk-line">
        <strong style="color:${riskColor}">Risk ${risk}/10</strong>
        <div class="risk-track"><div class="risk-fill" style="width:${risk * 10}%;background:${riskColor}"></div></div>
      </div>` : ''}
    ${(ev.action_items || []).length ? `
      <h3>Action items</h3>
      <ul>${ev.action_items.map((a) => `<li>${escapeHtml(a)}</li>`).join('')}</ul>` : ''}
    ${receiptList('Consensus - with receipts', ev.consensus)}
    ${receiptList('Disputes - with receipts', ev.disputes)}
    ${ev.removed_points > 0 ? `<div class="stripped-note">${ev.removed_points} unattributed claim${ev.removed_points === 1 ? '' : 's'} removed - the Chairman asserted agreement no member stated.</div>` : ''}
  `);
  container.appendChild(hero);

  // The raw streaming card served its purpose; collapse it now the real verdict rendered.
  const rawCard = state.thinkingCards['chairman-3'];
  if (rawCard) {
    const body = rawCard.querySelector('.card-body');
    if (body) {
      body.innerHTML = `<details><summary style="cursor:pointer;color:var(--muted);font-size:12px;">Raw chairman output</summary>${body.innerHTML}</details>`;
    }
  }
}

export function renderGroundingCard(panel, ev) {
  const container = state.ph3Section || panel;
  const card = document.createElement('div');
  card.className = 'status-card';
  if (ev.ratio == null) {
    card.innerHTML = `<div class="preset-title">Verdict grounding</div><div class="status-line">No consensus or dispute points to verify.</div>`;
  } else {
    const pct = Math.round(ev.ratio * 100);
    const cls = pct >= 60 ? 'status-line' : 'status-line status-warn';
    card.innerHTML = `
      <div class="preset-title">Verdict grounding</div>
      <div class="${cls}">${pct}% of consensus/dispute points trace to named members.</div>
      ${ev.enforced ? `<div class="status-line status-warn">Enforcement active: ${ev.removed} unattributed point${ev.removed === 1 ? '' : 's'} stripped from the verdict.</div>` : ''}
    `;
  }
  container.appendChild(card);
}

export function renderConfidenceCard(panel, ev) {
  const card = document.createElement('div');
  card.className = 'confidence-card';
  card.setAttribute('role', 'region');
  card.setAttribute('aria-label', 'Council confidence');
  const score = ev.score ?? 0;
  const scoreClass = score < 45 ? 'low' : score < 70 ? 'mid' : '';
  const bars = Object.entries(ev.components || {})
    .map(([name, val]) => `
      <span>${escapeHtml(name)}</span>
      <div class="confidence-bar-track"><div class="confidence-bar-fill" style="width:${Math.round(val * 100)}%"></div></div>
      <span>${Math.round(val * 100)}%</span>`)
    .join('');
  card.innerHTML = `
    <div class="confidence-headline">
      <span class="confidence-score ${scoreClass}">${score}</span>
      <div>
        <div class="preset-title">Council Confidence</div>
        <div class="status-line">${escapeHtml(ev.explanation || '')}</div>
      </div>
    </div>
    <div class="confidence-bars">${bars}</div>
  `;
  panel.appendChild(card);
}

// Render section
export function buildCard(member, meta) {
  const isChairman = member === 'chairman';
  const card = document.createElement('div');
  card.className = isChairman ? 'council-card chairman-card' : 'council-card';
  card.dataset.member = member;

  const color = (meta && meta.color) || '#888';
  card.innerHTML = `
    <div class="card-header">
      <div class="card-icon" style="color:${escapeHtml(color)}">${escapeHtml((meta && meta.icon) || '')}</div>
      <div class="card-name" style="color:${escapeHtml(color)}">${escapeHtml(((meta && meta.label) || member).toUpperCase())}</div>
    </div>
    <div class="typing" aria-label="generating"><span></span><span></span><span></span></div>
    <div class="card-body" style="display:none"></div>
  `;
  return card;
}

export function streamIntoCard(key, chunk, isChairman) {
  const existing = state.thinkingCards[key];
  if (!existing) return;
  const body = existing.querySelector('.card-body');
  const pulse = existing.querySelector('.typing');
  if (pulse) { pulse.remove(); body.style.display = 'block'; }
  if (!state.rawCardContents[key]) state.rawCardContents[key] = '';
  state.rawCardContents[key] += chunk;
  if (!isChairman) {
    body.innerHTML = renderMarkdown(state.rawCardContents[key]);
  } else {
    body.innerHTML = `<pre>${escapeHtml(state.rawCardContents[key])}</pre>`;
  }
}

export function jumpToMemberCard(memberId) {
  const cards = [...document.querySelectorAll(`.council-card[data-member="${CSS.escape(memberId)}"]`)];
  const target = cards[0];
  if (!target) return;
  target.scrollIntoView({ behavior: 'smooth', block: 'center' });
  target.classList.add('receipt-highlight');
  setTimeout(() => target.classList.remove('receipt-highlight'), 2400);
}
