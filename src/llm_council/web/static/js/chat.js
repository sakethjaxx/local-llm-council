// Interactive debate mode: direct chat with a council member after a run.

import { state } from './state.js?v=20260709-editable-names';
import { escapeHtml, renderMarkdown } from './utils.js';
import { cloudKeyHeaders } from './api.js';

export function showDebatePanel(panel) {
  const wrapper = document.createElement('div');
  wrapper.innerHTML = `
    <div class="debate-panel" style="display:block">
      <div class="debate-header">
        <span>Interactive debate</span>
        <button class="btn btn-small btn-solid" data-action="export-report">Export report</button>
      </div>
      <div class="chat-history" id="chatHistory" aria-live="polite"></div>
      <div class="chat-input-row">
        <label class="visually-hidden" for="chatTarget">Choose a council member</label>
        <select id="chatTarget" class="chat-select">
          ${Object.entries(state.councilConfig)
            .map(([id, cfg]) => `<option value="${escapeHtml(id)}">@${escapeHtml(cfg.label || id)}</option>`)
            .join('')}
        </select>
        <label class="visually-hidden" for="chatInput">Your question</label>
        <input type="text" id="chatInput" placeholder="Ask a question..." data-enter-action="send-chat">
        <button class="btn btn-solid" data-action="send-chat" id="chatBtn">Send</button>
      </div>
    </div>
  `;
  panel.appendChild(wrapper);
  wrapper.scrollIntoView({ behavior: 'smooth', block: 'end' });
}

export async function sendChat() {
  const input = document.getElementById('chatInput');
  const targetId = document.getElementById('chatTarget').value;
  const msg = input.value.trim();
  if (!msg) return;

  const historyDiv = document.getElementById('chatHistory');

  state.chatHistory.push({ role: 'user', content: msg });
  const uMsg = document.createElement('div');
  uMsg.className = 'chat-msg chat-user';
  uMsg.textContent = msg;
  historyDiv.appendChild(uMsg);
  input.value = '';

  const aMsg = document.createElement('div');
  aMsg.className = 'chat-msg chat-agent';
  aMsg.innerHTML = '<div class="typing"><span></span><span></span><span></span></div>';
  historyDiv.appendChild(aMsg);
  historyDiv.scrollTop = historyDiv.scrollHeight;

  document.getElementById('chatBtn').disabled = true;

  try {
    const resp = await fetch('/council/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...cloudKeyHeaders() },
      body: JSON.stringify({
        member_id: targetId,
        messages: state.chatHistory,
        council_config: state.councilConfig,
        token_budget_profile: state.tokenBudgetProfile,
      }),
    });

    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let fullReply = '';
    aMsg.innerHTML = '';

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
          if (ev.type === 'chat_token') {
            fullReply += ev.chunk;
            aMsg.innerHTML = renderMarkdown(fullReply);
            historyDiv.scrollTop = historyDiv.scrollHeight;
          }
        } catch {}
      }
    }
    state.chatHistory.push({ role: 'assistant', content: fullReply });
  } catch (err) {
    aMsg.innerHTML = `<span style="color:var(--danger)">Error: ${escapeHtml(err.message)}</span>`;
  }
  document.getElementById('chatBtn').disabled = false;
}
