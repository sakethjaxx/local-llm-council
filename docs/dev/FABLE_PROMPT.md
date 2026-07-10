# LLM Council: Gap-Fix & Production Implementation Prompt for Fable

**Status:** Ready for Fable agent execution  
**Token Budget:** Aggressive (minimize Sonnet sub-agents)  
**Deadline:** Single session completion  
**Acceptance:** Identify gaps → Fix gaps → 4-command setup → working council in <5 min

---

## Mission Statement

Deliver a **simple, bulletproof local LLM council** that:
- ✅ **Works first.** All broken pieces fixed. No cryptic errors.
- ✅ **Simple setup.** 1-2 commands max. No venv nonsense.
- ✅ **Zero friction.** Ollama auto-detected. Models auto-pulled. Errors are helpful.
- ✅ **Works locally.** Default path: Ollama (zero cost). Cloud optional.
- ✅ **Actually streams.** Real-time UI updates. See the council think live.
- ✅ **Usable from day 1.** Demo councils. Clear docs. No "advanced setup" needed.

**Core Principle:** **Simplicity > Features.** If it complicates the user path, cut it. Every gap must be fixed with the simplest, most robust solution.

---

## PHASE 0: Gap Identification & Prioritization (Read & Audit First)

**DO NOT START CODING YET.** Read the codebase. Find the actual problems.

### Read These Files (Parallel, No Sub-Agents):

1. **`orchestrator.py`**
   - Q: Are Phase 1, Phase 1.5 (smart_phase), Phase 2, Phase 3 all **implemented & working**?
   - Q: Does streaming actually work end-to-end?
   - Q: Error handling for LLM timeouts, Ollama down, etc.?

2. **`main.py`**
   - Q: Does `/api/run` POST endpoint exist & validate input?
   - Q: Does `/api/run/<id>/events` SSE work?
   - Q: Are all required endpoints present? (`/config`, `/metrics`, `/presets`)
   - Q: Error responses (400, 404, 500) clear & helpful?

3. **`static/index.html`**
   - Q: Does UI connect to API on load?
   - Q: Does it render SSE events live?
   - Q: Can user submit a topic & see results?
   - Q: Error states handled (red banner, helpful message)?

4. **`router_agent.py`**
   - Q: Does dynamic roster generation work?
   - Q: Fallback if Ollama unavailable?

5. **`run_store.py`**
   - Q: SQLite connection working? WAL mode enabled?
   - Q: CRUD operations for runs & phases?

6. **`requirements.txt`**
   - Q: All versions pinned? Missing deps?
   - Q: Is `python-dotenv` included?

7. **`tests/`**
   - Q: How many tests exist? All passing?
   - Q: Coverage on core (orchestrator, main endpoints)?

### Document Findings:

Create a **GAP REPORT** (in your mind or as comments):
```
GAPS FOUND:
1. [Gap Name] - Impact: [High/Med/Low] - Fix: [Best solution]
2. [Gap Name] - Impact: [High/Med/Low] - Fix: [Best solution]
...
PRIORITY ORDER:
- High impact gaps first
- Then medium
- Low = defer or skip
```

**Example gaps that likely exist:**
- ❌ `main.py` POST `/api/run` might not validate roster or topic
- ❌ SSE streaming might not include heartbeats (timeout after 30s)
- ❌ UI might not handle errors gracefully
- ❌ No `start.sh` / `start.ps1` scripts
- ❌ `requirements.txt` might have unpinned versions
- ❌ No `.env.example` file
- ❌ Demo personas not pre-built
- ❌ Ollama connection errors not caught with helpful messages
- ❌ Tests might not cover Phase 2 & 3
- ❌ No metrics endpoint

**Fix these gaps in order of user impact (highest first).** Don't skip, don't defer.

---

## Ease-of-Use Principles (Apply to Every Fix)

**Before shipping ANY code, ask:**
- ❓ **Can the user do this in 1 step instead of 5?** (If yes, do it)
- ❓ **Will a non-technical person understand the error?** (If no, rewrite it)
- ❓ **Does this require reading docs?** (If yes, automate it)
- ❓ **Is there a default that works 90% of the time?** (If yes, use it)
- ❓ **Can we detect & fix the problem automatically?** (If yes, do it)

**Examples:**
- ❌ "ConnectionError: Cannot connect to localhost:11434" 
- ✅ "Ollama not running. Start it: `ollama serve` or `docker run -d ollama/ollama:latest`"

- ❌ Manual venv setup
- ✅ Auto-detect Python, create venv if missing, source it

- ❌ "Set OLLAMA_BASE_URL in .env"
- ✅ Try localhost:11434 by default, fall back to .env if set

- ❌ UI hangs with no feedback
- ✅ Progress bar, member status cards, clear "thinking..." states

---

## Gap-Fixing Strategy

**When you find a gap:**

1. **Identify root cause.** (Not just the symptom)
   - Is it missing code? Wrong logic? Poor error handling? UX problem?

2. **Pick the simplest fix.** (Not the smartest)
   - Example: Instead of detecting Ollama availability via HTTP, just try the first request and catch the error. Simpler.

3. **Add helpful error message.** (Not a stack trace)
   - Include: "What went wrong", "Why it happened", "How to fix it"

4. **Test the fix.** (Manually or via pytest)
   - Break it on purpose to see if error message appears
   - Fix it to see success path

5. **Document if needed.** (Only if not obvious)
   - If user might hit this, add to TROUBLESHOOTING.md

**Example Gap Fix Workflow:**

**Gap:** SSE streaming stops after 30 seconds with no message
- **Root cause:** No heartbeat in SSE stream; client times out
- **Simplest fix:** Add `:\n\n` (comment) every 20 seconds
- **Error handling:** If orchestrator stalls, send `event: error` with message
- **Test:** Submit topic → watch SSE stream → verify heartbeats + completion
- **Doc:** Add to TROUBLESHOOTING: "Stream stopped? Check Ollama/API logs."

---

## CRITICAL FIRST STEP: Audit & Test the Actual Code

**BEFORE FIXING ANYTHING:** Run the project and document actual gaps.

```bash
# Step 1: Can it start?
cd C:\Projects\local-llm-council
python main.py

# Step 2: Watch for startup messages
# - Does it try to connect to Ollama?
# - Does it give a helpful error if Ollama is down?
# - Any import errors? Missing deps?

# Step 3: Test the UI
# Open http://localhost:8000 in browser
# - Does it load? Blank page? JS errors in console?
# - Can you type in the topic field?
# - Can you submit? Does it error? Is the error helpful?

# Step 4: Check test baseline
pytest tests/ -v --tb=short

# Step 5: Test an actual run (if API works)
curl -X POST http://localhost:8000/api/run \
  -H "Content-Type: application/json" \
  -d '{"topic": "test", "roster": []}'
# Does it return run_id? Does it accept empty roster? Error message clear?
```

**Create a GAP REPORT with actual findings:**

```
GAPS FOUND (Actual Issues):
1. [Gap Name] - Impact: [CRITICAL/HIGH/MEDIUM/LOW]
   Root cause: [Why]
   User sees: [What error/problem]
   Fix: [Simplest solution]

2. [Gap Name] - ...

3. ...

PRIORITY ORDER:
CRITICAL: [List gaps that break the app]
HIGH: [List gaps users hit immediately]
MEDIUM: [List gaps that cause friction]
LOW: [List nice-to-haves]
```

---

## Gap-Fix Priority Matrix

**Process gaps in this order:**

| Priority | Definition | Examples | Time Budget | Action |
|----------|-----------|----------|-------------|--------|
| 🔴 **CRITICAL** | App won't start or core functionality broken | API won't POST, SSE crashes, tests fail, import errors | 30-60 min | Fix NOW. These block everything. |
| 🟠 **HIGH** | User hits it in first 5 minutes | Bad error message, UI won't load, Ollama error cryptic | 60-120 min | Fix next. Users leave if they can't start. |
| 🟡 **MEDIUM** | Friction but workaroundable | No start.sh script, requires manual venv, missing .env.example | 60-90 min | Fix if time allows. Makes UX better. |
| 🟢 **LOW** | Nice to have, not blocking | Add presets, polish UI, add metrics, optimize latency | 120+ min | Skip if time-constrained. v2 material. |

**RULE:** Only move to next priority after current priority is 100% done.

---

## Gap-Fix Template (For Each Gap)

Use this format for every gap:

```
GAP: [Name]
PRIORITY: [CRITICAL/HIGH/MEDIUM/LOW]
ROOT CAUSE: [Why it's broken]
USER SEES: [What error/behavior]
SIMPLEST FIX: [1-2 sentence solution, not the smartest, the simplest]
FILES TO EDIT: [What to change]
CODE CHANGE: [Exact edit or new file]
TEST: [How to verify it's fixed + manual test]
ERROR MESSAGE: [What user sees if this breaks again]
DOCUMENTATION: [Any TROUBLESHOOTING note or README update]
```

---

## Work Breakdown: Gap-Fix + Core Deliverables

### 1️⃣ Deployment Scripts (30 min, no sub-agents)

**Goal:** User clones repo → runs ONE script → council ready

**Deliverables:**

- **`start.sh`** (Linux/macOS):
  ```bash
  #!/bin/bash
  set -e
  echo "🚀 Starting Local LLM Council..."
  
  if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3.12+ required. https://www.python.org/downloads/"
    exit 1
  fi
  
  if [ ! -d "venv" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv venv
  fi
  
  source venv/bin/activate
  echo "📥 Installing dependencies..."
  pip install -q -r requirements.txt
  
  echo "✅ Setup complete!"
  echo "🌐 Starting server on http://localhost:8000"
  python main.py
  ```

- **`start.ps1`** (Windows PowerShell):
  ```powershell
  Write-Host "🚀 Starting Local LLM Council..." -ForegroundColor Green
  
  if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Host "❌ Python 3.12+ required. https://www.python.org/downloads/" -ForegroundColor Red
    exit 1
  }
  
  if (-not (Test-Path "venv")) {
    Write-Host "📦 Creating virtual environment..." -ForegroundColor Yellow
    python -m venv venv
  }
  
  & "venv\Scripts\Activate.ps1"
  Write-Host "📥 Installing dependencies..." -ForegroundColor Yellow
  pip install -q -r requirements.txt
  
  Write-Host "✅ Setup complete!" -ForegroundColor Green
  Write-Host "🌐 Starting server on http://localhost:8000" -ForegroundColor Cyan
  python main.py
  ```

- **Test locally:** Run both scripts, verify `http://localhost:8000` loads

---

### 2️⃣ Docker Containerization (30 min, no sub-agents)

**Goal:** Deploy anywhere with `docker-compose up`

**Deliverables:**

- **`Dockerfile`**:
  ```dockerfile
  FROM python:3.13-slim
  
  WORKDIR /app
  
  COPY requirements.txt .
  RUN pip install --no-cache-dir -r requirements.txt
  
  COPY . .
  
  ENV PYTHONUNBUFFERED=1
  EXPOSE 8000
  
  CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
  ```

- **`docker-compose.yml`** (dev + prod variants):
  ```yaml
  version: '3.8'
  services:
    api:
      build: .
      ports:
        - "8000:8000"
      environment:
        OLLAMA_BASE_URL: http://ollama:11434
        COUNCIL_CORS_ORIGINS: "*"
      depends_on:
        - ollama
    
    ollama:
      image: ollama/ollama:latest
      ports:
        - "11434:11434"
      volumes:
        - ollama_data:/root/.ollama
      environment:
        OLLAMA_HOST: 0.0.0.0:11434
  
  volumes:
    ollama_data:
  ```

- **Test:** `docker-compose up` → API responds → Ollama reachable

---

### 3️⃣ Requirements & Dependency Cleanup (20 min, no sub-agents)

**Goal:** Minimal, pinned, production-safe deps

**Deliverables:**

- **Audit `requirements.txt`:**
  - Pin ALL versions (no `>=` ranges)
  - Remove unused packages
  - Ensure: fastapi, uvicorn, litellm, ollama, pydantic, sqlalchemy, python-dotenv
  - Add: gunicorn (optional, prod-grade)
  - Add: pytest, black, mypy (dev extras if using pyproject.toml)

- **Create `requirements-dev.txt`:**
  ```
  -r requirements.txt
  pytest>=7.4
  black>=23.7
  flake8>=6.0
  mypy>=1.5
  ```

- **Test:** `pip install -r requirements.txt` succeeds, `main.py` starts

---

### 4️⃣ README & Quick-Start (40 min, no sub-agents)

**Goal:** <2 min to understand, <5 min to run

**Deliverables:**

- **Root `README.md`** structure:
  ```markdown
  # Local LLM Council
  
  An offline-first multi-model AI council that debates topics in parallel.
  
  **60-Second Setup:**
  git clone https://github.com/sakethjaxx/local-llm-council.git
  cd local-llm-council
  ./start.sh  # or start.ps1 on Windows
  # Open http://localhost:8000 in your browser
  
  **What Happens:**
  1. Topic submitted → 3 AI personas analyze in parallel
  2. Smart phase: Are they agreeing? Skip debate or dig deeper.
  3. Cross-review: They critique each other's analysis
  4. Chairman: Synthesizes final decision with consensus score
  
  **Try It Locally (No LLM Needed Yet):**
  python main.py --demo  # loads demo run, no Ollama required
  
  **Cloud Optional:**
  Set OPENAI_API_KEY=sk-... in .env for GPT fallback
  
  **Docs:**
  - FIRST_RUN.md → Ollama setup guide
  - ARCHITECTURE.md → How it works
  - API.md → HTTP endpoints
  - TROUBLESHOOTING.md → Common issues
  ```

- **`FIRST_RUN.md`** (docs/):
  - Ollama installation (link + version check)
  - `ollama pull mistral` example
  - Expected startup output
  - Quick test: `curl http://localhost:11434/api/tags`

- **`.env.example`** (root):
  ```
  # Local Ollama (default, no setup needed)
  OLLAMA_BASE_URL=http://localhost:11434
  
  # Optional: Cloud LLM fallback
  # OPENAI_API_KEY=sk-...
  # ANTHROPIC_API_KEY=sk-ant-...
  
  COUNCIL_CORS_ORIGINS=*
  COUNCIL_ENABLE_PYTHON_TOOL=true
  COUNCIL_MAX_RECENT_RUNS=20
  ```

---

### 5️⃣ Preset Demo Personas (40 min, no sub-agents)

**Goal:** One-click council setup + instant demo

**Deliverables:**

- **Expand `demo_catalog.py`** with 4 presets:
  
  a) **"Tech Lead Council"** (3 seats, free)
     - Senior Backend Dev (focus: scalability, reliability)
     - Full-Stack Engineer (focus: UX, feature completeness)
     - System Architect (focus: long-term vision, trade-offs)
     - Example topic: "Should we migrate from PostgreSQL to DynamoDB?"

  b) **"Code Review Board"** (5 seats, free)
     - Pedantic Reviewer (nitpicks style, security)
     - Performance Guru (optimization focus)
     - UX Advocate (user impact)
     - DevOps Engineer (deployment, monitoring)
     - Pragmatist (business constraints)

  c) **"Startup Brainstorm"** (4 seats, free)
     - Product Manager (user needs, market fit)
     - Engineer (technical feasibility)
     - Designer (UX, brand)
     - Marketing Lead (go-to-market, positioning)
     - Example topic: "How should we approach AI feature rollout?"

  d) **"Research Lab"** (3 seats, free)
     - Theorist (research, cutting edge)
     - Pragmatist (real-world applicability)
     - Skeptic (assumptions, counter-evidence)

- **Each preset contains:**
  ```python
  {
    "name": "Tech Lead Council",
    "description": "3 architects debate backend decisions",
    "seats": [
      {
        "id": "backend",
        "persona": "Senior Backend Engineer",
        "model": "mistral",  # or gpt-4 if OPENAI_API_KEY set
        "focus_areas": ["scalability", "reliability"],
        "style": "data-driven, pragmatic"
      },
      # ... more seats
    ],
    "example_topic": "Migrate to microservices?",
    "cost": "free (local Ollama)"
  }
  ```

- **UI endpoint `GET /api/presets`:**
  - Returns all presets + metadata
  - No auth required

- **UI feature:** Dropdown selector → auto-populates roster

---

### 6️⃣ Streaming & Real-Time Progress (40 min, no sub-agents)

**Goal:** User sees live council in action, no "waiting..." ambiguity

**Deliverables:**

- **Enhanced `/api/run/<run_id>/events` SSE endpoint:**
  - `event: phase_start` → `{ "phase": 1, "member_count": 3 }`
  - `event: member_analysis` → `{ "member_id": "backend", "tokens": 342, "latency_ms": 2100 }`
  - `event: smart_phase_decision` → `{ "skip_phase_2": false, "consensus": 0.72 }`
  - `event: phase_end` → `{ "phase": 2, "total_latency_ms": 5200 }`
  - `event: complete` → `{ "run_id": "...", "status": "success" }`
  - Heartbeat every 30s (comment: `:keep-alive`)

- **`index.html` improvements:**
  - **Progress bar:** Phase 1: [████░░░░] 60% | Member latencies below
  - **Member cards:** Show live token count + spinning icon while streaming
  - **Results pane:** Markdown rendering, code blocks with syntax highlight
  - **Export buttons:** Download JSON, Markdown, HTML
  - **Error state:** Big red banner with actionable message + link
  - **Dark mode toggle:** Simple CSS swap

- **Test:** Stream council run, verify UI updates live, no lag

---

### 7️⃣ Smart Phase & Cross-Review Logic (30 min, no sub-agents)

**Goal:** Phase 1.5 decides Phase 2; Phase 3 synthesizes result

**Deliverables:**

- **`smart_phase.py` validation:**
  - Embed all Phase 1 analyses via MiniLM
  - Calculate cosine similarity pairwise
  - If all pairs > 0.88 → mark `consensus=true`, skip Phase 2
  - Otherwise → run Phase 2 (cross-review)
  - Log decision in `run_store` for metrics

- **Phase 2 prompt (`agent_prompts/phase_2_critique.md`):**
  ```
  You reviewed Seat A's and Seat B's analyses of: {topic}
  
  Their conclusions:
  - Seat A: {analysis_a}
  - Seat B: {analysis_b}
  
  Provide a brief critique:
  1. Strengths of each view
  2. Key gaps or blind spots
  3. Questions for clarification
  
  Keep it to 100-150 words.
  ```

- **Phase 3 prompt (`agent_prompts/phase_3_synthesis.md`):**
  ```
  As chairman, synthesize the council's decision on: {topic}
  
  Phase 1 analyses:
  {all_phase1_outputs}
  
  Phase 2 critiques:
  {all_phase2_outputs}
  
  Provide JSON:
  {
    "verdict": "clear recommendation",
    "consensus_confidence": 0.95,
    "key_disputes": ["if any"],
    "risk_score": 7,  # 0-10
    "action_items": ["do this", "watch for that"],
    "next_steps": "implementation path"
  }
  ```

- **Test:** Run council → verify all phases logged, JSON output valid

---

### 8️⃣ Database & Metrics (30 min, no sub-agents)

**Goal:** Persistent runs, metrics dashboard, feedback loop

**Deliverables:**

- **`run_store.py` audit:**
  - Confirm `PRAGMA journal_mode=WAL` on init
  - Schema: runs, phase_outputs, run_feedback
  - All CRUD operations working

- **`GET /api/runs/metrics` endpoint:**
  ```json
  {
    "total_runs": 42,
    "avg_latency_ms": 4200,
    "latest_runs": [
      {
        "run_id": "abc123",
        "topic": "Microservices?",
        "started_at": "2024-07-06T...",
        "duration_ms": 5200,
        "member_count": 3,
        "consensus_confidence": 0.92,
        "status": "complete"
      }
    ]
  }
  ```

- **`POST /api/run/<run_id>/feedback` endpoint:**
  ```json
  { "action_index": 0, "rating": 5, "note": "Spot-on analysis" }
  ```
  Stored for future learning signals.

- **Test:** Make 3 council runs, query metrics, verify all fields present

---

### 9️⃣ Testing & Quality (40 min, no sub-agents)

**Goal:** Baseline test coverage, CI/CD ready

**Deliverables:**

- **`tests/test_api.py`** (if missing):
  - `test_post_run_valid_topic` → 200, run_id returned
  - `test_sse_stream_complete` → all events received
  - `test_metrics_endpoint` → 200, latest_runs list

- **`tests/test_orchestrator.py`** (if missing):
  - `test_phase_1_parallel` → all members run in parallel
  - `test_smart_phase_consensus` → skip Phase 2 if agreement > 0.88
  - `test_phase_3_synthesis` → JSON output valid

- **`tests/test_run_store.py`** (if missing):
  - `test_create_run` → row inserted
  - `test_save_phase_output` → phase_outputs populated
  - Parallel write test (2 concurrent runs)

- **Run:** `pytest tests/ -q --tb=short` → all pass

- **Optional CI/CD:** `.github/workflows/test.yml`
  ```yaml
  on: [push, pull_request]
  jobs:
    test:
      runs-on: ubuntu-latest
      steps:
        - uses: actions/checkout@v3
        - uses: actions/setup-python@v4
          with:
            python-version: '3.13'
        - run: pip install -r requirements-dev.txt
        - run: pytest tests/ -q
  ```

---

### 🔟 Documentation Suite (40 min, no sub-agents)

**Goal:** Every developer question answered, zero friction

**Deliverables:**

- **`docs/ARCHITECTURE.md`:**
  - ASCII diagram: Input → Phase 1 (parallel) → smart_phase → Phase 2 OR Phase 3 → SSE → UI
  - Component overview table (orchestrator, router_agent, run_store, etc.)
  - Data flow: request lifecycle
  - ~500 words, one graphic

- **`docs/API.md`:**
  ```
  POST /api/run
  POST /api/run/<run_id>/feedback
  GET /api/run/<run_id>/events (SSE)
  GET /api/runs/metrics
  GET /api/config
  GET /api/presets
  ```
  Each with curl example + response schema

- **`docs/CUSTOMIZATION.md`:**
  - Writing custom persona prompts
  - Adding new LLM provider (via LiteLLM)
  - Tweaking Phase 2 critique prompt
  - ~400 words

- **`docs/TROUBLESHOOTING.md`:**
  - "Ollama connection refused" → check port, start Ollama
  - "Model not found" → show `ollama pull mistral`
  - "CORS error" → set COUNCIL_CORS_ORIGINS
  - "Timeout after 30s" → increase model size? check RAM
  - ~300 words

- **`docs/ROADMAP.md`:**
  - Phase 3 enhancements (memory_store, semantic memory)
  - UI: custom templates, collab mode
  - Performance: distributed orchestration
  - ~200 words

---

## Simplicity Rules (Non-Negotiable)

**If you're about to add code and ANY of these are true, STOP and simplify:**

1. ❌ "User needs to read the docs to use this" → Automate it or add clear defaults
2. ❌ "Error message doesn't say how to fix it" → Rewrite it with actionable steps
3. ❌ "Setup requires more than 2 commands" → Combine them or auto-detect
4. ❌ "Feature only works if you configure X" → Add a sensible default
5. ❌ "Code is clever but hard to understand" → Make it boring but obvious
6. ❌ "Edge case needs special handling" → See if you can eliminate the edge case
7. ❌ "This requires a sub-agent to explain" → You don't understand it well enough

**Examples of Simplification:**

- ❌ Detect Ollama via HTTP health check → ✅ Try the first API call, catch error
- ❌ Require user to set OLLAMA_BASE_URL → ✅ Default to localhost:11434, use .env only if set
- ❌ Complex retry logic with exponential backoff → ✅ Simple 3 retries, fail fast if all fail
- ❌ Streaming with multiple event types → ✅ One event type: `data: {json}`
- ❌ Plugins/extensions system → ✅ Hardcoded presets, no plugin infrastructure
- ❌ User can configure everything → ✅ Good defaults, 2 config options max

---

## Quality Checklist (Gap-Fix Specific)

**After each gap fix, verify:**

- [ ] **Does it work?** Manual test: break it, fix it, see success + error paths
- [ ] **Is the error message helpful?** Non-technical person can understand + fix
- [ ] **Is it the simplest solution?** Not the smartest, the simplest
- [ ] **Did it break anything?** Run affected tests
- [ ] **Is it documented?** If not obvious, add to TROUBLESHOOTING.md or code comment

---

## Success Definition

When complete:
- ✅ **Zero critical gaps.** App starts, runs, produces council output
- ✅ **All high-impact gaps fixed.** Users don't hit errors in first 5 min
- ✅ **Simple setup.** 2-3 commands max: `./start.sh` → working UI
- ✅ **Clear error messages.** Every error tells user what went wrong + how to fix
- ✅ **Working end-to-end.** Topic → Phase 1 → Phase 1.5 → Phase 2/3 → JSON result
- ✅ **Real-time streaming.** UI shows live progress, no "waiting..." ambiguity
- ✅ **Persistent & queryable.** All runs stored, metrics endpoint works
- ✅ **Tests passing.** `pytest tests/ -q` green, core logic covered
- ✅ **Deployed everywhere.** Docker image builds, start.sh works on Win/Mac/Linux
- ✅ **Documented simply.** Every user question answered, no confusion

**NOT Success:**
- ❌ "It's feature-complete but users need 10 commands to start"
- ❌ "Error messages are technically correct but unhelpful"
- ❌ "Setup works if you follow the docs perfectly"
- ❌ "There's a UI but it's confusing to use"

---

## Execution Checklist (Do in This Order)

1. [ ] **Audit**: Run code, document actual gaps in GAP REPORT
2. [ ] **Fix CRITICAL gaps**: App won't start, core functions broken (30-60 min)
3. [ ] **Fix HIGH gaps**: Users hit in first 5 min, hard errors (60-120 min)
4. [ ] **Fix MEDIUM gaps**: Setup friction (60-90 min)
5. [ ] **Add core deliverables**: Presets, metrics, tests (90 min)
6. [ ] **Polish & test**: Quality checklist pass (30 min)
7. [ ] **Documentation**: Complete suite (40 min)
8. [ ] **Final validation**: Fresh clone test, error scenarios, edge cases (20 min)

**Total time budget: ~4-5 hours.** Go fast, ship working, don't over-engineer.

---

## Success Definition

When complete:
- ✅ Fresh clone → 1 command (./start.sh) → working council in <2 min
- ✅ All endpoints tested & working
- ✅ 35+ tests passing, no regressions
- ✅ Docker deploys cleanly
- ✅ Clear, actionable error messages
- ✅ Zero-cost local path (Ollama), cloud optional
- ✅ Docs complete (README, FIRST_RUN, API, ARCH, TROUBLESHOOTING)

**Target Completion:** Single session, <4 hours with token-efficient execution.

---

## Ease-of-Use Scoring System

**When deciding between solutions, ask:**

| Question | Score 1 | Score 5 |
|----------|---------|---------|
| **Steps to use?** | Requires 5+ commands | Works with 1-2 commands |
| **Error clarity?** | Stack trace, cryptic message | Clear English: "X failed because Y. Fix: Z" |
| **Setup needed?** | Lots of config, docs required | Works out-of-box, sensible defaults |
| **Mental load?** | Need to understand internals | Just click/type, black box is OK |
| **First-time success?** | 20% of new users succeed | 95% of new users succeed |

**Scoring Rule:** If solution scores <3/5 on average, simplify it.

---

## Real-World Testing (Fable Must Do This)

**Before marking as "complete":**

1. **Fresh clone test:**
   - Clone repo to new folder
   - Run `./start.sh` (or start.ps1)
   - Open browser, see UI
   - Submit a topic
   - See full council output
   - **Checkpoint:** Should work in <3 min, zero config

2. **Error scenario test:**
   - Kill Ollama while running a council
   - See helpful error, not crash
   - Restart Ollama, council still works
   - **Checkpoint:** Error message tells user how to fix

3. **New user test:**
   - Give README to someone unfamiliar with the project
   - Watch them set up and run a council
   - Note where they get stuck
   - Fix those friction points
   - **Checkpoint:** They succeed without asking questions

4. **Docker test:**
   - `docker-compose up`
   - API responds
   - UI loads
   - Council runs end-to-end
   - **Checkpoint:** Production-ready deployment works

---

## Commit & Document Each Gap Fix

**For each gap fixed, commit with:**

```
fix: [Gap Name]

- Root cause: [Why it was broken]
- Solution: [What was changed]
- User impact: [What error they won't see anymore]
- Testing: [How we verified it works]

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>
```

---

## Red Flags (If You See These, STOP & Simplify)

- ❌ "This fix requires a 2-page explanation" → Too complex
- ❌ "Users need to understand our architecture to use this" → Design is wrong
- ❌ "We'll document this in ADVANCED_SETUP.md" → It shouldn't be advanced
- ❌ "Edge case only affects X% of users" → Fix the root, not the edge case
- ❌ "This will be easier once we add feature Y" → Build Y first or cut this
- ❌ "Requires setting 3+ environment variables" → Too many configs
- ❌ "Complex to explain, so we'll skip it" → If you can't explain simply, it's wrong

---

## Final Checklist: All Must Pass

**CRITICAL FIXES (All Must Be Done):**
- [ ] App starts without errors
- [ ] Ollama errors are helpful, not cryptic
- [ ] All 3 phases (1, 1.5, 2/3) execute
- [ ] SSE streaming works end-to-end
- [ ] UI loads and can submit topics
- [ ] Results display properly

**HIGH-IMPACT FIXES (All Should Be Done):**
- [ ] start.sh / start.ps1 works
- [ ] `.env.example` present
- [ ] Error messages are actionable
- [ ] No hardcoded Ollama URL
- [ ] Tests pass

**MEDIUM (Do if Time):**
- [ ] Presets configured
- [ ] Metrics endpoint working
- [ ] Docker working
- [ ] Docs complete

**LOW (v2 if time-constrained):**
- [ ] Performance optimization
- [ ] Advanced config options
- [ ] UI polish

---

## What Success Looks Like

**A non-technical person can:**
- [ ] Clone the repo
- [ ] Run 1 command (`./start.sh`)
- [ ] Wait <1 minute
- [ ] See UI in browser
- [ ] Type a question
- [ ] See council discuss it live
- [ ] Get a clear decision with reasoning
- [ ] **All with ZERO confusion or docs reading**

**If they have to:**
- Read docs to start → Design failed, fix it
- Set environment variables → Design failed, use defaults
- Troubleshoot errors → Error message was bad, fix it
- Run multiple commands → Automate it into one

---

## Summary: What Fable Needs to Deliver

**Final deliverable is ONE THING: A local LLM council that:**

✅ Starts with `./start.sh` (Linux/macOS) or `start.ps1` (Windows)  
✅ Loads UI in browser within 1 minute  
✅ User submits topic → Council discusses → Results appear live  
✅ Every error message is helpful + actionable  
✅ Works locally (Ollama) by default, zero cost  
✅ All code tested, no regressions  
✅ Docker deployable for prod  
✅ Docs make everything clear  

**NOT a feature checklist. NOT a polished product. Just: WORKS, SIMPLE, CLEAR.**

---

**Now go audit the code, find real gaps, fix them with the simplest solutions, ship it. 🚀**
