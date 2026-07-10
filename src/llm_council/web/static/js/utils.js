// Rendering-safe helpers: escaping, sanitized markdown, toasts.

export function escapeHtml(value) {
  return String(value)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

if (window.marked) {
  window.marked.setOptions({ gfm: true, breaks: true });
}

export function sanitizeHtml(html) {
  if (window.DOMPurify) {
    return window.DOMPurify.sanitize(html, { USE_PROFILES: { html: true } });
  }
  return escapeHtml(html || '');
}

export function renderMarkdown(text) {
  if (!window.marked) return `<pre>${escapeHtml(text || '')}</pre>`;
  return sanitizeHtml(window.marked.parse(text || ''));
}

export function showToast(message) {
  let stack = document.getElementById('toastStack');
  if (!stack) {
    stack = document.createElement('div');
    stack.id = 'toastStack';
    stack.className = 'toast-stack';
    stack.setAttribute('role', 'alert');
    document.body.appendChild(stack);
  }
  const toast = document.createElement('div');
  toast.className = 'toast';
  toast.textContent = message || 'Something went wrong.';
  stack.appendChild(toast);
  setTimeout(() => toast.remove(), 6500);
}

export function renderLoadingState(panel, message) {
  panel.innerHTML = `
    <div class="run-skeleton">
      <div>${escapeHtml(message || 'Starting council run...')}</div>
      <div class="skeleton-line"></div>
      <div class="skeleton-line short"></div>
    </div>
  `;
}

// Client-side mirror of the server STANCE regex — display-only; the server's
// smart_phase_decision event remains the authority for gate decisions.
const STANCE_RE = /^\s*\**\s*STANCE\s*\**\s*:\s*\**\s*([A-Za-z]+)\s*\**(?:\s*\|\s*\**\s*CONFIDENCE\s*\**\s*:\s*\**\s*(\d{1,2})\s*\**)?(?:\s*\|\s*(.*))?$/gim;
const VERDICT_MAP = {
  PROCEED: 'PROCEED', GO: 'PROCEED', SHIP: 'PROCEED', APPROVE: 'PROCEED', YES: 'PROCEED',
  ACCEPT: 'PROCEED', SUPPORT: 'PROCEED', ENDORSE: 'PROCEED',
  HOLD: 'HOLD', STOP: 'HOLD', BLOCK: 'HOLD', WAIT: 'HOLD', NO: 'HOLD', REJECT: 'HOLD',
  OPPOSE: 'HOLD', DEFER: 'HOLD',
  MIXED: 'MIXED', SPLIT: 'MIXED', UNSURE: 'MIXED', NEUTRAL: 'MIXED', UNDECIDED: 'MIXED',
};

export function extractStanceClient(text) {
  const matches = [...(text || '').matchAll(STANCE_RE)];
  for (let i = matches.length - 1; i >= 0; i--) {
    const verdict = VERDICT_MAP[(matches[i][1] || '').toUpperCase()];
    if (verdict) {
      return {
        verdict,
        confidence: matches[i][2] ? parseInt(matches[i][2], 10) : null,
        summary: (matches[i][3] || '').trim(),
      };
    }
  }
  return null;
}
