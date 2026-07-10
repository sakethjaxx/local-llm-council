// Launching runs: full council and project review, with retry support.

import { state, resetRunState } from './state.js?v=20260709-editable-names';
import { renderLoadingState, showToast } from './utils.js';
import { cloudKeyHeaders, readSseStream } from './api.js';
import { renderErrorCard } from './render.js';
import { handleEvent } from './events.js';
import { refreshPreflight } from './config-panel.js';

function setRunControls(running, label = 'Council running...') {
  const launchBtn = document.getElementById('launchBtn');
  const stopBtn = document.getElementById('stopRunBtn');
  if (launchBtn) {
    launchBtn.disabled = running;
    launchBtn.textContent = running ? label : 'Run council';
  }
  if (stopBtn) {
    stopBtn.hidden = !running;
    stopBtn.disabled = !running;
  }
}

function beginRun(label) {
  state.runStopped = false;
  state.currentRunController = new AbortController();
  setRunControls(true, label);
  return state.currentRunController;
}

function endRun() {
  state.currentRunController = null;
  setRunControls(false);
}

export function stopRun() {
  if (!state.currentRunController) return;
  state.runStopped = true;
  state.currentRunController.abort();
  showToast('Run stopped.');
}

export async function launchCouncil() {
  const topic = document.getElementById('topicText').value.trim();
  if (!topic && !state.selectedFiles.length) {
    showToast('Enter a topic or attach at least one file.');
    return;
  }
  await refreshPreflight();
  if (!state.preflightState || !state.preflightState.ready) {
    showToast('Preflight failed: install the missing models (see Setup) or pick models you have.');
    return;
  }
  if ((state.preflightState.warnings || []).some((item) => item.includes('no seat is using a known image-capable local model'))) {
    showToast('Image attachments need an image-capable seat. Change one model before launching.');
    return;
  }

  const btn = document.getElementById('launchBtn');
  const panel = document.getElementById('councilPanel');
  const controller = beginRun('Council running...');

  btn.textContent = 'Council running...';
  renderLoadingState(panel, 'Starting council run...');
  resetRunState();

  const formData = new FormData();
  formData.append('topic_text', topic);
  formData.append('council_config', JSON.stringify(state.councilConfig));
  formData.append('token_budget_profile', state.tokenBudgetProfile);
  for (const file of state.selectedFiles) {
    formData.append('attachments', file);
  }
  if (document.getElementById('dynamicSwarmToggle')?.checked) {
    formData.append('dynamic_swarm', true);
  }
  if (state.deepDebate) {
    formData.append('deep_debate', true);
  }

  try {
    const resp = await fetch('/council/stream', {
      method: 'POST',
      headers: cloudKeyHeaders(),
      body: formData,
      signal: controller.signal,
    });
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      const message = err.detail || err.message || `Request failed with status ${resp.status}`;
      showToast(message);
      panel.innerHTML = '';
      renderErrorCard(panel, message, { retryAction: 'retry-run' });
      return;
    }

    panel.innerHTML = '';
    const sawDone = await readSseStream(resp, (ev) => handleEvent(ev, panel));
    if (!sawDone) {
      showToast('The stream ended before the council reported completion.');
    }
  } catch (err) {
    if (state.runStopped || err.name === 'AbortError') {
      panel.innerHTML = '';
      renderErrorCard(panel, 'Run stopped by user.', {
        retryAction: 'retry-run',
        hint: 'The browser stream was cancelled. Start again when ready.',
      });
      return;
    }
    showToast(err.message || 'SSE connection failed.');
    panel.innerHTML = '';
    renderErrorCard(panel, err.message || 'Connection failed', {
      retryAction: 'retry-run',
      hint: 'Check that the backend is still running, then retry.',
    });
  } finally {
    btn.disabled = false;
    btn.textContent = 'Run council';
    endRun();
  }
}


export async function launchProjectReview(pathOverride = null) {
  const path = pathOverride || document.getElementById('projectPathInput').value.trim();
  if (!path) {
    showToast('Enter a project directory path.');
    return;
  }

  const btn = document.getElementById('projectReviewBtn');
  const launchBtn = document.getElementById('launchBtn');
  const panel = document.getElementById('councilPanel');
  const infoDiv = document.getElementById('projectScanInfo');

  btn.disabled = true;
  btn.textContent = 'Scanning...';
  const controller = beginRun('Project review running...');
  renderLoadingState(panel, 'Scanning project and preparing review...');
  resetRunState();
  infoDiv.textContent = '';

  try {
    const resp = await fetch('/council/review-project', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...cloudKeyHeaders() },
      body: JSON.stringify({
        path,
        deep_debate: state.deepDebate,
        council_config: state.councilConfig,
        token_budget_profile: state.tokenBudgetProfile,
      }),
      signal: controller.signal,
    });

    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      const message = err.detail || 'Unknown error';
      showToast(message);
      panel.innerHTML = '';
      renderErrorCard(panel, message);
      return;
    }

    panel.innerHTML = '';
    const sawDone = await readSseStream(resp, (ev) => {
      if (ev.type === 'project_info') {
        infoDiv.textContent = `Scanning ${ev.total_files} files -> reviewing ${ev.files_selected.length} core files`;
      } else {
        handleEvent(ev, panel);
      }
    });
    if (!sawDone) {
      showToast('The project review stream ended before completion.');
    }
  } catch (err) {
    if (state.runStopped || err.name === 'AbortError') {
      panel.innerHTML = '';
      renderErrorCard(panel, 'Project review stopped by user.', {
        hint: 'The active stream was cancelled.',
      });
      return;
    }
    showToast(err.message || 'Project review connection failed.');
    panel.innerHTML = '';
    renderErrorCard(panel, err.message || 'Connection failed');
  } finally {
    btn.disabled = false;
    btn.textContent = 'Scan & Review';
    launchBtn.disabled = false;
    endRun();
  }
}

export function launchSelfReview() {
  const input = document.getElementById('projectPathInput');
  if (input) input.value = '.';
  return launchProjectReview();
}

export function exportReport() {
  let md = '# Universal Council Report\n\n';
  md += '## Topic\n' + document.getElementById('topicText').value + '\n\n';

  for (const [key, content] of Object.entries(state.rawCardContents)) {
    const [member, phase] = key.split('-');
    const meta = state.councilConfig[member] || { label: member };
    const phaseName = phase == 1 ? 'Analysis' : phase == 2 ? 'Review' : 'Verdict';
    md += `## ${meta.label} - Phase ${phase} (${phaseName})\n\n`;
    md += content + '\n\n---\n\n';
  }

  if (state.chatHistory.length > 0) {
    md += '## Interactive Debate\n\n';
    state.chatHistory.forEach((msg) => {
      md += `**${msg.role.toUpperCase()}**: ${msg.content}\n\n`;
    });
  }

  const blob = new Blob([md], { type: 'text/markdown' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `council_report_${Date.now()}.md`;
  a.click();
  URL.revokeObjectURL(url);
}
