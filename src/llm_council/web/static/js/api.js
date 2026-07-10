// Server communication: cloud key headers and SSE stream reading.

import { CLOUD_KEY_STORAGE_KEY, state } from './state.js?v=20260709-editable-names';

export function loadCloudKeys() {
  try {
    return JSON.parse(localStorage.getItem(CLOUD_KEY_STORAGE_KEY) || '{}');
  } catch (e) {
    console.error('Failed to parse stored cloud keys', e);
    return {};
  }
}

export function persistCloudKeys() {
  const keys = {
    openai: document.getElementById('keyOpenAI')?.value.trim() || '',
    anthropic: document.getElementById('keyAnthropic')?.value.trim() || '',
    gemini: document.getElementById('keyGemini')?.value.trim() || '',
    groq: document.getElementById('keyGroq')?.value.trim() || '',
  };
  localStorage.setItem(CLOUD_KEY_STORAGE_KEY, JSON.stringify(keys));
}

export function hydrateCloudKeys() {
  const keys = loadCloudKeys();
  document.getElementById('keyOpenAI').value = keys.openai || '';
  document.getElementById('keyAnthropic').value = keys.anthropic || '';
  document.getElementById('keyGemini').value = keys.gemini || '';
  document.getElementById('keyGroq').value = keys.groq || '';
}

export function clearCloudKeys() {
  localStorage.removeItem(CLOUD_KEY_STORAGE_KEY);
  hydrateCloudKeys();
}

export function cloudKeyHeaders() {
  const needsCloud = Object.values(state.councilConfig || {}).some((seat) => {
    const model = String(seat?.model || '').trim().toLowerCase();
    return model && !model.startsWith('ollama/');
  });
  if (!needsCloud) return {};

  const keys = loadCloudKeys();
  const headers = {};
  if (keys.openai) headers['X-OpenAI-API-Key'] = keys.openai;
  if (keys.anthropic) headers['X-Anthropic-API-Key'] = keys.anthropic;
  if (keys.gemini) headers['X-Gemini-API-Key'] = keys.gemini;
  if (keys.groq) headers['X-Groq-API-Key'] = keys.groq;
  return headers;
}

// Read an SSE body, invoking onEvent per parsed `data:` payload.
// Returns true when a `done` event was seen.
export async function readSseStream(response, onEvent) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let sawDone = false;

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop();
    for (const line of lines) {
      if (!line.startsWith('data: ')) continue;
      try {
        const ev = JSON.parse(line.slice(6));
        if (ev.type === 'done') sawDone = true;
        onEvent(ev);
      } catch {
        // ignore malformed keep-alives
      }
    }
  }
  return sawDone;
}
