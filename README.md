# 🏛️ LLM Council

<div align="center">

![Python](https://img.shields.io/badge/python-3.11%2B-blue?style=for-the-badge&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.141-009688?style=for-the-badge&logo=fastapi&logoColor=white)
![Ollama](https://img.shields.io/badge/Ollama-Local--First-black?style=for-the-badge&logo=ollama&logoColor=white)
![Tests](https://img.shields.io/badge/tests-180%20passed-success?style=for-the-badge)
![License](https://img.shields.io/badge/license-MIT-green?style=for-the-badge)

**A hardware-aware, local-first multi-model review and decision engine for consumer machines.**

*Run multi-agent debates locally in Ollama without VRAM thrashing, context truncation, or cloud lock-in.*

[Quick Start](#-quick-start-in-60-seconds) • [Killer USPs](#-the-4-killer-usps) • [Architecture](#-system-architecture) • [CLI & Pre-Commit Hook](#-cli--git-pre-commit-hook) • [Configuration](#-configuration-env)

</div>

---

## ⚡ Why LLM Council?

Most multi-agent frameworks (CrewAI, AutoGen, LangGraph) make a fatal assumption: **infinite cloud API credits or an enterprise GPU cluster**.

When you try running multi-model debates on a 16GB consumer laptop using Ollama:
- ❌ **The VRAM Thrash Death Spiral:** Loading 3–4 distinct 8B models concurrently causes Ollama to constantly evict and swap weights between RAM and disk, freezing your machine.
- ❌ **The "Tail-Drop" Context Bias:** Naive frameworks concatenate peer reviews and slice `text[:max_tokens]`, systematically truncating the last agents' critique.
- ❌ **Structural Consensus Blindness:** Multi-agent reviews using boilerplate Markdown headers falsely trigger consensus gates because 40% of their tokens are identical formatting.

**LLM Council solves the real systems-engineering challenges of local multi-agent inference.**

---

## 🎯 The 4 Killer USPs

### 1. ⚡ Zero-Thrash Hardware Fitting
Auto-detects your system RAM and available VRAM.
- On **16GB machines**, it keeps a single resident model (e.g. `qwen2.5:7b`) and enforces **persona sampling distributions** (`T=0.15` to `0.35`, `top_p=0.80` to `0.95`) to prevent homogenous groupthink.
- On **24GB+ machines**, it unlocks true multi-model specialist councils (e.g., Qwen + Gemma + Llama) with strict concurrency semaphores.

### 2. 🛡️ Native Git Pre-Commit Hook & Blast Radius
Run `python src/council/cli.py check_diff` before every commit. The council analyzes your Git diff, traverses your project's dependency DAG, warns about broken downstream imports, and blocks commits with critical security flaws (`risk_score >= 8`).

### 3. ⚖️ Fair-Share Token Allocation & Smart Consensus
- **Fair-Share Slicing:** Binary-searches peer analyses into equal context allocations so every council seat receives equal deliberation weight.
- **Negation-Aware Consensus:** Strips Markdown headers and runs stance-negation regexes. If the council unanimously agrees on Phase 1, Phase 2 debate is bypassed—cutting latency by 50% while guaranteeing dissenters are never silenced.

### 4. 🧠 Continuous SQLite Knowledge Graph & Skill Registry
Extracts knowledge triples `(Subject -> Predicate -> Object)` with temporal decay ($0.99^{\text{days}}$) and stores reusable analysis patterns. Your council gets smarter with every architectural decision you make.

---

## 🚀 Quick Start in 60 Seconds

### 1. Clone & Setup
```bash
git clone https://github.com/sakethjaxx/local-llm-council.git
cd local-llm-council
python -m venv venv && source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp env.example .env
```

### 2. Pull Your Default Model
```bash
ollama pull qwen2.5:7b
```

### 3. Launch Server & Web UI
```bash
python run.py
```
Open **`http://localhost:8765`** in your browser.

---

## 💻 CLI & Git Pre-Commit Hook

LLM Council provides a rich CLI for automated checks, terminal prompts, and repository reviews:

```bash
# 1. Ask a question or run an architecture deliberation
python src/council/cli.py ask "Should we migrate from Postgres to SQLite WAL for this service?"

# 2. Review a file or directory with AST dependency graph
python src/council/cli.py review ./src/council/orchestrator.py

# 3. View recent council deliberation history
python src/council/cli.py history

# 4. View detected hardware profile and suggested model roster
python src/council/cli.py models

# 5. Pre-commit check on staged changes
python src/council/cli.py check_diff

# Or install as a native git pre-commit hook:
echo "python src/council/cli.py check_diff" > .git/hooks/pre-commit
chmod +x .git/hooks/pre-commit
```

### What Happens on `git commit`:
```
$ git commit -m "refactor: update auth middleware"
[INFO] Precommit review started...
[INFO] Architectural Blast Radius: 4 downstream routes depend on auth.py
[SECURITY] Scanning for OWASP vulnerabilities...
[CHAIRMAN] Verdict: APPROVE (Risk Score: 2/10)
Commit accepted.
```

---

## 🏛️ System Architecture

```
                       User Input / Code Files / Git Diff / Project Scan
                                              │
                                              ▼
                    ┌───────────────────────────────────────────────────┐
                    │ 1. Context Prep & Continuous Memory Injection     │
                    │    • Ingest documents & parse multi-language code │
                    │    • Match SQLite knowledge graph triples         │
                    │    • Inject relevant domain analysis skills       │
                    └─────────────────────────┬─────────────────────────┘
                                              │
                                              ▼
                    ┌───────────────────────────────────────────────────┐
                    │ 2. Phase 1 — Independent Parallel Analysis        │
                    │    • Architect (T=0.25) | Security (T=0.15) | ... │
                    │    • Gated concurrency (Semaphore=2)              │
                    │    • Fair-share context window allocation         │
                    └─────────────────────────┬─────────────────────────┘
                                              │
                                  [Smart Consensus Gate]
                                 /                      \
                      (Unanimous Agreement)       (Dissent / Contradiction)
                               │                                │
                               │               ┌────────────────┴───────────────┐
                               │               │ 3. Phase 2 — Dialectic Review  │
                               │               │    • Peer critique & disputes  │
                               │               └────────────────┬───────────────┘
                               │                                │
                               └───────────────┬────────────────┘
                                               │
                                               ▼
                    ┌───────────────────────────────────────────────────┐
                    │ 4. Phase 3 — Chairman Synthesis & Decision        │
                    │    • Optional live DuckDuckGo dispute verification│
                    │    • Multi-tier JSON parsing (Strict->Repair->AST)│
                    │    • Concrete Action Items + 0-10 Risk Score      │
                    └─────────────────────────┬─────────────────────────┘
                                              │
                                              ▼
                    ┌───────────────────────────────────────────────────┐
                    │ 5. Post-Run Learning (Cooperative Background)     │
                    │    • Knowledge Triple extraction                  │
                    │    • Skill confidence reinforcement               │
                    └───────────────────────────────────────────────────┘
```

---

## ⚙️ Configuration (`.env`)

| Variable | Default | Description |
| :--- | :---: | :--- |
| `COUNCIL_HOST` | `127.0.0.1` | Server host binding. Local-only by default. |
| `COUNCIL_PORT` | `8765` | FastAPI server port. |
| `COUNCIL_API_KEY` | `""` | Optional API key required when binding to `0.0.0.0` or VPS. |
| `COUNCIL_MAX_PARALLEL_MEMBERS` | `2` | Max concurrent Ollama inference calls to prevent VRAM thrashing. |
| `COUNCIL_LLM_TIMEOUT` | `300` | Hard wall-clock timeout in seconds for slow local hardware. |
| `COUNCIL_ENABLE_WEB_SEARCH` | `false` | Enable DuckDuckGo web search to fact-check council disputes. |
| `COUNCIL_MAX_UPLOAD_MB` | `20` | Maximum file attachment size in MB. |

*(Optional cloud API keys for OpenAI, Anthropic, Gemini, or Groq can be configured in `.env` or directly in the Web UI via headers).*

---

## 🧪 Testing & Evaluation

### Run Test Suite (165 Tests)
```bash
pytest tests/ -v
```

### Run Multi-Criteria Evaluation Benchmark
```bash
python tests/eval/run_eval.py --all
```
Evaluates council decisions against golden benchmark topics using composite scoring ($0.40 \times \text{SemanticSimilarity} + 0.60 \times \text{ConceptAssertions}$).

---

## 📂 Project Structure

```
local-llm-council/
├── run.py                     # Single-command application entrypoint
├── pyproject.toml             # Package metadata and CLI registrations
├── requirements.txt           # Production dependencies
├── src/council/
│   ├── main.py                # FastAPI app, SSE routes, lifecycle hooks
│   ├── orchestrator.py        # 3-Phase deliberation engine & token balancer
│   ├── smart_phase.py         # Negation-aware consensus gate
│   ├── hardware_detect.py     # Hardware tier modeling & sampling presets
│   ├── ollama_manager.py      # Ollama stream puller & process supervisor
│   ├── project_graph.py       # Native code DAG & dependency analyzer
│   ├── blast_radius.py        # Reverse dependency impact engine
│   ├── cli.py                 # Git pre-commit CLI tool
│   ├── memory_store.py        # SQLite triple store with temporal decay
│   ├── skill_registry.py      # Extracted reusable skills
│   ├── io_parser.py           # Multi-language code & document parser
│   └── static/                # Web UI (Vanilla JS, CSS, HTML)
└── tests/                     # 165 unit & integration tests
```

---

## 📜 License

MIT License. Designed for privacy, local open weights, and self-hosted control.
