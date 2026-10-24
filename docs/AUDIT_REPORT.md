# LLM Council — Audit and Hardening Report

Date: 2026-10-07 · Scope: the whole repository at `d6b724a` (local `main`) · Host: Windows 11, 23.8 GB RAM, NVIDIA MX230 (2 GB, treated as CPU-only), Ollama 0.34.4, Docker 29.5.3, Python 3.13, Node 24.

## 1. Diagnosis and system-design assessment

LLM Council is a local-first, single-user FastAPI app: a browser UI and a CLI send a topic to a council of local models (Ollama via LiteLLM), stream the work over SSE, and store runs, memory and skills in SQLite. The architecture is sound for that scope. Its weaknesses were at the edges:

- **Trust boundary placement.** Authentication and admission ran *after* FastAPI had parsed request bodies, so the most expensive work happened before any check.
- **Ownership of in-flight work.** Nothing owned cancellation: a disconnected browser left model calls running, background tasks were untracked, and crashed runs stayed `running` forever.
- **Untrusted content in-process.** PDFs (native parser), code graphs and model tool calls ran with no deadline, memory ceiling or re-authorization.
- **Data leaving the process.** Secret scrubbing existed only for some persisted fields and worked per chunk, so split secrets and many sinks (logs, errors, chat, metrics, memory) leaked.
- **Event-loop discipline.** Several blocking calls (embedding, sandbox, slow model lookups) ran on the event loop, freezing the server.
- **Real-run correctness.** UAT against real models showed that the chairman's verdict never reached the UI or CLI. Mocked tests had hidden it for many releases.

After the changes, responsibilities are explicit (see `docs/ARCHITECTURE.md`, *Request Boundary and Run Lifecycle*):

| Concern | Owner |
|---|---|
| Admission, auth, body limits, security headers | `http_security` middleware, before any body is read |
| Run slots, background tasks, shutdown | `shutdown_state` |
| Phases and member tasks | `orchestrator` |
| Provider calls, timeouts, retries, tool authorization | `llm_stream` |
| Redaction | `provider_caps`, applied at the SSE layer, the stores and the log formatters |
| Untrusted-content isolation | `pdf_worker`, `tool_repl`, `project_graph` |
| Configuration | `council_env` |

## 2. Gaps found, fixes and verification

Severity is for the default local deployment; items marked *(LAN)* matter mostly when bound beyond localhost.

| # | Gap and evidence | Sev. | Fix | Commit / files | Verified by |
|---|---|---|---|---|---|
| 1 | API key checked by a FastAPI dependency, which runs **after** multipart/JSON parsing; unauthenticated clients could make the server read and spool uploads *(LAN)* | High | Auth in ASGI middleware before any body read; public: UI shell, static assets, CORS preflight | `63d276a` http_security.py, main.py | `test_http_security` (receive never called when unauthenticated); real-app subprocess: unauthenticated multipart → 403 |
| 2 | No cap on actual request bytes (chunked uploads unbounded) | High | 52 MiB cap on `Content-Length` and on received bytes; app's own parse-error reply replaced by 413 | `63d276a` | unit (chunked over/under limit); real app: 53 MiB chunked → 413 |
| 3 | Run admission was check-then-start; the count rose only when streaming began, so parallel requests all passed during upload/preflight | Med | Atomic slot reservation before body read, held through streaming, released on every exit (429 when full) | `63d276a` shutdown_state.py, routes_stream.py | 5 concurrent (max 2) → 2×200 + 3×429; release on exception and cancellation; real app: 4 concurrent (max 1) → 1×200, 3×429, slot reusable |
| 4 | Python tool executed **any** phase-1 `execute_python` tool call, offered or not (forged/unsolicited calls ran code) | High | Re-check at execution: opt-in, model capability, phase 1, depth, exact name, code shape/size; refused calls logged, never run | `41138ec` llm_stream.py | refusal matrix (12 cases); forged call never reaches sandbox |
| 5 | Sandbox: `subprocess.run` on the event loop; on timeout only the CLI died, the **container kept running** (unnamed); unbounded output; first-ever image pull consumed the deadline | High | Worker thread, unique container name, code via stdin (no mount), 10 s deadline that removes the container, 64 KiB output, `--cap-drop ALL`, `--pull never`, cleanup on success/failure/timeout/cancel | `41138ec` tool_repl.py | process-level tests (truncation, deadline, cancellation, unique names, loop responsiveness); **live Docker**: runs, no network, timeout, 0 leftover containers |
| 6 | Secrets leaked: per-chunk scrubbing missed keys split across stream chunks; chat, errors, logs, feedback, run errors, in-memory metrics, memory triples, skills unscrubbed | High | `StreamScrubber` per member/chat at the SSE layer; scrubbing log formatters; stores scrub notes/errors/triples/skills; metrics scrubbed on read | `6520f1c` provider_caps.py, routes_stream.py, logging_utils.py, stores | split-at-every-position test for 6 key formats + bearer; SSE, chat, errors, logs, feedback, metrics, memory (incl. prompt sent to extractor), skills |
| 7 | `redact_config` dropped every key containing "token", deleting `tokens_in/out`, `prompt_tokens`, `token_budget_profile` from SSE, metrics and exports | Med | Drop credential-named keys only for non-numeric values; suffix match (`*token`, `refreshToken`) | `6520f1c` | usage-counter test; adversarial-shape test kept |
| 8 | Model Markdown could load remote images (data exfiltration on render); no CSP | Med | Self-hosted CSP (connect/img/font/media `'self'`, `object-src 'none'`, `frame-ancestors 'none'`, …); DOMPurify hook strips non-local `src`, safe link `rel` | `b89f710` http_security.py, static/js/state.js | header test; browser suite: remote image stripped, no CSP violations (console errors fail the suite) |
| 9 | Code graph read whole files and resolved references quadratically; 4,000-file cap silent | Med | 1 MiB/file, 16 MiB total, 4,000 files, 20,000 edges; basename index; `stats.truncation` (additive) and a note in the review prompt | `1812597` project_graph.py | limit tests (each limit, oversized file listed but unread) |
| 10 | PDFs parsed by native code in the server process with no deadline/page/memory limits | High | Disposable child: 10 s deadline, 100 pages, text limit, 768 MiB ceiling (Linux `RLIMIT_AS`, Windows Job Object); refused where unenforceable (macOS) unless `COUNCIL_PDF_ALLOW_UNLIMITED_MEMORY=true` | `09e6a52` pdf_worker.py, io_parser.py | real PDFs; page/text limits; deadline; killed child → safe error; **Windows ceiling live**: 600 MB allocation fails under 200 MB; refusal path |
| 11 | `.env` loaded from the working directory upward, and LiteLLM calls `load_dotenv()` on import: starting from an untrusted folder could set `COUNCIL_API_KEY`, DB paths or keys; `python src/council/cli.py` loaded no config | High | `council_env`: environment > `COUNCIL_ENV_FILE` > checkout `.env`; `LITELLM_MODE=PRODUCTION`; tests use an empty env file | `6d5c843` council_env.py, \_\_init\_\_.py, cli.py | precedence tests; subprocess from a hostile directory for package and CLI entrypoints |
| 12 | Disconnect did not cancel model calls (abandoned generator closed only at GC); fire-and-forget background tasks (one unreferenced); stale `running` runs; `LIMIT -1` returned all rows | Med | `aclosing` streams; orchestrator cancels and awaits member tasks; tracked background registry with drain/cancel at shutdown; startup marks `interrupted`; limits clamped in stores | `d061cac` | disconnect, member cancellation, drain/cancel, recovery, bounded limits; real app: `/health` < 0.5 s during a blocking graph build |
| 13 | **Chairman verdict never reached clients**: phase code swallowed `member_done`, so the UI never rendered the verdict card, `council ask` always reported "unparseable", `check_diff` could never block | High | Forward member results; emit the chairman event with normalized JSON | `d990a34` (pushed) | regression test; live UAT U11/U19/U20/B01 |
| 14 | Memory embedding (first-call model load) blocked the event loop: server unanswered > 60 s after a run | Med | Embedding/retrieval in worker threads | `6195fa1` (pushed) | loop-tick test; live UAT U12 |
| 15 | Every model lookup took ~2.8 s (`localhost` → IPv6 detour, new HTTP client per call) | Med | `OLLAMA_API_BASE=http://127.0.0.1:11434` default (LiteLLM reads it too), pooled client | `e904eac` | catalog 2.75 s → 0.02 s measured |
| 16 | UI races: Turbo applied before the catalog loaded; launch preflight judged a cleared state → false "preflight failed" alert, no run | Med | Await catalog; launch waits for the newest preflight | `e31c38c`, `6814eeb` (pushed) | frontend race test; browser journey B01 |
| 17 | CPU-only machines were given 7B/8B rosters (a run took most of an hour) | Med | GPU detection + `COUNCIL_GPU_VRAM_GB`; shared small model on CPU; CLI `--model`/`--preset` | `241c56e` (pushed) | roster tests; live UAT U02/U19 |
| 18 | Keyboard-inaccessible controls (`<div onclick>`), nested interactive `<summary>`, badge contrast 3.78:1/4.1:1, `role=dialog` on `<form>`, destructive Reset/Clear without confirmation | Med | Real buttons, restructured replay rows, contrast tokens, confirmations | `1cdfc09` | axe-core: 0 serious/critical (light, dark, all dialogs, results) at 4 viewports; keyboard tests; suite fails on the old UI |
| 19 | Browser suite caught only page exceptions, so CSP violations / failed loads went unnoticed | Low | Console errors fail the suite | `1cdfc09` tools/verify_ui.cjs | suite run |
| 20 | `COUNCIL_LLM_TIMEOUT` defaulted to 300 s in one path and 180 s elsewhere/docs | Low | One 300 s default | `18b7540`, `e92eb33` | suite |
| 21 | Helpers looked the app up as `sys.modules["main"]`, absent when served as `council.main` | Low | Register `main` alias | `6d5c843` | subprocess lookup test |
| 22 | Trailing whitespace in 9 JS files from the earlier `dec98d4` refactor | Low | **Not fixed** (cosmetic; CI's `git diff --check` only checks uncommitted changes) | — | `git diff --check origin/main HEAD` clean for this work |

## 3. Commands executed and results

All on `d6b724a` unless noted. "Idle" means no concurrent model inference.

| Check | Command | Result |
|---|---|---|
| Baseline (before changes, `e31c38c`) | full battery | 213 pytest, 5 frontend, vendor, audits — all pass |
| Backend suite (idle) | `pytest tests/ -q --ignore=tests/eval` | **259 passed, 1 skipped** (the opt-in live Docker test), exit 0 |
| Backend suite under load | same, during live UAT | 258 passed, 1 failed: `test_simultaneous_admissions_and_responsive_health` subprocess import exceeded 300 s on a saturated CPU; assertions never ran; passes idle |
| Live Docker | `COUNCIL_TEST_DOCKER=1 pytest tests/test_tool_repl.py` | 13 passed; 0 leftover `council-sandbox-*` containers |
| Frontend | `node --test tests/frontend.test.cjs` | 6 passed |
| JS syntax | `node --check` on all UI/tool/UAT scripts | pass |
| Vendored libraries | `node tools/vendor_frontend.cjs --check` | DOMPurify, marked, vis-network byte-identical to pinned packages |
| Dependency audits | `npm audit` (tools/frontend), `pip-audit -r requirements.txt` | 0 vulnerabilities / no known vulnerabilities |
| Packaging | `python -m build`, `twine check --strict` | wheel + sdist PASSED; wheel (90 files) includes templates, scripts, styles, vendor assets + licenses, prompts (3), migrations (3), demo samples (11), `pdf_worker`, `council_env` |
| Installed-wheel smoke | UAT fast scenarios against the HEAD wheel | 11/11 pass (CLI, offline assets, health, catalog, preflight, validation, boundaries, secret-file exclusion, missing-model error, no tracebacks) |
| Browser, synthetic inference | `tools/verify_ui.cjs` against the installed HEAD wheel | pass at 1440, 768, 390, 320 px: overflow, dialogs, keyboard, focus return, axe (0 serious/critical), Markdown blocking, streaming, action items, no console errors |
| **Live UAT** (real Ollama `qwen2.5:3b`, installed wheel built at `1cdfc09`) | `tests/uat/run_uat.py --browser` | **22/22 pass**: core run with verdict (636 s), replay + redaction, feedback, export, chat, project review without `.env`, CLI history/delete, browser journey (443 s), `council ask` (762 s), `check_diff` hook (382 s), clean server log |
| Push gate (four commits + approved fix, `6814eeb`) | B01 + suites on an exact worktree build | B01 pass; 213 pytest; 6 frontend; pushed fast-forward `41cc3cf..6814eeb` |
| Ponytail audit | `tools/ponytail_audit.py` | advisory, exit 0; 9 notes: 5 files at 506–520 lines, complexity 16–19 in `_pick_roster`, `ingest_folder`, `build_project_graph`, class-level 28 in the middleware (sum of small methods) |

Timings for live runs were inflated by other work on the same CPU-only machine; an uncontended `qwen2.5:3b` council run took ~270 s.

## 4. Mocked, live, failed and blocked verification

- **Live (real systems):** Ollama inference across every UAT journey; real Chromium browser journey; Docker sandbox; Windows memory ceiling; installed-wheel server and CLI; GitHub push.
- **Synthetic / mocked:** backend unit tests stub LiteLLM and network boundaries (real SQLite); the four-viewport browser suite mocks inference and run history.
- **Failed during the audit, then fixed:** live U11 (verdict event), U12 (event loop blocked), B01 (Turbo race, then false preflight alert), and the commit gate for the four commits (B01 failed on that exact build, so the push included the fix after your approval).
- **Failed for environmental reasons:** one concurrency test under CPU saturation (passes idle). Recorded, not suppressed.
- **Blocked / not verified here:**
  - Linux `RLIMIT_AS` and macOS refusal paths are unit-tested only. This host is Windows.
  - GPU roster paths: there is no capable GPU (unit-tested).
  - End-to-end Python tool use by a cloud model: no cloud keys. The authorization and the sandbox were verified separately.
  - Authenticated LAN deployment over a real network: simulated with keyed remote clients in tests.
  - GitHub Actions results for the pushed commits: `gh` is not installed here; check the Actions tab.
  - The Docker image build was not run.

## 5. Remaining risks

- **CSP allows `'unsafe-inline'` scripts** because the UI uses ~50 inline event handlers. DOMPurify is the XSS defense; a sanitizer bypass would not be contained.
- **Redaction is pattern-based**; unusual credential formats pass through.
- **Pre-commit blocking depends on small-model judgment.** In UAT, `qwen2.5:3b` flagged an `os.system` injection but described it as SQL injection and the commit was allowed (risk below 8).
- **One shared API key**, no TLS of its own, no per-user audit trail (out of scope by design).
- **CPU-only performance** is inherent: ~2.5 tok/s; a council run is minutes.
- **macOS:** PDF extraction is refused unless the user opts out.
- **The 16 audit commits (`63d276a` … `d6b724a`) and this report are local and unpushed**, by your instruction.

## 6. Ratings (evidence-based, 1–10)

| Area | Rating | Basis |
|---|---|---|
| Security | **7** | Boundary checks before parsing, byte limits, atomic admission, execution-time tool authorization, isolated sandbox and PDF parsing, full-boundary redaction, CSP, safe config loading, all regression-tested; held back by `'unsafe-inline'`, pattern-based redaction, no third-party review or fuzzing |
| UI/UX | **7** | axe-clean (serious/critical), keyboard-operable, four viewports, confirmations, verdict card now works; native `alert/confirm`, slow CPU runs without progress ETA, model output quality varies |
| Performance | **6** | App-side stalls removed (catalog 2.8 s → 0.02 s, loop never blocked, bounded parsing); end-to-end speed is limited by CPU inference |
| Code quality | **7** | 259 backend + 6 frontend tests, 22 live UAT scenarios, small focused commits; some modules near complexity limits; legacy `_main_attr` indirection and pre-existing whitespace |
| Maintainability | **7** | Ownership and lifecycle documented; config and security docs current; settings still read at import time; sys.path-based module layout |
| Production readiness | **6** | Ready for its intended single-user local use; LAN use possible with the SECURITY.md checklist; not for public or multi-user hosting |

## 7. Requirements for higher readiness

1. Replace inline handlers with delegated listeners and drop `'unsafe-inline'` from `script-src`.
2. Run the browser suite and the live Docker test in CI (a Linux runner also covers `RLIMIT_AS`), plus a nightly UAT with a tiny model.
3. ~~Add deterministic checks to `check_diff`~~ — **done** (2026-10-24): `_static_diff_findings` in `cli.py` regex-scans added diff lines for `os.system`, `subprocess(...shell=True)`, `eval`/`exec`, unsafe `pickle`/`yaml.load`, and dynamic `__import__`, and force-blocks the commit regardless of the model's score. Line-level only, not AST-aware — a backstop, not a replacement for the model review.
4. Push the local audit commits after review, confirm CI is green, and verify the Docker image build.
5. Fuzz the upload, PDF and Markdown paths; get an external security review before any LAN deployment with sensitive data.
6. Add run progress/ETA and cancel feedback for CPU-only users.
