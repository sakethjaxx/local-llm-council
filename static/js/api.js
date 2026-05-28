// ── SERVER API & STREAMING ENGINE MODULE ──

import { cloudKeyHeaders } from './state.js';

/**
 * Fetches the available demo presets and sample files.
 */
export async function fetchDemoCatalog() {
  const resp = await fetch('/config/presets');
  if (!resp.ok) throw new Error(`HTTP error ${resp.status}`);
  return resp.json();
}

/**
 * Checks model availability and active warnings.
 */
export async function checkPreflight(councilConfig, selectedFiles) {
  const resp = await fetch('/ollama/check', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      council_config: councilConfig,
      attachment_names: selectedFiles.map(file => file.name)
    })
  });
  if (!resp.ok) throw new Error(`HTTP error ${resp.status}`);
  return resp.json();
}

/**
 * Queries hardware profiling for resource tuning suggestions.
 */
export async function fetchHardwareSuggestion() {
  const resp = await fetch('/hardware/suggest');
  if (!resp.ok) throw new Error(`HTTP error ${resp.status}`);
  return resp.json();
}

/**
 * Fetches sample files content by filename.
 */
export async function fetchSampleFileBlob(filename) {
  const resp = await fetch(`/demo-samples/${filename}`);
  if (!resp.ok) throw new Error(`HTTP error ${resp.status}`);
  return resp.blob();
}

/**
 * Helper to process stream reader of SSE.
 */
async function readSSEStream(reader, onEvent, onError) {
  const decoder = new TextDecoder();
  let buffer = '';
  let sawDone = false;

  try {
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
            if (ev.type === 'done') sawDone = true;
            onEvent(ev);
          } catch (e) {
            console.error('Failed to parse SSE JSON', line, e);
          }
        }
      }
    }
  } catch (err) {
    if (onError) onError(err);
    throw err;
  }
  return sawDone;
}

/**
 * Streams Topic-based Council run.
 */
export async function streamCouncilRun({
  topic,
  councilConfig,
  tokenBudgetProfile,
  selectedFiles,
  dynamicSwarm,
  deepDebate,
  onEvent,
  onError
}) {
  const formData = new FormData();
  formData.append('topic_text', topic);
  formData.append('council_config', JSON.stringify(councilConfig));
  formData.append('token_budget_profile', tokenBudgetProfile);
  
  for (const file of selectedFiles) {
    formData.append('attachments', file);
  }
  if (dynamicSwarm) formData.append('dynamic_swarm', true);
  if (deepDebate) formData.append('deep_debate', true);

  const resp = await fetch('/council/stream', {
    method: 'POST',
    headers: cloudKeyHeaders(),
    body: formData
  });

  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.detail || err.message || `Request failed with status ${resp.status}`);
  }

  const reader = resp.body.getReader();
  return readSSEStream(reader, onEvent, onError);
}

/**
 * Streams Project Directory-based Council run review.
 */
export async function streamProjectReview({
  path,
  deepDebate,
  councilConfig,
  tokenBudgetProfile,
  onEvent,
  onError
}) {
  const resp = await fetch('/council/review-project', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...cloudKeyHeaders() },
    body: JSON.stringify({
      path,
      deep_debate: deepDebate,
      council_config: councilConfig,
      token_budget_profile: tokenBudgetProfile,
    }),
  });

  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.detail || err.message || `Request failed with status ${resp.status}`);
  }

  const reader = resp.body.getReader();
  return readSSEStream(reader, onEvent, onError);
}

/**
 * Streams interactive chat replies during debate mode.
 */
export async function streamDebateChat({
  targetId,
  chatHistory,
  councilConfig,
  tokenBudgetProfile,
  onToken,
  onError
}) {
  const resp = await fetch('/council/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...cloudKeyHeaders() },
    body: JSON.stringify({
      member_id: targetId,
      messages: chatHistory,
      council_config: councilConfig,
      token_budget_profile: tokenBudgetProfile
    })
  });

  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.detail || err.message || `Chat request failed with status ${resp.status}`);
  }

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  try {
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
            if (ev.type === 'chat_token') {
              onToken(ev.chunk);
            }
          } catch {}
        }
      }
    }
  } catch (err) {
    if (onError) onError(err);
    throw err;
  }
}
