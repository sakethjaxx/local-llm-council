// Shared mutable state for the council UI. One module owns it; everyone imports.

export const state = {
  councilConfig: {
    architect: { label: 'Lead Architect', model: 'ollama/qwen2.5:7b', color: '#4D6BFE', icon: 'A', persona: 'You are the Lead Architect. Focus on SOLID principles, design patterns, maintainability, and code structure. Favor pragmatic, local-first solutions and call out unnecessary complexity.' },
    security: { label: 'Security Auditor', model: 'ollama/gemma2:9b', color: '#FF4444', icon: 'S', persona: 'You are the Senior Security Auditor. Focus strictly on OWASP vulnerabilities, injection flaws, unsafe defaults, and exposure risk. Prefer defenses that work in local self-hosted deployments.' },
    perf: { label: 'Performance Eng', model: 'ollama/llama3.1:8b', color: '#00A76F', icon: 'P', persona: 'You are the Performance Engineer. Focus on algorithmic cost, memory pressure, context bloat, and latency. Optimize for hardware-constrained local inference.' },
    chairman: { label: 'Chairman', model: 'ollama/qwen2.5:7b', color: '#F5C842', icon: 'C', persona: 'You are the Chairman. Synthesize the council and make a final verdict. Prefer recommendations that preserve free, open-weight, local execution.' },
  },
  chatHistory: [],
  rawCardContents: {},
  thinkingCards: {},
  ph2Section: null,
  ph3Section: null,
  selectedFiles: [],
  demoCatalog: null,
  preflightState: null,
  installedModels: [],
  setupInstalledConfig: null,
  selectedModelProfile: null,
  tokenBudgetProfile: 'balanced',
  deepDebate: false,
  lastRunConfig: null,
  currentRunController: null,
  runStopped: false,
};

export const CLOUD_KEY_STORAGE_KEY = 'llmCouncilCloudKeys';

export const TOKEN_BUDGET_SUMMARIES = {
  economy: 'Economy profile: shorter answers for lower latency on smaller local models.',
  balanced: 'Balanced profile: standard council token caps.',
  performance: 'Performance profile: longer answers with higher latency and memory cost.',
};

export const MODEL_PROFILES = {
  turbo: {
    architect: 'ollama/qwen2.5:3b',
    security: 'ollama/gemma2:2b',
    perf: 'ollama/llama3.2:3b',
    chairman: 'ollama/qwen2.5:3b',
  },
  balanced: {
    architect: 'ollama/qwen2.5:7b',
    security: 'ollama/gemma2:9b',
    perf: 'ollama/llama3.1:8b',
    chairman: 'ollama/qwen2.5:7b',
  },
  quality: {
    architect: 'ollama/qwen2.5:14b',
    security: 'ollama/deepseek-r1:14b',
    perf: 'ollama/llama3.1:8b',
    chairman: 'ollama/qwen2.5:14b',
  },
};

export const LOCAL_MODEL_CHOICES = [
  'ollama/qwen2.5:3b',
  'ollama/qwen2.5:7b',
  'ollama/qwen2.5:14b',
  'ollama/qwen2.5:32b',
  'ollama/qwen2.5-coder:7b',
  'ollama/qwen2.5-coder:14b',
  'ollama/llama3.2:3b',
  'ollama/llama3.1:8b',
  'ollama/llama3.1:70b',
  'ollama/gemma2:2b',
  'ollama/gemma2:9b',
  'ollama/gemma3:4b',
  'ollama/mistral:7b',
  'ollama/deepseek-r1:8b',
  'ollama/deepseek-r1:14b',
  'ollama/deepseek-r1:32b',
  'ollama/llava:7b',
  'ollama/qwen2.5vl:7b',
  'ollama/minicpm-v:8b',
];

export function councilSeatIds() {
  return Object.keys(state.councilConfig).filter((id) => id !== 'chairman');
}

export function resetRunState() {
  state.rawCardContents = {};
  state.thinkingCards = {};
  state.chatHistory = [];
  state.ph2Section = null;
  state.ph3Section = null;
}
