# Self Improvement Guide

The council reviews itself. You find the top issue. You fix it. You rerun. You repeat.

This document is the complete reference for running structured self-improvement cycles on the LLM Council project. It covers every review role, every targeted prompt, all known bug classes, Codex prompt templates for common fixes, metrics to track, and a weekly/monthly routine.

---

## Table of Contents

1. [Review Roles](#1-review-roles)
2. [File Groups](#2-file-groups)
3. [Council Prompts by Role](#3-council-prompts-by-role)
4. [Workflow — Running a Session](#4-workflow--running-a-session)
5. [Known Bug Classes](#5-known-bug-classes)
6. [Codex Fix Prompts](#6-codex-fix-prompts)
7. [Evaluating Council Output Quality](#7-evaluating-council-output-quality)
8. [Metrics to Track Over Time](#8-metrics-to-track-over-time)
9. [Weekly and Monthly Routine](#9-weekly-and-monthly-routine)
10. [Open Product Questions](#10-open-product-questions)
11. [Good vs Bad Council Actions](#11-good-vs-bad-council-actions)

---

## 1. Review Roles

Every self-review session should be done from one explicit role. Mixing roles in a single run produces shallow coverage of everything and deep coverage of nothing.

| Role | What they look for | When to use |
|---|---|---|
| **LLM Engineer** | Token budgets, context overflow, retry logic, structured output, concurrency, memory/skill extraction quality | After any change to orchestrator, prompts, or provider_caps |
| **Security Engineer** | SSRF, auth enforcement, key storage, upload limits, supply chain, default exposure | Before any public share or non-localhost deployment |
| **Product Engineer** | First-run UX, audience clarity, trust signals, non-goals, demo readiness | Before sharing with new users or publishing |
| **Code Quality Engineer** | Silent failures, type mismatches, async bugs, missing error propagation, duplicate logic | After any significant feature addition |
| **Prompt Engineer** | Schema conflicts, persona overlap, token/word budget mismatch, debate quality, instruction ambiguity | After changing any phase prompt or adding personas |
| **QA / Chaos Engineer** | Fallback behavior, Ollama down, model missing, port conflicts, startup/shutdown edge cases | Before releases, after reliability incidents |
| **Ops Engineer** | Health endpoints, metrics usefulness, log structure, deployment defaults, dependency pinning | Before any deployment change |
| **Technical Writer** | Docs portable on any machine, no hardcoded paths, quickstart completeness, security notes present | Before OSS release or new contributor onboarding |

---

## 2. File Groups

Attach only the files relevant to the review. Smaller evidence sets produce sharper findings.

### LLM Engineering Set
```
orchestrator.py
budget_profiles.py
smart_phase.py
memory_store.py
skill_registry.py
summarizer.py
router_agent.py
provider_caps.py
agent_prompts/phase_prompts/phase1_analyze.txt
agent_prompts/phase_prompts/phase2_review.txt
agent_prompts/phase_prompts/phase3_chairman.txt
```

### Security Set
```
main.py
io_parser.py
static/index.html
env.example
tool_repl.py
cloud_keys.py
```

### Product / Docs Set
```
README.md
docs/SPEC.md
docs/ARCHITECTURE.md
demo_run_guide.md
env.example
```

### Code Quality Set
```
main.py
orchestrator.py
run_store.py
provider_caps.py
metrics_store.py
memory_store.py
```

### Prompt Quality Set
```
agent_prompts/phase_prompts/phase1_analyze.txt
agent_prompts/phase_prompts/phase2_review.txt
agent_prompts/phase_prompts/phase3_chairman.txt
```

### Reliability Set
```
main.py
ollama_manager.py
shutdown_state.py
hardware_detect.py
metrics_store.py
```

### Run Quality Set
```
[export the run JSON from self_review_history/]
[export the run markdown from self_review_history/]
```

---

## 3. Council Prompts by Role

### 3.1 LLM Engineering Review

**When:** After any orchestrator change, budget change, prompt change, or provider_caps update.  
**Attach:** LLM Engineering Set.

```
You are a senior LLM systems engineer auditing a multi-model AI council pipeline.

Your job is to find bugs and design flaws in how this system calls language models, manages context, handles failures, and extracts structured data.

Review the attached files for the following, providing file:line references for every finding:

TOKEN BUDGETS
- Are phase1/phase2/phase3 token limits large enough for useful output?
- Does any phase prompt contain a word-count instruction that contradicts the token budget?
  (e.g. "keep under 300 words" with max_tokens=1000 is fine; "keep under 300 words" with max_tokens=600 is a conflict)
- Does the economy profile produce output too truncated to be useful?

CONTEXT WINDOW MANAGEMENT
- Is context overflow possible in Phase 2 (peer reviews) or Phase 3 (chairman brief)?
- Is truncation computed correctly — total budget across all peers, not per-peer independently?
- Is token counting done with a real tokenizer or a char/4 heuristic?
  (char/4 is wrong for code, non-English text, and very short tokens)
- Does chunk_and_summarize cap concurrent LLM calls?

STRUCTURED OUTPUT (response_format)
- Is response_format gated by caps_for(model)[1].response_format before being passed to litellm?
- For providers where response_format is False (Ollama), is the JSON schema provided inline in the prompt instead?
- Does the Phase 3 chairman prompt show the exact expected JSON schema?
- Is there a type mismatch between what the prompt schema implies and what the Pydantic model declares?

RETRY LOGIC
- Does the retry loop distinguish transient errors (timeout, rate limit, 503) from permanent failures (model not found, invalid API key, 401, 403)?
- Is there exponential backoff with jitter, or a fixed sleep?
- On permanent failure, does the system surface the error immediately instead of wasting 3 attempts?

CONCURRENCY AND TIMEOUTS
- Are any background tasks (memory extraction, skill extraction) wrapped in asyncio.wait_for with a timeout?
- Does skill extraction make more than 2 LLM calls per run?
- Does summarizer use a semaphore to cap parallel chunk calls?

MEMORY AND SKILL EXTRACTION
- Does memory extraction use response_format unconditionally (bug) or only when provider supports it?
- Does get_context() load all rows from memory_triples without a LIMIT? (O(N) at scale)
- Does skill extraction pass litellm_kwargs_for_model() so cloud model API keys are included?
- Is the smart phase threshold (cosine similarity) hardcoded or configurable via env var?
- Does the smart phase check for explicit disagreement keywords before skipping Phase 2?

PROMPT INJECTION
- Is user-provided topic text sanitized before being interpolated into the router agent prompt?

For each finding: exact file:line, what breaks, user-visible impact, specific fix.
Order findings by severity: silent data corruption > wrong output > performance > maintainability.
```

---

### 3.2 Security Review

**When:** Before any non-localhost deployment, before OSS release, after any endpoint change.  
**Attach:** Security Set.

```
You are a security engineer auditing an AI council server intended for OSS self-hosting.

The threat model: users running this on localhost (low risk) or on a LAN/VPS with a shared API key (medium risk). There is no multi-user auth, no RBAC. The goal is to find issues that would matter when someone accidentally exposes this to a network.

Review the attached files for:

SSRF (Server-Side Request Forgery)
- Can user-submitted topic text cause the server to make HTTP requests to internal IPs, link-local addresses (169.254.x.x), or loopback?
- Is URL fetching opt-in (env var default false) or always active?
- Are private IP ranges blocked before fetch: 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, 127.0.0.0/8, 169.254.0.0/16?
- Is there a response size cap on fetched URLs?
- Is there a timeout on URL fetches?

AUTH ENFORCEMENT
- Is COUNCIL_API_KEY actually enforced as a FastAPI dependency that returns 403 on mismatch?
- Or does it only log a warning (not enforced)?
- Does the server refuse to start when bound to non-localhost without COUNCIL_API_KEY set?
- Does the server default to 127.0.0.1 or 0.0.0.0?

UPLOAD LIMITS
- Is there a max file count per request?
- Is there a max bytes-per-file limit enforced at read time (not after full read)?
- Is there a total body size limit across all files?

KEY STORAGE
- Are cloud API keys stored in browser localStorage?
- Do CDN script tags (jsdelivr, unpkg) have SRI integrity hashes?
- What is the attack surface if a CDN script is compromised?

PYTHON TOOL
- Is COUNCIL_ENABLE_PYTHON_TOOL defaulted to false or true?
- Is it documented that it requires Docker and is an advanced opt-in feature?
- Can the tool be triggered without Docker installed (silent failure or crash)?

PROMPT INJECTION INTO ROUTER
- Is user topic text sanitized before interpolation into the swarm router prompt?
- Can a malicious topic cause the router to generate a harmful swarm config?

For each finding: file:line, attack vector, severity (P0/P1/P2), exact fix.
```

---

### 3.3 Code Quality Review

**When:** After any significant feature addition or refactor.  
**Attach:** Code Quality Set.

```
You are a senior backend engineer reviewing this codebase for correctness risks, silent failures, and hidden regressions.

Review the attached files for:

SILENT FAILURE MODES
- Where are exceptions caught and swallowed without surfacing to the user or run record?
- Where do background asyncio tasks fail silently (no done callback, no logging)?
- Where does a LLM call fail but the system continues as if it succeeded?

TYPE MISMATCHES AT PARSING BOUNDARIES
- Where does a Pydantic model declare one type (e.g. List[str]) but the parser returns another (e.g. str)?
- Where does JSON parsing have a regex fallback that produces a different shape than the primary path?
- Where is LLM output trusted without validation against the expected schema?

ASYNC CONCURRENCY BUGS
- Where are asyncio tasks created with create_task() without being awaited or tracked?
- Where is shared mutable state accessed from multiple concurrent coroutines without locking?
- Where does asyncio.to_thread() wrap non-thread-safe code (e.g. sqlite3 connections)?

MISSING ERROR PROPAGATION
- Where does a phase failure (Phase 1 member error) not mark the run as failed in RunStore?
- Where does run_store.finish_run() get called with "completed" even when errors occurred?

DUPLICATE LOGIC
- Where is the same pattern (cosine similarity, JSON extraction, DB connection setup) duplicated across multiple modules that should share it?
- Where does blast_radius.py duplicate logic that project_graph.py already provides?

DATABASE
- Are all SQLite connections using WAL mode?
- Are there any schema changes without a migration path?
- Are there raw string interpolations in SQL queries (injection risk)?

For each finding: file:line, exact risk, consequence, fix, test to add.
Return top 7 issues ordered by severity.
```

---

### 3.4 Prompt Quality Review

**When:** After changing any phase prompt, after adding new personas, after noticing degraded chairman output.  
**Attach:** Prompt Quality Set + orchestrator.py (for token budget values).

```
You are a prompt engineer specializing in multi-agent LLM systems.

Review the attached phase prompts and orchestrator token budgets for:

WORD/TOKEN BUDGET CONFLICTS
- Does any prompt contain a "keep under N words" instruction?
- What is the actual max_tokens budget for that phase (from orchestrator.py TOKEN_BUDGET_PROFILES)?
- Is there a conflict? (e.g. "under 300 words" ≈ 400 tokens, but max_tokens=600 — fine. "under 300 words" with max_tokens=400 — tight. "under 200 words" with max_tokens=300 — model will truncate reasoning.)

MISSING JSON SCHEMA IN CHAIRMAN PROMPT
- Does phase3_chairman.txt show the exact JSON schema the system expects?
- Or does it say "follow the schema" without showing it?
- Models produce correct JSON only when the schema is explicit in the prompt. Test: would a model that has never seen this codebase know what fields to output?

PERSONA DIFFERENTIATION IN PHASE 1
- Are the three council member personas genuinely different in reasoning approach?
- Or do they converge on the same framing (all say "strengths/risks/recommendations")?
- Good differentiation: one quantitative, one adversarial/devil's advocate, one big-picture synthesizer.
- Bad differentiation: all three review from the same angle with different labels.

PHASE 2 DEBATE QUALITY
- Does the Phase 2 prompt push reviewers to find genuine gaps and disagreements?
- Or does it encourage polite agreement ("they make some good points...)?
- "Under 200 words" in Phase 2 — is this tight enough to produce sharp critique or too tight?

INSTRUCTION CLARITY
- Are there any ambiguous instructions that different models might interpret differently?
- Are there contradictory instructions (e.g. "be decisive" and "be balanced")?
- Are persona instructions specific enough to produce differentiated outputs?

For each finding: quote the exact weak text, explain the failure mode it causes, provide a rewrite.
```

---

### 3.5 Product / OSS Readiness Review

**When:** Before sharing with new users, before OSS release, monthly.  
**Attach:** Product / Docs Set.

```
You are a product engineer evaluating this project for OSS release readiness.

The intended user: a developer who wants to run a multi-model AI council locally. They have Ollama installed. They will clone this repo and try to run it within 10 minutes. They will not read more than the README before filing a bug report or giving up.

Review the attached files for:

FIRST-RUN EXPERIENCE
- Does README.md have a "clone → install → run → verify" path that works on any machine?
- Are there hardcoded absolute paths in any docs (e.g. /Users/username/...)?
- Does env.example have safe defaults that work out of the box without any edits?
- Is the minimum required Ollama model named explicitly?

AUDIENCE AND PURPOSE CLARITY
- Is it clear who this is for and what it is not for?
- Is the "local power user" vs "self-hosted team tool" distinction made?
- Is it clear what "safe" means for this tool (localhost only, LAN with API key, etc.)?

TRUST SIGNALS
- Does the README mention cloud key storage in localStorage?
- Does it mention the Python tool requires Docker and is disabled by default?
- Does it mention URL fetching is disabled by default?
- Are non-goals explicit so users don't file wrong bugs?

PACKAGING
- Is there a LICENSE file?
- Is there a pyproject.toml?
- Is there a Dockerfile?
- Is there a GitHub Actions CI workflow?
- Are all requirements pinned to exact versions?

DEMO FRAMING
- Does any doc describe this as "demo-ready" or use demo-first language?
- Would a new user think this is a production-grade tool or a prototype?

For each gap: user-visible consequence, what to change, priority (P0/P1/P2).
```

---

### 3.6 Run Quality Review

**When:** Weekly, using saved exports from self_review_history/.  
**Attach:** Run JSON or markdown exports.

```
Review these past council runs for systematic output quality problems.

For each run, analyze:

CHAIRMAN PARSE QUALITY
- What is _parse_tier for each run? (json > fenced_json > regex_extracted > parse_failed)
- If regex_extracted or parse_failed: what was the chairman model and prompt, and what did it output?
- Are action_items specific and assigned, or generic and vague?
- Is risk_score an integer 0-10 or a float, null, or -1?

PHASE 2 SKIP PATTERNS
- How often was Phase 2 skipped (is_unanimous = true)?
- For runs where it was skipped: were the Phase 1 analyses actually in agreement, or just phrased similarly?
- Is the smart phase threshold (default 0.88) skipping too aggressively?

ANALYSIS QUALITY
- Do any Phase 1 analyses end mid-sentence (token truncation)?
- Do analyses from different personas say the same thing in different words (low differentiation)?
- Are analyses generic ("there are risks") or specific ("the retry loop at orchestrator.py:327 retries model-not-found errors")?

MEMORY EXTRACTION
- Are memory triples being added after runs? (check added/reinforced counts in logs)
- Are triples meaningful or trivial ("project has risks")?

LATENCY PATTERNS
- Which phase has highest average latency?
- Are any members consistently slower than others?
- Does Phase 3 chairman latency correlate with council_brief size?

For each problem: how many runs show it, root cause in the system, what to change.
```

---

### 3.7 Reliability / Chaos Review

**When:** After any startup/shutdown change, before release.  
**Attach:** Reliability Set.

```
You are a QA engineer stress-testing this system's failure modes.

For each scenario below, trace through the code and determine: does the system fail gracefully with a clear error, fail silently, or crash?

STARTUP FAILURES
- Ollama not running when server starts
- Required model not installed (hardware_detect picks a model that isn't pulled)
- Port 8765 already in use
- .env missing or malformed

RUNTIME FAILURES
- Ollama goes down mid-run (Phase 1 already started, Phase 2 not yet)
- One council member times out while others complete
- Chairman model returns malformed JSON (all parse tiers fail)
- All members fail — does run_store record status="failed"?

RESOURCE EXHAUSTION
- Very large file uploaded (>100MB)
- Topic text containing a URL to a very large file (SSRF + memory exhaustion)
- 10 concurrent council runs simultaneously

SHUTDOWN
- Server killed mid-run — does run_store show the run as "running" forever?
- Graceful shutdown — are in-flight SSE streams terminated cleanly?

For each scenario: file:line of the failure point, current behavior, correct behavior, fix.
```

---

## 4. Workflow — Running a Session

### Start the server
```bash
source venv/bin/activate
uvicorn main:app --host 127.0.0.1 --port 8765
# open http://127.0.0.1:8765
```

### Choose review type → paste prompt → attach files → run

Use Deep Debate mode for LLM Engineering, Security, and Code Quality reviews.
Use Fast Mode for Prompt Quality and Product reviews (quicker iteration).

### Save the run
```bash
mkdir -p self_review_history
RUN_ID=<paste run id>

# Save both formats
curl "http://127.0.0.1:8765/runs/$RUN_ID/export?format=json" \
  -o "self_review_history/$(date +%F)_$(echo $RUN_ID | cut -c1-8)_llm_eng.json"

curl "http://127.0.0.1:8765/runs/$RUN_ID/export?format=md" \
  -o "self_review_history/$(date +%F)_$(echo $RUN_ID | cut -c1-8)_llm_eng.md"

# Inspect raw run data
curl -s "http://127.0.0.1:8765/runs/$RUN_ID" | python3 -m json.tool | less
```

### Evaluate output quality
Before acting on findings, check if the council run itself was high-quality:
```bash
# Check parse tier in run JSON
curl -s "http://127.0.0.1:8765/runs/$RUN_ID" | python3 -c "
import json, sys
data = json.load(sys.stdin)
chairman = [p for p in data.get('phase_outputs', []) if p['member_id'] == 'chairman']
if chairman:
    import re
    m = re.search(r'_parse_tier.*?\"(.*?)\"', chairman[0]['output'])
    print('Parse tier:', m.group(1) if m else 'unknown')
"
```

If parse tier is `regex_extracted` or `parse_failed`, the chairman output is unreliable. Rerun before acting on findings.

### Act on findings
```bash
# Pick ONE finding. Implement fix. Run tests.
./venv/bin/pytest tests/ -q

# If fix touches orchestrator or memory:
./venv/bin/pytest tests/test_orchestrator.py tests/test_memory_store.py tests/test_smart_phase.py -v

# Rerun same review after fix to verify the finding no longer appears
```

### One issue per cycle. Never more.

---

## 5. Known Bug Classes

These bugs have been identified in past audits. If the council finds them again, the fix wasn't complete or regressed.

### 5.1 LLM Engineering Bugs

| ID | Bug | File:Line | Signal | Status |
|---|---|---|---|---|
| LLM-01 | `response_format=MemoryExtraction` passed to Ollama unconditionally | `memory_store.py:181` | Memory grows nothing after runs; no triples added | Open |
| LLM-02 | Chairman JSON schema not in phase3 prompt; model hallucinates fields | `phase3_chairman.txt` | `_parse_tier: regex_extracted` or `parse_failed` in runs | Open |
| LLM-03 | `consensus` field type mismatch: Pydantic `List[str]`, parser returns `str` | `orchestrator.py:39,62` | Downstream consumers get inconsistent types | Open |
| LLM-04 | Phase 2 truncation per-peer not total — context overflow on multi-member councils | `orchestrator.py:396-403` | Reviews cut mid-sentence on 4096-window models | Open |
| LLM-05 | Phase 3 council_brief has no context cap before sending to chairman | `orchestrator.py:434-446` | Chairman output degrades on large councils or small models | Open |
| LLM-06 | Token counting uses `len(text) // 4` instead of real tokenizer | `orchestrator.py:399` | Inaccurate truncation; 2× error on code or dense text | Open |
| LLM-07 | Retry loop retries permanent failures (model not found, 401, 403) | `orchestrator.py:313-334` | 6-second stall per member on hard errors | Open |
| LLM-08 | No exponential backoff on retries; fixed 2s sleep | `orchestrator.py:329` | Thundering herd when multiple members fail simultaneously | Open |
| LLM-09 | Skill extraction: up to 6 LLM calls per run (3 temperatures × extract + sanity) | `skill_registry.py:148` | Post-run latency spike; 6× Ollama load | Open |
| LLM-10 | `_request_text` in skill_registry missing `litellm_kwargs_for_model` | `skill_registry.py:121` | Cloud model API keys not passed; extraction silently fails | Open |
| LLM-11 | Skill extraction has no timeout | `skill_registry.py:129` | Background task can run indefinitely | Open |
| LLM-12 | Summarizer: no semaphore — unlimited parallel chunk LLM calls | `summarizer.py:40` | Ollama saturation on large inputs; cloud rate limits hit | Open |
| LLM-13 | Summarizer: no `max_tokens` per chunk call | `summarizer.py:31` | Chunk summaries can be arbitrarily long | Open |
| LLM-14 | Summarizer missing `litellm_kwargs_for_model` | `summarizer.py:31` | Cloud models silently fail summarization | Open |
| LLM-15 | Smart phase threshold `0.88` hardcoded, no env override | `smart_phase.py:30` | Can't calibrate without code change | Open |
| LLM-16 | Smart phase skips Phase 2 without checking disagreement keywords | `smart_phase.py:30` | False consensus when analyses use similar phrasing but disagree | Open |
| LLM-17 | Memory `get_context` loads all triples — O(N) at scale | `memory_store.py:261` | Latency grows as memory accumulates; no row cap | Open |
| LLM-18 | Router agent: topic interpolated directly into prompt — prompt injection | `router_agent.py:72` | User can hijack swarm config generation | Open |
| LLM-19 | Token budgets too small: balanced phase1=600, phase2=400 | `budget_profiles.py:8` | Analyses truncated; phase2 reviews cut off | Open |
| LLM-20 | Phase 1 prompt says "under 300 words" but max_tokens=600 (economy: 300) | `phase1_analyze.txt:6` | On economy profile, model truncates reasoning before conclusion | Open |
| LLM-21 | Chat mode has no retry logic | `orchestrator.py:646` | One transient Ollama error kills chat silently | Open |
| LLM-22 | Chat mode doesn't write to RunStore | `orchestrator.py:646` | No persistence, no debugging trail for chat sessions | Open |

---

### 5.2 Security Bugs

| ID | Bug | File:Line | Signal | Status |
|---|---|---|---|---|
| SEC-01 | URL fetching in topic text — SSRF, no private IP block, always active | `io_parser.py:94` | User triggers internal service fetch | Open |
| SEC-02 | `COUNCIL_API_KEY` only logs warning, no route enforcement | `main.py:43-47` | Key set but all endpoints open | Open |
| SEC-03 | Default bind to `0.0.0.0`, not `127.0.0.1` | `main.py:654` | LAN exposure on any network | Open |
| SEC-04 | No upload size limit — files read fully into memory | `main.py:205` | Memory exhaustion on large uploads | Open |
| SEC-05 | No upload count limit | `main.py:205` | 100-file upload possible | Open |
| SEC-06 | Cloud keys stored in browser `localStorage` | `static/index.html:854` | Any XSS or compromised CDN script reads keys | Open |
| SEC-07 | CDN scripts without SRI hashes | `static/index.html:10` | Supply chain compromise | Open |
| SEC-08 | `COUNCIL_ENABLE_PYTHON_TOOL=true` default | `env.example:13` | Docker dependency hidden; code execution on by default | Open |
| SEC-09 | Router prompt injection via user topic | `router_agent.py:72` | Malicious topic hijacks persona generation | Open |

---

### 5.3 Ops / Packaging Bugs

| ID | Bug | File:Line | Signal | Status |
|---|---|---|---|---|
| OPS-01 | No LICENSE file | repo root | Legal blocker for any OSS consumer | Open |
| OPS-02 | No pyproject.toml | repo root | No declared Python version range, no installable package | Open |
| OPS-03 | No Dockerfile | repo root | No reproducible install path | Open |
| OPS-04 | No CI workflow | repo root | No automated test gate on PRs | Open |
| OPS-05 | Unpinned deps: litellm, networkx, numpy, sentence-transformers, etc. | `requirements.txt:10` | Installs drift; breaking changes silently break prod | Open |
| OPS-06 | `/health` leaks provider key presence and feature flags | `main.py:606` | Config enumeration via unauthenticated endpoint | Open |
| OPS-07 | No liveness/readiness split | `main.py:606` | Can't distinguish "app up" from "Ollama up" in orchestration | Open |

---

## 6. Codex Fix Prompts

Use these when delegating fixes to Codex. Each is self-contained — paste as-is.

### Fix LLM-01: Memory response_format Ollama bug
```
Fix memory_store.py: response_format=MemoryExtraction is passed unconditionally to
litellm.acompletion (line 181-186), but Ollama models don't support structured output.
This causes silent failure — no triples extracted for any local run.

Changes in memory_store.py:
1. Add import: from provider_caps import caps_for
2. In extract_memory(), before acompletion call:
   use_response_format = caps_for(model)[1].response_format
3. If use_response_format True: pass response_format=MemoryExtraction as before.
   If False: omit response_format. Append to prompt instead:
   "\n\nRespond ONLY with valid JSON:\n{\"triples\": [{\"subject\": \"...\", \"predicate\": \"...\", \"object\": \"...\"}]}"
4. Keep existing _extract_json_block() call — it already handles fenced JSON.
Do not change any other file.
```

### Fix LLM-02 + LLM-03: Chairman schema in prompt + consensus type mismatch
```
Two related fixes.

FIX 1 — agent_prompts/phase_prompts/phase3_chairman.txt:
Append to end of file:

Output ONLY valid JSON. No markdown fences. Match this exact schema:
{
  "verdict": "your decisive recommendation as a string",
  "risk_score": <integer 0-10>,
  "action_items": ["action 1", "action 2", ...],
  "consensus": ["point of agreement 1", "point of agreement 2", ...],
  "disputes": ["disagreement 1", "disagreement 2", ...]
}

Remove "Under 400 words." from the prompt.

FIX 2 — orchestrator.py:
In parse_chairman_response(), in the normalize() function (line ~57):
- consensus: coerce to list. If result.get("consensus") is a str, return [v] if v else [].
  If already a list, keep as-is.
- Remove the appended "CRITICAL INSTRUCTION..." string from _chairman_decide() (line 444)
  since the schema is now in the prompt file.
Do not change any other file.
```

### Fix LLM-07 + LLM-08: Retry — permanent failures + backoff
```
Fix _stream_llm_to_queue() retry logic in orchestrator.py lines 313-334.

1. Add import: import random

2. In the except block, classify the error before retrying:
   error_msg = str(e)
   is_permanent = any(m in error_msg.lower() for m in [
       "model not found", "no such model", "pull model",
       "invalid api key", "unauthorized", "401", "403",
   ])
   is_retryable = any(m in error_msg.lower() for m in [
       "timeout", "timed out", "rate limit", "service unavailable",
       "502", "503", "429", "connection", "reset by peer",
   ])

3. If is_permanent: break retry loop immediately after logging. Do not sleep.

4. If is_retryable and attempt < max_retries - 1:
   backoff = (2 ** attempt) + random.uniform(0, 1)
   await asyncio.sleep(backoff)

5. If neither (unknown error): retry with backoff as before.

Keep existing metrics_store.record_llm_call() on failure. Do not change any other file.
```

### Fix LLM-09 + LLM-10 + LLM-11: Skill extraction calls + kwargs + timeout
```
Fix skill_registry.py extract_skills():

1. Remove the for-loop over temperatures (lines 148-224). Replace with a single extraction
   attempt at temperature=0.4. Keep the extract + sanity check structure inside.

2. In _request_text(), add:
   from cloud_keys import litellm_kwargs_for_model  (at top of file)
   Add **litellm_kwargs_for_model(model) to the acompletion call.

3. Wrap the body of extract_skills in a timeout:
   async def _do_extract():
       <existing logic here>
   try:
       await asyncio.wait_for(_do_extract(), timeout=45.0)
   except asyncio.TimeoutError:
       print(f"[Skills] Extraction timed out for run {run_id}")

Do not change any other file.
```

### Fix LLM-12 + LLM-13 + LLM-14: Summarizer concurrency + limits + kwargs
```
Fix summarizer.py:

1. Add imports at top: import asyncio; from cloud_keys import litellm_kwargs_for_model

2. Add max_tokens=600 to the acompletion call in summarize_chunk().

3. Add **litellm_kwargs_for_model(base_model) to the acompletion call.

4. Cap parallel calls with semaphore. Replace asyncio.gather call:
   sem = asyncio.Semaphore(4)
   async def bounded_summarize(idx, chunk):
       async with sem:
           return await summarize_chunk(idx, chunk)
   summaries = await asyncio.gather(*[bounded_summarize(i, c) for i, c in enumerate(chunks)])

Do not change any other file.
```

### Fix LLM-15 + LLM-16: Smart phase threshold configurable + keyword check
```
Fix smart_phase.py:

1. Read threshold from env:
   import os
   SKIP_THRESHOLD = float(os.getenv("COUNCIL_SMART_PHASE_THRESHOLD", "0.88"))

2. Add disagreement keyword check before returning skip decision:
   DISAGREEMENT_MARKERS = [
       "however", "disagree", "dispute", "contradict", "concern",
       "wrong", "incorrect", "but", "unfortunately", "risk", "danger"
   ]
   def _has_explicit_disagreement(analyses: dict) -> bool:
       text = " ".join(analyses.values()).lower()
       return sum(1 for m in DISAGREEMENT_MARKERS if m in text) >= 3

   In should_skip(): if _has_explicit_disagreement(analyses):
       print("[Smart Phase] Disagreement markers found — forcing Phase 2")
       return False, avg_sim

3. Update env.example: add COUNCIL_SMART_PHASE_THRESHOLD=0.88

Do not change any other file.
```

### Fix LLM-17: Memory get_context row cap
```
Fix memory_store.py get_context() line 261-268.

Replace the existing SELECT (no LIMIT) with:
   SELECT id, subject, predicate, object, confidence, last_seen, embedding
   FROM memory_triples
   WHERE embedding IS NOT NULL
   ORDER BY confidence DESC, last_seen DESC
   LIMIT 500

Add after fetchall():
   if len(rows) == 500:
       print("[Memory] Row cap hit — consider pruning low-confidence triples")

Do not change any other file.
```

### Fix SEC-01: SSRF
```
Fix SSRF in io_parser.py. Full prompt: [see P0-A in main Codex prompt list]
```

### Fix SEC-02 + SEC-03: Auth enforcement + bind default
```
Fix auth and bind in main.py. Full prompt: [see P0-B in main Codex prompt list]
```

### Fix LLM-19 + LLM-20: Token budgets + prompt word limit
```
Fix budget_profiles.py and phase1_analyze.txt:

1. Replace TOKEN_BUDGET_PROFILES in budget_profiles.py:
   "economy":     phase1=500,  phase2=400,  phase3=800,  chat=400
   "balanced":    phase1=1000, phase2=700,  phase3=2000, chat=800
   "performance": phase1=1500, phase2=1000, phase3=3000, chat=1200

2. In agent_prompts/phase_prompts/phase1_analyze.txt:
   Remove "Keep it under 300 words."
   Replace with "Be thorough but focused. Every sentence should add new information."

3. In agent_prompts/phase_prompts/phase2_review.txt:
   Remove "Under 200 words."
   Replace with "Be direct and specific. Cite file:line when reviewing code."

Do not change any other file.
```

---

## 7. Evaluating Council Output Quality

Before acting on any finding, verify the run itself was high quality.

### Check parse tier
```bash
RUN_ID=<id>
curl -s "http://127.0.0.1:8765/runs/$RUN_ID" | python3 -c "
import json, sys, re
data = json.load(sys.stdin)
for p in data.get('phase_outputs', []):
    if p['member_id'] == 'chairman':
        m = re.search(r'_parse_tier.*?\"(.*?)\"', p.get('output',''))
        print('Chairman parse tier:', m.group(1) if m else 'not found')
        print('Output preview:', p.get('output','')[:300])
"
```

### Parse tier quality ladder
| Tier | Quality | Action |
|---|---|---|
| `json` | Perfect — Pydantic validated | Trust the output |
| `fenced_json` | Good — model wrapped in backticks | Trust the output |
| `regex_extracted` | Degraded — only verdict + risk_score, action_items lost | Rerun with better chairman model or after fixing LLM-02 |
| `parse_failed` | Broken — chairman produced prose not JSON | Fix LLM-02 before acting on findings |

### Check Phase 2 skip rate
Runs where Phase 2 was skipped have shallower findings. If >50% of self-review runs skip Phase 2, the smart phase threshold is too aggressive or analyses are too similar.

```bash
curl -s "http://127.0.0.1:8765/runs" | python3 -c "
import json, sys
runs = json.load(sys.stdin)
# Check phase_outputs for 'SKIPPED' reviews
print(f'Total runs: {len(runs)}')
"
```

### Action item quality check
Good action items: name a file, a function, or an exact behavior.
Bad action items: "improve error handling", "add better logging", "make it faster".

If >50% of action items are vague, the Phase 1 persona prompts need differentiation work or the topic prompt was too broad.

---

## 8. Metrics to Track Over Time

After each self-review cycle, record these in `self_review_history/metrics.md`:

```markdown
## YYYY-MM-DD

- Review type: [LLM Engineering / Security / Code Quality / ...]
- Chairman parse tier: [json / fenced_json / regex_extracted / parse_failed]
- Phase 2 skipped: [yes / no]
- Smart phase score: [e.g. 0.82]
- Action items count: [N]
- Action items specific (file:line): [N of total]
- Top issue found: [one sentence]
- Fix implemented: [yes / no / deferred]
- Tests passing after fix: [yes / no / N/A]
- Known bugs resolved this cycle: [LLM-XX, SEC-XX]
```

**Trends to watch:**
- Parse tier degrading over time → chairman prompt or token budget regression
- Phase 2 skip rate increasing → smart phase threshold needs recalibration
- Action item specificity decreasing → persona prompts losing differentiation
- Same known bug appearing again → fix regressed or was incomplete

---

## 9. Weekly and Monthly Routine

### Weekly (4 runs, 1 per week)

| Week | Role | Files | Mode |
|---|---|---|---|
| 1 | LLM Engineer | LLM Engineering Set | Deep Debate |
| 2 | Security Engineer | Security Set | Deep Debate |
| 3 | Prompt Engineer | Prompt Quality Set + orchestrator.py | Fast |
| 4 | Run Quality | self_review_history/ exports (last 4 runs) | Fast |

After each run: fix top 1 issue. Run `./venv/bin/pytest tests/ -q`. Record in metrics.md.

### Monthly (1 additional run)

| Month | Role | Files |
|---|---|---|
| Every month | Product Engineer | Product / Docs Set |
| Odd months | Code Quality | Code Quality Set |
| Even months | Reliability / Chaos | Reliability Set |

Monthly runs are for strategic issues — don't try to fix monthly findings in the same session. File them in IMPROVEMENT_PLAN.md.

### Minimum viable version (when short on time)

```bash
# 1. Run
uvicorn main:app --host 127.0.0.1 --port 8765

# 2. Paste the LLM Engineering prompt, attach orchestrator.py + budget_profiles.py + memory_store.py
# 3. Export the run
# 4. Fix the top finding
# 5. Run tests
./venv/bin/pytest tests/ -q
# 6. Record in metrics.md
```

---

## 10. Open Product Questions

These are decisions that must be made by the project owner, not the council. They gate multiple fixes.

| Question | Why it matters | Options |
|---|---|---|
| **Who is this for?** | Local power user (solo, localhost) vs. self-hosted team tool (LAN, shared API key). These are different products with different auth, docs, and UX requirements. | Pick one as v1 target |
| **Cloud keys in v1?** | localStorage keys + CDN scripts is acceptable for local-only. For any network exposure it's a trust failure. Server-side key proxy would fix it but adds complexity. | Keep localStorage (local-only) / Add server-side proxy (team use) |
| **Python tool fate** | Enabled by default (hidden Docker dep, code execution surface). Should it be removed from default path entirely and documented as an advanced plugin? | Remove from default / Keep as opt-in |
| **OSS release timing** | P0 security bugs (SSRF, auth, upload limits) must be fixed before any non-localhost share. Is v0.1.0 release blocked on all P0s or just SEC-01 + SEC-02? | Fix all P0s first / Ship with documented limitations |

---

## 11. Good vs Bad Council Actions

The council's job is to produce specific, actionable findings. Push back on vague output.

**Good — specific, file-linked, testable:**
```
"Add asyncio.Semaphore(4) in summarizer.py:40 to cap parallel chunk calls.
 Currently fires N concurrent LLM calls for N chunks; saturates Ollama on >15KB inputs."

"Gate response_format=MemoryExtraction behind caps_for(model)[1].response_format
 in memory_store.py:181. Ollama provider has response_format=False — passing it causes
 silent extraction failure. After fix, add test: run extract_memory with ollama model,
 verify triples table grows."

"Embed JSON schema in phase3_chairman.txt so models don't hallucinate field names.
 Current prompt says 'follow the schema' without showing it. Result: 30% of runs
 show _parse_tier=regex_extracted, losing action_items and consensus."
```

**Bad — vague, unactionable:**
```
"Improve output quality."
"The system needs better error handling."
"Consider adding more robust retry logic."
"The UI could be clearer."
```

If a recommendation doesn't name a file, it's not done. If it doesn't explain the failure mode, it's not useful. If it doesn't say what to test, it's not complete.

---

## Appendix: Quick Command Reference

```bash
# List recent runs
curl -s http://127.0.0.1:8765/runs | python3 -m json.tool | head -100

# Inspect specific run
curl -s http://127.0.0.1:8765/runs/$RUN_ID | python3 -m json.tool

# Export run as markdown
curl "http://127.0.0.1:8765/runs/$RUN_ID/export?format=md" -o review.md

# Export run as JSON
curl "http://127.0.0.1:8765/runs/$RUN_ID/export?format=json" -o review.json

# Metrics summary
curl -s http://127.0.0.1:8765/metrics/summary | python3 -m json.tool

# Run tests (all)
./venv/bin/pytest tests/ -q

# Run tests (specific modules)
./venv/bin/pytest tests/test_orchestrator.py tests/test_memory_store.py -v

# Check memory triples count
sqlite3 council_runs.db "SELECT COUNT(*) FROM memory_triples;"

# Check skills count
sqlite3 council_runs.db "SELECT COUNT(*) FROM skills;"

# Find runs with failed chairman parse
sqlite3 council_runs.db "
SELECT run_id, output
FROM phase_outputs
WHERE member_id='chairman'
AND output NOT LIKE '%\"verdict\"%'
LIMIT 5;"

# Check smart phase scores
sqlite3 council_runs.db "
SELECT run_id, smart_phase_score
FROM runs
WHERE smart_phase_score IS NOT NULL
ORDER BY started_at DESC
LIMIT 20;"
```
