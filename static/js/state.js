// ── GLOBAL APPLICATION STATE ──

export const state = {
  activeTab: 'text', // 'text' or 'project'
  councilConfig: {
    "architect": { 
      label: "Lead Architect", 
      model: "ollama/qwen2.5:7b", 
      color: "#4D6BFE", 
      icon: "🐋", 
      persona: "You are the Lead Architect. Focus on SOLID principles, design patterns, maintainability, and code structure. Favor pragmatic, local-first solutions and call out unnecessary complexity." 
    },
    "security": { 
      label: "Security Auditor", 
      model: "ollama/gemma2:9b", 
      color: "#FF4444", 
      icon: "🛡️", 
      persona: "You are the Senior Security Auditor. Focus strictly on OWASP vulnerabilities, injection flaws, unsafe defaults, and exposure risk. Prefer defenses that work in local self-hosted deployments." 
    },
    "perf": { 
      label: "Performance Eng", 
      model: "ollama/llama3.1:8b", 
      color: "#00FF00", 
      icon: "⚡", 
      persona: "You are the Performance Engineer. Focus on algorithmic cost, memory pressure, context bloat, and latency. Optimize for hardware-constrained local inference." 
    },
    "chairman": { 
      label: "Chairman", 
      model: "ollama/qwen2.5:7b", 
      color: "#F5C842", 
      icon: "👑", 
      persona: "You are the Chairman. Synthesize the council and make a final verdict. Prefer recommendations that preserve free, open-weight, local execution." 
    }
  },
  chatHistory: [],
  rawCardContents: {},
  thinkingCards: {},
  selectedFiles: [],
  demoCatalog: null,
  preflightState: null,
  tokenBudgetProfile: 'balanced',
  isAdvancedExpanded: false
};

// ── DESIGN TOKENS & METRIC CONFIGS ──

export const CLOUD_KEY_STORAGE_KEY = 'llmCouncilCloudKeys';

export const TOKEN_BUDGET_SUMMARIES = {
  economy: 'Economy profile: shorter answers for lower latency on smaller local models.',
  balanced: 'Balanced profile: standard council token caps.',
  performance: 'Performance profile: longer answers with higher latency and memory cost.'
};

export const MODEL_PROFILES = {
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

// ── STORAGE & CONFIG UTILITIES ──

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
    groq: document.getElementById('keyGroq')?.value.trim() || ''
  };
  localStorage.setItem(CLOUD_KEY_STORAGE_KEY, JSON.stringify(keys));
}

export function hydrateCloudKeys() {
  const keys = loadCloudKeys();
  const oai = document.getElementById('keyOpenAI');
  const ant = document.getElementById('keyAnthropic');
  const gem = document.getElementById('keyGemini');
  const grq = document.getElementById('keyGroq');
  
  if (oai) oai.value = keys.openai || '';
  if (ant) ant.value = keys.anthropic || '';
  if (gem) gem.value = keys.gemini || '';
  if (grq) grq.value = keys.groq || '';
}

export function clearCloudKeys() {
  localStorage.removeItem(CLOUD_KEY_STORAGE_KEY);
  hydrateCloudKeys();
}

export function cloudKeyHeaders() {
  const keys = loadCloudKeys();
  const headers = {};
  if (keys.openai) headers['X-OpenAI-API-Key'] = keys.openai;
  if (keys.anthropic) headers['X-Anthropic-API-Key'] = keys.anthropic;
  if (keys.gemini) headers['X-Gemini-API-Key'] = keys.gemini;
  if (keys.groq) headers['X-Groq-API-Key'] = keys.groq;
  return headers;
}

export function configFromPreset(preset) {
  if (preset.config) return JSON.parse(JSON.stringify(preset.config));
  const seats = preset.seats || [];
  const keys = ['architect', 'security', 'perf'];
  const config = {};
  seats.slice(0, 3).forEach((seat, index) => {
    config[keys[index]] = {
      label: seat.label || `Seat ${index + 1}`,
      model: seat.model,
      color: seat.color || ['#4D6BFE', '#FF4444', '#00A76F'][index],
      icon: seat.icon || ['◆', '◇', '○'][index],
      persona: seat.persona || ''
    };
  });
  config.chairman = {
    label: 'Chairman',
    model: preset.chairman_model || 'ollama/qwen2.5:7b',
    color: '#F5C842',
    icon: '👑',
    persona: preset.chairman_persona || 'You are the Chairman. Synthesize the council into a decisive summary with concrete next steps.'
  };
  return config;
}
