# Local LLM Council — Feature Audit & Improvement Plan

> **Constraint:** every recommendation in this document must be achievable **at zero recurring cost**. No paid APIs in the required path. Cloud LLMs may be supported as opt-in (user provides their own key), but every default flow runs on Ollama + local libraries shipped with the project.

---

## Status Legend

| Marker | Meaning |
|---|---|
| ✅ Implemented | Code exists in `main` and is wired into the runtime |
| 🟡 Partial | Code exists but is incomplete (missing endpoints, tests, or wiring) |
| ⚪ Proposed | Discussed, not yet built |
| ⛔ Dropped | Originally proposed, no longer recommended |

## Quality Tiers (for implemented features)

- **Solid** — works, no urgent rework needed
- **Decent** — works, but has clear shortcomings worth addressing
- **Weak/Basic** — works minimally; design is the bottleneck

---

## 1. Audit of Existing Features

### 1.1 — 3-phase council pipeline · ✅ Solid
`orchestrator.py:355` — Phase 1 analyze → Phase 2 review → Phase 3 chairman.
**No urgent change.** Future addition: optional Phase 0 (briefing) for skill injection. Free.

---

### 1.2 — SSE token streaming · ✅ Solid
`_stream_llm_to_queue` streams chunks into a per-run queue. Works.
**Setback:** retry logic writes to RunStore inside the retry loop (see 1.18). Fix there.

---

### 1.3 — Ollama-first execution · ✅ Solid
`ollama_manager.py` checks installed models, optional auto-pull.
**No change.** This is the project's identity. Free.

---

### 1.4 — Hardware-aware default roster · ✅ Decent
`hardware_detect.py` picks a roster based on RAM tiers (3B / 7-9B / 14B / 32-70B).

**Problems:**
- Picks models that may not be installed locally — preflight then has to warn or auto-pull.
- Tier breakpoints are arbitrary: a 16GB Mac with iGPU will struggle with 8B models the function recommends.
- Ignores GPU/VRAM entirely.

**What to do:**
- Intersect tier × **installed Ollama models** × `provider_caps.MODELS` registry. Recommend only what is both installable and present.
- Add VRAM detection on macOS (Metal) and Linux (`nvidia-smi`) where available.
- Surface tier choice in the UI as a soft recommendation, not a hard default.

**Setbacks:**
- VRAM detection is platform-specific and brittle. Keep it best-effort with a graceful fallback to RAM-only logic.
- Auto-pulling models without consent burns disk; keep behind explicit user toggle.

---

### 1.5 — Demo presets & samples · ✅ Solid
`demo_catalog.py`, `demo_samples/` — preset prompts and demo files.
**Already mostly fine.** See 1.20 for config-rot concerns once presets need to be shared with UI.

---

### 1.6 — Mixed file uploads · ✅ Decent
`io_parser.py` parses md/json/text/pdf/code/images.

**Problems:**
- PDF parsing via PyMuPDF is OK but no OCR fallback for image-heavy PDFs.
- No size cap or page cap — a 500-page PDF will explode the context.
- No structural extraction (tables, headings as anchors).

**What to do:**
- Hard caps: max 25MB upload, max 60 PDF pages by default; configurable in env.
- Detect when PDF has near-zero extractable text and warn the user instead of feeding empty content into the council.
- Optional, free OCR via `pytesseract` (system Tesseract install, no cloud).

**Setbacks:**
- Tesseract adds a system-level dependency. Make it optional and skip silently if not present.

---

### 1.7 — Image-aware vision routing · ✅ Solid
Now uses `provider_caps.supports_image_input`. Single source of truth.

**One small leftover:** the model registry only flags vision models the project knows about; user-added Ollama vision models (e.g. a finetune) won't be detected. Document the registry-extension path or expose a `/provider/register` endpoint.

---

### 1.8 — Dynamic Swarm router · ✅ Decent
`router_agent.py` asks an LLM to design 3 personas for the topic.

**Problems:**
- Output is JSON-schema-validated only on cloud models; for local Ollama the result is a regex-extracted block that often fails on small models.
- No fallback to the default roster on parse failure (returns `None` and the caller has to handle it; current handling is OK but logs are noisy).
- Personas have no diversity check — small models often produce three nearly identical experts.
- No routing by model capability — a code-review persona may be assigned to a weak-reasoning model.

**What to do:**
- Add a deterministic fallback that mutates the default roster's personas using simple topic keywords (no LLM call) when parsing fails.
- Add a similarity check on the three personas using the existing MiniLM embedder; reject and retry if pairwise cosine > 0.85.
- When assigning model to persona, prefer models where `task_type in model.strengths` (see 1.27).

**Setbacks:**
- Retrying on similarity adds 1 extra LLM call worst case. Cap at 1 retry.

---

### 1.9 — Memory graph (triples) · 🟡 Weak
`memory_graph.py` stores `(subject, predicate, object)` triples in NetworkX, persisted as JSON.

**Problems:**
- Retrieval is **keyword substring matching** — semantically related but lexically different topics never match. ("microservices design" vs "service mesh architecture" share zero memory.)
- Memory extraction uses the **same model that just produced the verdict** → circular, low-signal triples.
- No `confidence`, no `last_seen`, no contradiction tracking → memory is a logbook, not a learned belief.
- `council_memory.json` grows unbounded and is reloaded fully on every retrieval call.
- Retrieval query must use the **synthesized topic embedding**, not keywords.

**What to do (free-of-cost only):**
1. Add a vector column to memory entries using a local embedding model (`all-MiniLM-L6-v2` already a dep via `smart_phase.py`).
2. Replace keyword retrieval with cosine top-K against the **topic embedding** (not keyword string).
3. Extend the triple schema: `confidence: float`, `last_seen: float (ts)`, `reinforced: int`, `contradicted: int`.
4. Apply decay on retrieval (`confidence *= 0.99 ** days_since_last_seen`).
5. Migrate JSON store to SQLite for incremental writes.

**Setbacks:**
- First run after upgrade has zero embeddings → background-rebuild on startup.
- Embedding the whole graph for every retrieval is wasteful; cache embeddings on disk indexed by triple ID.
- Local embedders take a few hundred MB of RAM. Already loaded via `smart_phase.py`, so reuse the singleton (see 1.14).

---

### 1.10 — Project code graph · ✅ Decent
`project_graph.py` builds an AST + regex dependency graph and renders a review prompt.

**Problems:**
- Only captures imports/asset refs, no call graph, no class hierarchy.
- The review prompt dumps the entire adjacency list — large repos blow the context window.
- No clustering or community detection — every project gets the same shape of summary.

**What to do:**
- Add module clustering via `networkx.community` (Louvain or label propagation, both free).
- Add a "hotspot" heuristic: nodes ranked by `in_degree × line_count`.
- Truncate prompt to top-K hubs + top-K isolated files when graph exceeds a size threshold.

**Setbacks:**
- Louvain is non-deterministic; seed it for repeatable reviews.
- Call-graph extraction (beyond imports) requires per-language tooling and is a bigger project — defer.

---

### 1.11 — Blast radius analysis · ✅ Decent
`blast_radius.py` finds reverse-dependencies of changed files.

**Problems:**
- Duplicates dependency-graph code from `project_graph.py`.
- Capped at 20 files in output silently — the full count is logged but the warning truncates.
- Doesn't distinguish strong (import) vs weak (string ref) edges in the report.

**What to do:**
- Refactor to consume `project_graph.build_project_graph()` instead of duplicating `os.walk` + AST parsing.
- Surface edge type in the warning so reviewers know if a "blast" is a real import chain or a string match.

**Setbacks:**
- Refactor risk: must preserve the existing JSON output shape consumed by callers.

---

### 1.12 — Post-run debate chat · ✅ Decent
`orchestrator.chat_with_member` lets the user keep talking to a specific member.

**Problems:**
- The chat session does not auto-include the chairman verdict, the topic, or attachments — the member starts each chat blind.
- No persistence of chat sessions; refresh wipes the conversation.

**What to do:**
- Inject the run summary (topic + chairman verdict + this member's Phase 1 output) into the system prompt automatically.
- Persist chat turns into `run_store` under a new `chat_turns` table keyed by `run_id, member_id`.

**Setbacks:**
- More context per turn = slower local inference. Truncate older messages when context fills.

---

### 1.13 — Run metrics · ✅ Decent
`metrics_store.py` records latency + status to JSONL.

**Problems:**
- Will diverge from `run_store.py` (SQLite). Two stores, overlapping data.
- No per-phase breakdown, no per-model token counts.
- JSONL grows unbounded — no rotation.

**What to do:**
- Make `metrics_store` a thin wrapper that writes only to `run_store`, OR keep JSONL only for streaming-friendly tail consumption (one consumer use case).
- Expose `/metrics/summary` from a single SQL query against `run_store`.
- Add daily rollup table (`metrics_daily`) computed lazily on first call per day.
- Rotate JSONL at 100MB or 30 days via a background task.

**Setbacks:**
- Existing JSONL consumers (if any) break. Add a one-shot migration script.

---

### 1.14 — Smart Phase consensus skip · ✅ Solid
`smart_phase.py` uses MiniLM cosine similarity to skip Phase 2 when members agree (>0.88).

**Problems:**
- Embedder is loaded inline in `smart_phase.py`. Memory graph upgrade (1.9) and skill registry (Phase 2) will load the same model twice or thrice.
- 0.88 threshold has no empirical basis — no audit trail of similarity scores.
- Skip rate is not monitored. If >40% of runs skip Phase 2, threshold is too low and users lose cross-critique without knowing.

**What to do:**
- Extract `embeddings.py` with a `get_embedder()` singleton (see P1.5-1).
- Return `(skip: bool, score: float)` from `should_skip()` and log score to `runs.smart_phase_score`.
- Surface skip rate in `/metrics/summary`.

**Setback:** none — this is pure refactor + instrumentation.

---

### 1.15 — Web search context · 🟡 Basic
`search_engine.py` uses DuckDuckGo (free) when a dispute is detected.

**Problems:**
- Only the chairman uses search. Members fly blind during analysis.
- Single 3-result top-K with no reranking.
- The "is there a dispute" detector calls the chairman model with a small prompt — fine, but it can hallucinate "NONE" when there really is a dispute.

**What to do:**
- Allow any seat to optionally enable a "research" capability (off by default).
- Cache search results in `run_store` so re-runs on the same topic don't repeat queries.
- Add a 5-second timeout on DDG; degrade gracefully on rate-limit.

**Setbacks:**
- Multi-seat search increases noise and latency. Keep it opt-in.
- DuckDuckGo's HTML endpoint is unstable under load; the `duckduckgo_search` library breaks periodically. Treat search as best-effort.

---

### 1.16 — Chunk + summarize · 🟡 Basic
`summarizer.py` chunks long input over 15K chars and map-reduces with the chairman model.

**Problems:**
- Hard threshold at 15K chars regardless of model context window.
- Summaries are sequential per chunk (despite `asyncio.gather`, the local Ollama serializes to one model).
- No deduplication — the same boilerplate appears in every chunk's summary.

**What to do:**
- Use `provider_caps.MODELS[m].context_window` to compute the threshold dynamically (50% of context window).
- Add a structural pre-pass: if input is code, split by file/module boundaries instead of lines.
- Cache summaries by content hash so repeated runs on the same file don't re-summarize.

**Setbacks:**
- Cache invalidation needed when files change. Use file mtime + size as cheap cache key.

---

### 1.17 — Provider capability registry · ✅ Solid
`provider_caps.py` ships the registry. Heuristics are gone.

**Minor issues:**
- `caps_for` falls back to a default `ModelCaps` for unknown models. Default `response_format=True` for unknown cloud models is unsafe — provider may reject.
- No way for a user to register a new Ollama model without editing the source.
- `ModelCaps` has no `strengths` or `tool_use` fields — router cannot make capability-aware assignments.

**What to do:**
- Default unknown models to `response_format=False` and `vision=False` (safest).
- Add `/provider/models` GET endpoint that returns the registry; future UI can show what's known.
- Add `strengths: list[str]` and `tool_use: bool` to `ModelCaps`. Populate for known models.
- Optional: load a `models.local.json` if present, merging user-added entries.

**Setbacks:** none material.

---

### 1.18 — Run persistence (SQLite) · 🟡 Partial
`run_store.py` exists, schema applied, orchestrator wires `begin_run`, `record_phase_output`, `finish_run`.

**Missing pieces:**
- No `/runs`, `/runs/{id}`, `DELETE /runs/{id}`, `POST /runs/{id}/feedback` endpoints in `main.py`.
- No tests in `tests/`.
- Phase output writes happen inside the retry loop in `_stream_llm_to_queue` — duplicates on retry are possible.
- Chairman Phase 3 output is not explicitly recorded (only Phase 2 lines visible in current wiring).
- `phase_outputs` missing `finish_reason` and `attempt_number` columns (see P1-6).

**What to do:**
- Add the four endpoints.
- Add `tests/test_run_store.py`, `tests/test_provider_caps.py`, `tests/test_redaction.py`.
- Move the `record_phase_output` call to the terminal-success branch of the retry loop so retries don't double-write.
- Confirm Phase 3 chairman output is written too (read `orchestrator.run` and trace).
- Apply schema migration for P1-6 columns on startup.

---

### 1.19 — Config redaction · 🟡 Partial
`provider_caps.redact_config` exists.

**Problem:** No tests. Not yet applied at every serialization boundary (`metrics_store`, `run_store`'s `roster_json`, any UI export).

**What to do:**
- Add adversarial unit tests with nested dicts, lists of dicts, and key names matching `*api_key*`, `*token*`, `*secret*`.
- Audit every `json.dump(s)` call in the repo and route configs through `redact_config` first.

**Setbacks:** miss one boundary and a key leaks. Worth a careful pass.

---

### 1.20 — Local export of reports · 🟡 Basic
UI button at `static/index.html:1069` exports the report as markdown via `exportReport()`.

**Problems:**
- Exports only the chairman's verdict + member analyses as text; no structured artifact.
- No JSON/zip option, no inclusion of metrics, attachments, or feedback.

**What to do:**
- Add `GET /runs/{id}/export?format=md|json|zip` server-side that produces:
  - `report.md` — human-readable
  - `run.json` — full run with all phases, redacted
  - `attachments/` — original uploads (when stored)
  - `metrics.json` — latency + token counts
- UI gets a dropdown for format choice.

**Setbacks:**
- Storing attachments requires deciding lifetime + cap on disk usage. Default: 30 days, 1GB total cap with LRU eviction.

---

### 1.21 — Prompt management · ⚪ Proposed (AI Engineering)
Phase 1 / 2 / 3 system prompts are hardcoded string literals in `orchestrator.py`. No version history, no diff-ability, no rollback.

**Problems:**
- One bad edit silently degrades all runs. No way to A/B test prompt changes.
- Hard to share prompt improvements across sessions.

**What to do:**
- Extract to `agent_prompts/phase_prompts/*.txt`, loaded at startup.
- Fail fast (`FileNotFoundError`) if any prompt file missing — don't silently fall through to a broken empty string.

**Setbacks:** none — pure organization.

---

### 1.22 — Chairman JSON parse robustness · ⚪ Proposed (AI Engineering)
Small local models (3B–7B) frequently produce JSON with trailing prose, partial escapes, or markdown fences. On `json.loads` failure the chairman verdict is silently lost.

**What to do:**
- Two-stage fallback: strip fences → retry; then regex-extract `verdict` + `risk_score` + `action_items`.
- Degraded dict returned on total failure: `{"verdict": "parse_failed", "risk_score": -1, ...}`.
- Log parse tier in `phase_outputs.finish_reason`.

**Setbacks:** regex extraction is lossy. Log prominently so the user knows they got a degraded result.

---

### 1.23 — Eval harness · ⚪ Proposed (AI Engineering)
30 tests verify plumbing. Zero tests verify output quality. Regressions in prompt changes are invisible.

**What to do:**
- `tests/eval/` — 5 golden topics with reference verdicts.
- Score: cosine similarity (MiniLM) between chairman verdict and reference. Pass ≥ 0.70.
- Log Smart Phase skip rate across golden runs — if >40% skip Phase 2, review the 0.88 threshold.
- Not in default pytest suite (slow). Run with standalone script or `--eval` flag.

**Setbacks:**
- Requires Ollama running. Document clearly.
- Golden verdicts drift as models update. Pin model versions for eval runs.

---

### 1.24 — LLM call observability · ⚪ Proposed (AI Engineering)
`phase_outputs` captures tokens and latency but not call quality signals.

**Missing:**
- `finish_reason` (`stop` / `length` / `tool_calls`) — `length` = silent truncation = quality loss.
- `attempt_number` — which retry succeeded. Routine retries indicate model/prompt issues.

**What to do:**
- Add both columns to `phase_outputs` (with migration).
- Expose in `GET /runs/{run_id}` response.
- Surface `length` finish_reason as a UI warning: "⚠ This seat's response was cut off."

**Setbacks:** Ollama streaming doesn't reliably return `finish_reason`. Store as `null` when absent.

---

### 1.25 — Token budget enforcement before Phase 2 · ⚪ Proposed (AI Engineering)
No context window guard exists. Phase 1 output (up to N tokens) fed verbatim into Phase 2 prompts can overflow a 4K–8K local model window. Truncation is silent — the reviewer never saw the full analysis.

**What to do:**
- In `orchestrator.py`, before building Phase 2 prompt per seat: check `provider_caps.caps_for(model).context_window`.
- Truncate/summarize Phase 1 output if it would overflow (`context_window - 500` buffer for instructions).
- Log truncation with `finish_reason="length_truncated_by_orchestrator"`.

**Setbacks:** summarization adds latency. Use truncation (not summarization) for Phase 2 input to keep it fast.

---

### 1.26 — Smart Phase threshold empirical review · ⚪ Proposed (AI Engineering)
0.88 cosine similarity threshold for Phase 2 skip is a magic number. No baseline data.

**What to do:**
- Log `smart_phase_score` per run (see P1.5-5).
- After 20+ runs, review skip rate. If >40% skip, raise threshold.
- Expose skip rate in `/metrics/summary`.

**Setbacks:** need actual run data before tuning. Instrument first, tune later.

---

### 1.27 — Model capability routing (strengths + tool_use) · ⚪ Proposed (AI Engineering)
`router_agent.py` assigns models to personas without knowing model strengths. A code-review persona on a weak-reasoning model underperforms silently.

**What to do:**
- Add `strengths: list[str]` and `tool_use: bool` to `ModelCaps`.
- `router_agent.py` filters candidate models by `task_type in strengths` when assigning.
- `tool_use` gate: don't assign Python REPL tool to a model where `tool_use=False`.

**Setbacks:** strengths are subjective. Document as soft hints, not guarantees.

---

### 1.28 — Health check endpoint · ⚪ Proposed (DevOps)
No `/health` endpoint exists. Any deployment target (Docker, systemd, launchd, reverse proxy) requires a liveness check.

**What to do:**
- `GET /health` → `{"status": "ok", "ollama": bool, "db": bool}`.
- `ollama` = `True` if Ollama API responds within 2 seconds.
- `db` = `True` if SQLite `council_runs.db` is reachable.

**Setbacks:** none.

---

### 1.29 — WAL mode coverage gap · ⚪ Proposed (DevOps)
`run_store.py` sets `PRAGMA journal_mode=WAL` on first connection. `metrics_store.py` opens its own SQLite connection without WAL mode. Under concurrent runs, one writer can lock the other.

**What to do:**
- Add a shared `db_connect(path)` helper in `run_store.py` that always applies WAL + foreign keys pragmas.
- `metrics_store.py` uses `db_connect` instead of raw `sqlite3.connect`.

**Setbacks:** none — pure correctness fix.

---

### 1.30 — Graceful shutdown on SIGTERM · ⚪ Proposed (DevOps)
uvicorn kills mid-stream SSE connections on SIGTERM. Active runs lose their stream.

**What to do:**
- Register a SIGTERM handler that sets a global `shutdown_requested` flag.
- `_stream_llm_to_queue` checks flag and sends a `{"event": "shutdown"}` SSE event before closing.
- Allow up to 10 seconds for in-flight runs to drain.

**Setbacks:** doesn't solve mid-inference kill (Ollama holds the connection). Document as best-effort.

---

### 1.31 — Cost-per-token fields in provider registry · ⚪ Proposed (Cloud Engineering)
`provider_caps.ModelCaps` has no cost fields. Users have no way to see estimated cost before running a cloud council.

**What to do:**
- Add `cost_per_input_token: float = 0.0` and `cost_per_output_token: float = 0.0` (USD).
- Populate for Anthropic / OpenAI / Gemini / Groq models.
- `GET /runs/{run_id}` includes `estimated_cost_usd` computed from `tokens_in * cost_in + tokens_out * cost_out`.
- Default for Ollama models: 0.0 (free).

**Setbacks:** provider pricing changes. Treat as approximate. Document that costs are estimates.

---

### 1.32 — Auth boundary documentation · ⚪ Proposed (Cloud Engineering)
`/run` endpoint has no authentication. Fine for localhost. Catastrophic if accidentally exposed on a network port.

**What to do:**
- Document explicitly in README: "This server binds to `127.0.0.1` by default. Do not expose on a public interface without adding authentication."
- Add a startup warning if `host != "127.0.0.1"` and no `COUNCIL_API_KEY` env var is set.

**Setbacks:** none — this is documentation + a 5-line warning.

---

### 1.33 — Rate limit handling in orchestrator · ⚪ Proposed (Cloud Engineering)
LiteLLM raises `RateLimitError` on cloud provider throttle. Retry backoff exists but is not per-provider-cap-aware. All seats retry with the same backoff regardless of provider policy.

**What to do:**
- Add `rate_limit_rpm: int = 0` to `ModelCaps` (0 = unknown/unlimited).
- Before parallel `asyncio.gather` in Phase 1, group seats by provider and stagger launch by `60 / rate_limit_rpm` seconds if known.

**Setbacks:** only relevant for cloud councils. Skip if no cloud keys configured.

---

## 2. Re-evaluation of Proposed Features Under Free-of-Cost Constraint

### 2.1 — Project fingerprint · ⚪ Proposed
Detect tech stack and domain from uploaded files / repo structure.
**Free?** Yes — pure heuristics, no LLM needed.
**Action:** build it. Required for skill registry.

---

### 2.2 — Skill registry · ⚪ Proposed (re-scoped)
Extract reusable analysis skills from runs and inject into future Phase 1 prompts.

**Free-of-cost re-scoping:**
- Extraction model defaults to the **chairman's local model** (no cloud requirement). Quality will be lower than a cloud extractor — accept it.
- Add a quality gate: only extract skills when the run has at least one user 👍, OR chairman `risk_score` ≤ a configured threshold. This compensates for weaker extraction.
- Embeddings via the shared local embedder (1.14).

**Setbacks:**
- Local extraction produces vague skills. The 👍 signal is essential — without user feedback, the registry will fill with noise.
- Weak local models sometimes hallucinate "skills" that contradict the verdict. Add a sanity step: re-prompt the model with the extracted skill + verdict and ask "does this skill follow from the verdict, yes or no?" Discard on "no".

---

### 2.3 — Per-member stance memory · ⚪ Proposed
Each persona accumulates positions over time, surfaced in future Phase 1 prompts.

**Free?** Yes — same local extraction as 2.2.
**Action:** keep on roadmap. Build after 2.2 because it shares infrastructure.

**Setback:** privacy. Stance log on a security persona could embed sensitive info from a past confidential review. Ship with a per-run "ephemeral" toggle that opts out of stance writes.

---

### 2.4 — User feedback signal (👍 / 👎 / ignored) · ⚪ Proposed
Per-action-item rating, stored in `run_feedback` table.

**Free?** Yes — pure DB write.
**Action:** finish in Phase 1. This is the missing ground-truth signal for skill confidence.

**Setback:** users won't rate every action. Default state is `none`, not `ignored`. Don't penalize unrated items.

---

### 2.5 — Pre-recorded demo runs · ⚪ Proposed
Ship 5 pre-baked runs in `demo_runs/` to make skill-learning demo work live.

**Free?** Yes — JSON files committed to repo.
**Action:** generate after skill registry lands.

**Setback:** demo runs reference specific model outputs that drift over time. Treat them as read-only fixtures, not regenerable.

---

### 2.6 — Cloud LLM key UI input · ⚪ Proposed (made optional)
Let users paste OpenAI/Anthropic/Gemini/Groq keys in the UI.

**Free-of-cost re-scoping:** the key UI is allowed because **the user pays, not the project**. The default flow stays 100% local. Cloud is opt-in.

**Action:**
- Browser-side: store keys in `localStorage` (encrypted with a user-set passphrase, or `crypto.subtle` with a session-derived key).
- Send keys per-request as headers; server holds them only for the request lifetime.
- Never write keys to disk server-side.
- Strip keys from `run_store.roster_json` and all exports via `redact_config`.

**Setbacks:**
- `localStorage` is readable by any JS on the page. Don't load third-party scripts.
- A user accidentally committing a `.env` with keys is more likely than the app leaking them — make `.env` ignored by default and warn loudly if a key is ever printed to logs.

---

### 2.7 — Token budget profiles · ⚪ Proposed
Single global slider: Economy / Balanced / Performance.

**Free?** Yes.
**Action:** build it. Even with 100% local execution, smaller budgets = faster runs.

**Setback:** profile names have to map to actual `max_tokens` numbers per phase. Local 7B models produce notably worse output below ~250 tokens — set Economy floor accordingly.

---

### 2.8 — Benchmark mode · ⚪ Proposed (re-scoped)
Run same prompt across N rosters and compare side-by-side.

**Free-of-cost re-scoping:** default benchmark compares **two local rosters** (e.g. small vs medium model tier). Cloud comparison is opt-in only when the user has provided keys.

**Action:**
- Add a "Run benchmark" button that takes 2-4 rosters and runs them in sequence (local) or parallel (cloud).
- Store results as N separate runs in `run_store`, linked by a `benchmark_id`.
- Side-by-side UI shows latency, token counts, and chairman verdict diff.

**Setbacks:**
- Sequential local benchmark is slow on modest hardware (one model loads at a time in Ollama). Show progress clearly.
- Verdict comparison is qualitative; use the MiniLM embedder to compute pairwise verdict similarity as a numeric anchor.

---

### 2.9 — Config extraction from `index.html` · ⚪ Proposed
Move presets, seat templates, and personas from inline JS/Python into a single `presets.json`.

**Free?** Yes.
**Action:** worth doing before adding more UI features.

**Setback:** `index.html` is 1255 lines of co-located HTML/CSS/JS. Splitting carries regression risk — do it in one focused PR, behind a feature flag if possible, with snapshot tests of the rendered DOM.

---

### 2.10 — Vector embeddings on memory triples · ⚪ Proposed
Already covered in 1.9. Free. Required.

---

### 2.11 — Counterfactual view · ⚪ Proposed
"What would the chairman have decided without member X?" — re-run Phase 3 on a subset of analyses.

**Free?** Yes — one extra chairman call per scenario.
**Action:** defer to a later phase. Nice-to-have, not differentiating yet.

**Setback:** 1 counterfactual = 1 extra chairman call ≈ 5-30 seconds local. Limit to one at a time.

---

### 2.12 — Run replay UI · ⚪ Proposed
View any past run in full with phase outputs, member colors, chairman verdict.

**Free?** Yes — reads `run_store`.
**Action:** small UI lift after Phase 1 endpoints land.

**Setback:** large attachments stored alongside runs require lazy loading.

---

### 2.13 — Adversarial seat (devil's advocate) · ⚪ Proposed
A persona type that always argues against the consensus.

**Free?** Yes — it's a persona string.
**Action:** ship as a built-in seat in `presets.json`.

**Setback:** small models often slip out of the persona under pressure. Reinforce with strong system prompt and a Phase 2 instruction to challenge the most confident member.

---

### 2.14 — Member reputation scoring · ⚪ Proposed
Track which seats' recommendations the chairman accepts most often.

**Free?** Yes.
**Action:** compute lazily from `run_store` + `run_feedback`.

**Setback:** chairman acceptance is biased by ordering and persona loudness, not just quality. Weight by user 👍 instead of chairman acceptance to avoid feedback-loop bias.

---

### 2.15 — Fine-tune dataset export · ⚪ Proposed
Export `run_store` as a JSONL training file (system prompt + user + assistant per phase).

**Free?** Yes.
**Action:** small endpoint, low priority. Useful once you have 50+ stored runs.

**Setback:** must aggressively redact secrets and PII before export. Reuse `redact_config` and add a content-side scrubber for things like emails, IP addresses, JWTs.

---

### 2.16 — Daily standup / cron-driven runs · ⚪ Proposed
Schedule a daily run on the project repo and email/notify a digest.

**Free?** Yes — system `cron` + `cli.py`.
**Action:** add a thin CLI wrapper that drives the same orchestrator. Notification is optional and stays local (write to a file, ring the system bell).

**Setback:** scheduled runs that fail silently are worse than no runs. Surface the last run status in the UI prominently.

---

### 2.17 — Local document RAG · ⚪ Proposed
Index a folder of docs/code locally and let the council retrieve from it during Phase 1.

**Free?** Yes — same shared local embedder + SQLite for the vector store.
**Action:** stage this AFTER skill registry. Both share the same vector infrastructure.

**Setbacks:**
- Indexing large repos is slow on modest hardware.
- Stale index when files change. Use mtime-based incremental reindexing.

---

## 3. Prioritized Roadmap (Free-of-Cost Only)

### Phase 1 — Finish Foundation (≈ 1-2 days)

| # | Item | Role | Blocker? |
|---|---|---|---|
| 1 | P1-3 double-write fix (`run_id=None` on recursive call) | SDE | DB corruption on cloud runs |
| 2 | P1-4 redaction at all boundaries | SDE | Key leak to disk |
| 3 | P1-5 unknown model fallback → all False | SDE | Silent parse failures |
| 4 | P1-6 `finish_reason` + `attempt_number` columns | AI Eng | Can't diagnose truncation |
| 5 | P1-7 token budget enforcement before Phase 2 | AI Eng | Silent context overflow |
| 6 | P1-8 chairman JSON fallback parser | AI Eng | Lost verdicts on small models |
| 7 | P1-1 endpoint validation + tests | SDE | Phase 1 unshippable |
| 8 | 1.29 WAL mode in `metrics_store.py` | DevOps | Concurrent write locks |
| 9 | 1.28 `/health` endpoint | DevOps | Deployability |
| 10 | 1.32 auth boundary startup warning | Cloud Eng | Security gap documentation |

### Phase 1.5 — Quick Wins (≈ 1 day)

| # | Item | Role |
|---|---|---|
| 11 | P1.5-1 `embeddings.py` singleton | ML / AI Eng |
| 12 | P1.5-5 smart phase score logged | AI Eng |
| 13 | P1.5-4 phase prompts externalized | AI Eng |
| 14 | P1.5-2 `presets.json` extracted | SDE / PM |
| 15 | P1.5-3 blast radius uses project graph | SDE |

### Phase 2 — Memory Becomes Knowledge (≈ 3-5 days)

| # | Item | Role |
|---|---|---|
| 16 | P2-1 memory store → SQLite + vectors (topic embedding retrieval) | ML / AI Eng |
| 17 | P2-3 project fingerprint | SDE |
| 18 | P2-6 model routing by strengths + tool_use | AI Eng |
| 19 | P2-5 eval harness (5 golden topics) | AI Eng |
| 20 | P2-4 skill registry | AI Eng / SDE |
| 21 | P2-2 memory extraction separate model | ML |
| 22 | Pre-record 5 demo runs | PM |

### Phase 3 — Cloud Opt-In + Benchmark + Polish (≈ 2-3 days)

| # | Item | Role |
|---|---|---|
| 23 | 1.31 cost-per-token fields | Cloud Eng |
| 24 | 1.33 rate limit staggering | Cloud Eng |
| 25 | 2.6 cloud LLM key UI (browser localStorage) | SDE |
| 26 | 2.7 token budget profiles | SDE |
| 27 | 2.8 benchmark mode (local-vs-local default) | SDE / PM |
| 28 | 2.12 run replay UI | SDE |
| 29 | 1.20 export endpoint with format selector | SDE |
| 30 | 1.30 graceful shutdown | DevOps |

### Phase 4 — Differentiating Features (≈ ongoing)

| # | Item |
|---|---|
| 31 | 2.3 per-member stance memory |
| 32 | 2.13 adversarial seat preset |
| 33 | 2.17 local document RAG |
| 34 | 2.11 counterfactual replay |
| 35 | 2.15 fine-tune dataset export |
| 36 | 2.14 member reputation scoring |
| 37 | 2.16 cron-driven scheduled runs |
| 38 | 1.26 smart phase threshold tuning (after eval data exists) |

---

## 4. Cross-Cutting Setbacks

- **Local model quality ceiling.** Skill extraction, dispute detection, summarization, memory triple extraction, chairman JSON parsing, and eval scoring all rely on local models. A 3B model will produce vague/broken outputs across all of these. Document the recommended minimum (7B) for the full feature set.
- **Embedder RAM cost.** Adding the embedder to memory_graph + skill_registry + RAG triples its calls. Mitigated by the shared singleton (1.14) but still adds a one-time ~90–300MB load. Log load time on startup.
- **SQLite contention.** Multiple writers from concurrent runs can lock briefly. WAL mode required everywhere (see 1.29). Use a single `db_connect()` helper that applies pragmas consistently.
- **UI surface area.** Every new feature adds buttons. The current `index.html` is already at 1255 lines. The presets extraction (2.9 / P1.5-2) is a prerequisite to further UI work.
- **Disk usage.** Runs + attachments + embeddings grow unbounded. Add `MAX_DISK_GB` env var and LRU eviction from day one of attachment storage.
- **Privacy.** Skills, stances, and run history may contain sensitive code or topics. Provide a global "ephemeral run" mode that disables all persistence for a single session.
- **Prompt quality ceiling.** All quality improvements (eval harness, finish_reason logging, token budget enforcement) only reveal problems — fixing them still requires prompt iteration. Externalized prompt files (P1.5-4) are a prerequisite to safe iteration.
- **Eval baseline drift.** Golden topics for the eval harness must be re-evaluated when the primary model changes. Pin model version in `eval_config.json`.

---

## 5. What This Plan Deliberately Excludes

- Paid LLM dependencies in any default flow.
- Cloud-hosted vector databases (Pinecone, Weaviate, etc.). Use SQLite + numpy or local Chroma if needed.
- Multi-user authentication and RBAC. The project remains a local single-user tool.
- Mobile / responsive UI. Desktop-first.
- Multi-tenant skill sharing. Skills are per-installation, not synced.

These can be revisited later but are explicitly out of scope under the free-of-cost mandate.
