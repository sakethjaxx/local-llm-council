// SSE event to render dispatch. One entry point: handleEvent(ev, panel).

import { state } from './state.js?v=20260709-editable-names';
import { escapeHtml, showToast } from './utils.js';
import {
  buildCard,
  mountStanceStrip,
  renderConfidenceCard,
  renderErrorCard,
  renderGateCard,
  renderGroundingCard,
  renderRebuttalResult,
  renderVerdictHero,
  streamIntoCard,
  updateStanceFromText,
} from './render.js';
import { showDebatePanel } from './chat.js';

function phaseForMember(member) {
  if (state.ph3Section && state.ph3Section.contains(state.thinkingCards[`${member}-3`])) return 3;
  if (state.ph2Section && state.ph2Section.contains(state.thinkingCards[`${member}-2`])) return 2;
  return 1;
}

export function handleEvent(ev, panel) {
  switch (ev.type) {
    case 'run_started':
      state.currentRunId = ev.run_id;
      return;

    case 'error': {
      const message = ev.message || 'The council run failed.';
      showToast(message);
      renderErrorCard(panel, message, { retryAction: 'retry-run' });
      return;
    }

    case 'warning': {
      const isClone = /same model/i.test(ev.message || '');
      const warning = document.createElement('div');
      warning.className = 'status-card';
      warning.setAttribute('role', 'alert');
      warning.innerHTML = `<div class="preset-title status-warn">${isClone ? 'Council of clones' : 'Runtime fallback'}</div><div class="status-line status-warn">${escapeHtml(ev.message || 'A warning occurred.')}</div>`;
      panel.appendChild(warning);
      return;
    }

    case 'swarm_routed':
      if (ev.config) {
        state.councilConfig = ev.config;
      }
      return;

    case 'smart_phase_decision':
      renderGateCard(panel, ev);
      return;

    case 'rebuttal_start': {
      const banner = document.createElement('div');
      banner.className = 'phase-banner';
      banner.innerHTML = `<span>REBUTTAL // ${escapeHtml((ev.label || 'Members respond to critiques').toUpperCase())}</span>`;
      panel.appendChild(banner);
      return;
    }

    case 'rebuttal_result':
      renderRebuttalResult(panel, ev);
      return;

    case 'chairman_grounding':
      renderGroundingCard(panel, ev);
      return;

    case 'chairman_verdict':
      renderVerdictHero(panel, ev);
      return;

    case 'council_confidence':
      renderConfidenceCard(panel, ev);
      return;

    case 'phase_start': {
      const banner = document.createElement('div');
      banner.className = 'phase-banner';
      banner.innerHTML = `<span>PHASE ${escapeHtml(String(ev.phase))} // ${escapeHtml((ev.label || '').toUpperCase())}</span>`;
      panel.appendChild(banner);

      if (ev.phase === 1) mountStanceStrip(panel);

      const grid = document.createElement('div');
      grid.className = 'cards-grid';
      grid.id = `grid-phase${ev.phase}`;
      panel.appendChild(grid);

      if (ev.phase === 2) state.ph2Section = grid;
      if (ev.phase === 3) state.ph3Section = grid;
      grid.scrollIntoView({ behavior: 'smooth', block: 'end' });
      return;
    }

    case 'member_thinking': {
      const phase = ev.phase || 1;
      const grid = document.getElementById(`grid-phase${phase}`);
      if (!grid) return;
      const card = buildCard(ev.member, ev.meta);
      grid.appendChild(card);
      state.thinkingCards[`${ev.member}-${phase}`] = card;
      card.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      return;
    }

    case 'member_token': {
      const phase = phaseForMember(ev.member);
      streamIntoCard(`${ev.member}-${phase}`, ev.chunk, ev.member === 'chairman');
      return;
    }

    case 'member_done': {
      const phase = phaseForMember(ev.member);
      // Phase-1 completion updates the live stance chip (client-side preview;
      // the server's gate event overrides with the authoritative stance).
      if (phase === 1 && ev.member !== 'chairman') {
        updateStanceFromText(ev.member, ev.full_text || '');
      }
      return;
    }

    case 'done':
      showDebatePanel(panel);
      return;

    default:
      return;
  }
}
