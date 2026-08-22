// ── UTIL ──
function cssVar(name, fallback) {
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback;
}

function prefersReducedMotion() {
  return window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

function scrollWithMotion(element, block = 'nearest') {
  element?.scrollIntoView({ behavior: prefersReducedMotion() ? 'auto' : 'smooth', block });
}

// ── STATE ──
let councilConfig = {
  "architect": { label: "Lead Architect", model: "ollama/qwen2.5:7b", color: "#0071E3", icon: "A", persona: "You are the Lead Architect. Focus on SOLID principles, design patterns, maintainability, and code structure. Favor pragmatic, local-first solutions and call out unnecessary complexity." },
  "security": { label: "Security Auditor", model: "ollama/gemma2:9b", color: "#D70015", icon: "S", persona: "You are the Senior Security Auditor. Focus strictly on OWASP vulnerabilities, injection flaws, unsafe defaults, and exposure risk. Prefer defenses that work in local self-hosted deployments." },
  "perf": { label: "Performance Eng", model: "ollama/llama3.1:8b", color: "#248A3D", icon: "P", persona: "You are the Performance Engineer. Focus on algorithmic cost, memory pressure, context bloat, and latency. Optimize for hardware-constrained local inference." },
  "chairman": { label: "Chairman", model: "ollama/qwen2.5:7b", color: "#5856D6", icon: "C", persona: "You are the Chairman. Synthesize the council and make a final verdict. Prefer recommendations that preserve free, open-weight, local execution." }
};

let chatHistory = [];
let rawCardContents = {};
let thinkingCards = {};
let ph2Section, ph3Section;
let selectedFiles = [];
let demoCatalog = null;
let preflightState = null;
const CLOUD_KEY_STORAGE_KEY = 'llmCouncilCloudKeys';
const THEME_STORAGE_KEY = 'llmCouncilTheme';
let tokenBudgetProfile = 'balanced';

const TOKEN_BUDGET_SUMMARIES = {
  economy: 'Economy profile: shorter answers for lower latency on smaller local models.',
  balanced: 'Balanced profile: standard council token caps.',
  performance: 'Performance profile: longer answers with higher latency and memory cost.',
  quality: 'Quality profile: ample analysis and synthesis space; expect slower local runs.'
};

const MODEL_PROFILES = {
  turbo: {
    architect: "ollama/qwen2.5:3b",
    security: "ollama/gemma2:2b",
    perf: "ollama/llama3.2:3b",
    chairman: "ollama/qwen2.5:3b"
  },
  balanced: {
    architect: "ollama/qwen2.5:7b",
    security: "ollama/gemma2:9b",
    perf: "ollama/llama3.1:8b",
    chairman: "ollama/qwen2.5:7b"
  },
  quality: {
    architect: "ollama/qwen2.5:14b",
    security: "ollama/deepseek-r1:14b",
    perf: "ollama/llama3.1:8b",
    chairman: "ollama/qwen2.5:14b"
  }
};

function escapeHtml(value) {
  return String(value || '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

if (window.marked) {
  marked.setOptions({ gfm: true, breaks: true });
}

function sanitizeHtml(html) {
  if (window.DOMPurify) {
    return DOMPurify.sanitize(html, { USE_PROFILES: { html: true } });
  }
  return escapeHtml(html || '');
}

function renderMarkdown(text) {
  return sanitizeHtml(window.marked ? marked.parse(text || '') : escapeHtml(text || ''));
}

function resetSession() {
  selectedFiles = [];
  rawCardContents = {};
  thinkingCards = {};
  chatHistory = [];
  ph2Section = null;
  ph3Section = null;

  const topicInput = document.getElementById('topicText');
  const projectInput = document.getElementById('projectPathInput');
  const scanInfo = document.getElementById('projectScanInfo');
  const presetSelect = document.getElementById('presetSelect');
  const presetDesc = document.getElementById('presetDesc');

  if (topicInput) topicInput.value = '';
  if (projectInput) projectInput.value = '';
  if (scanInfo) scanInfo.textContent = '';
  if (presetSelect) presetSelect.value = '';
  if (presetDesc) presetDesc.textContent = 'Choose a preset to set models, starter topic text, and sample files.';
  
  if (typeof renderSelectedFiles === 'function') renderSelectedFiles();
  
  const panel = document.getElementById('councilPanel');
  if (panel) {
    panel.innerHTML = `
      <div class="panel-empty">
        <div class="empty-material">
          <div class="empty-eyebrow">Ready</div>
          <div class="empty-title">Choose context, then run the council.</div>
          <div class="helper-copy">Start from a preset, attach files, or scan a local project. Output streams here phase by phase.</div>
          <div class="empty-steps" aria-label="Council run phases">
            <span>Analyze</span>
            <span>Review</span>
            <span>Synthesize</span>
          </div>
          <div class="helper-copy hardware-reason" id="hardwareReason"></div>
        </div>
      </div>
    `;
  }

  const btn = document.getElementById('launchBtn');
  if (btn) {
    btn.disabled = false;
    btn.innerHTML = 'Run council';
  }

  showToast('Session reset cleanly.');
}

function toggleTheme() {
  const toggle = document.getElementById('themeToggle');
  const isDark = toggle ? toggle.checked : (document.body.getAttribute('data-theme') !== 'dark');

  if (isDark) {
    document.body.setAttribute('data-theme', 'dark');
    localStorage.setItem(THEME_STORAGE_KEY, 'dark');
  } else {
    document.body.removeAttribute('data-theme');
    localStorage.setItem(THEME_STORAGE_KEY, 'light');
  }
}

function initTheme() {
  const saved = localStorage.getItem(THEME_STORAGE_KEY);
  const prefersDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
  const shouldBeDark = saved === 'dark' || (!saved && prefersDark);

  if (shouldBeDark) {
    document.body.setAttribute('data-theme', 'dark');
  } else {
    document.body.removeAttribute('data-theme');
  }

  const toggle = document.getElementById('themeToggle');
  if (toggle) {
    toggle.checked = shouldBeDark;
  }
}

function showToast(message) {
  let stack = document.getElementById('toastStack');
  if (!stack) {
    stack = document.createElement('div');
    stack.id = 'toastStack';
    stack.className = 'toast-stack';
    document.body.appendChild(stack);
  }
  const toast = document.createElement('div');
  toast.className = 'toast';
  toast.textContent = message || 'Something went wrong.';
  stack.appendChild(toast);
  setTimeout(() => toast.remove(), 5500);
}

function renderLoadingState(panel, message) {
  panel.innerHTML = `
    <div class="run-skeleton">
      <div class="empty-material">
        <div class="empty-eyebrow">Running</div>
        <div class="empty-title">${escapeHtml(message || 'Starting council run...')}</div>
        <div class="helper-copy">Streaming will begin as soon as the first model starts producing tokens.</div>
        <div class="skeleton-line"></div>
        <div class="skeleton-line short"></div>
      </div>
    </div>
  `;
}

function renderErrorState(panel, message) {
  panel.innerHTML = `
    <div class="status-card">
      <div class="preset-title status-bad">Run failed</div>
      <div class="status-line status-bad">${escapeHtml(message || 'Unknown error')}</div>
    </div>
  `;
}

function loadCloudKeys() {
  try {
    return JSON.parse(localStorage.getItem(CLOUD_KEY_STORAGE_KEY) || '{}');
  } catch (e) {
    return {};
  }
}

function persistCloudKeys() {
  const keys = {
    openai: document.getElementById('keyOpenAI')?.value.trim() || '',
    anthropic: document.getElementById('keyAnthropic')?.value.trim() || '',
    gemini: document.getElementById('keyGemini')?.value.trim() || '',
    groq: document.getElementById('keyGroq')?.value.trim() || ''
  };
  localStorage.setItem(CLOUD_KEY_STORAGE_KEY, JSON.stringify(keys));
}

function hydrateCloudKeys() {
  const keys = loadCloudKeys();
  if (document.getElementById('keyOpenAI')) document.getElementById('keyOpenAI').value = keys.openai || '';
  if (document.getElementById('keyAnthropic')) document.getElementById('keyAnthropic').value = keys.anthropic || '';
  if (document.getElementById('keyGemini')) document.getElementById('keyGemini').value = keys.gemini || '';
  if (document.getElementById('keyGroq')) document.getElementById('keyGroq').value = keys.groq || '';
}

function clearCloudKeys() {
  localStorage.removeItem(CLOUD_KEY_STORAGE_KEY);
  hydrateCloudKeys();
  showToast('Cloud API keys cleared.');
}

function setTokenBudgetProfile(profile) {
  tokenBudgetProfile = ['economy', 'balanced', 'performance', 'quality'].includes(profile) ? profile : 'balanced';
  const summary = document.getElementById('tokenBudgetSummary');
  if (summary) {
    summary.textContent = TOKEN_BUDGET_SUMMARIES[tokenBudgetProfile];
  }
}

function cloudKeyHeaders() {
  const keys = loadCloudKeys();
  const headers = {};
  if (keys.openai) headers['X-OpenAI-API-Key'] = keys.openai;
  if (keys.anthropic) headers['X-Anthropic-API-Key'] = keys.anthropic;
  if (keys.gemini) headers['X-Gemini-API-Key'] = keys.gemini;
  if (keys.groq) headers['X-Groq-API-Key'] = keys.groq;
  return headers;
}
