# ⚖ LLM Council — Local Multi-Model Sprint Decision Engine

A local web app that convenes a panel of Claude, GPT-4o, and Gemini to analyze
your sprint plan, cross-review each other's opinions, and deliver a final
chairman verdict via GPT-4o-mini.

---

## Architecture

```
Sprint Input (text / image)
        │
        ▼
┌───────────────────────────────────────┐
│  Phase 1 — Independent Analysis       │  (parallel)
│  ⚡ Claude Sonnet                      │
│  🔮 GPT-4o                            │
│  ✦  Gemini Flash                      │
└───────────────────────────────────────┘
        │
        ▼
┌───────────────────────────────────────┐
│  Phase 2 — Cross-Review               │  (each reviews the other two)
│  ⚡ Claude   reviews GPT + Gemini      │
│  🔮 GPT-4o  reviews Claude + Gemini   │
│  ✦  Gemini  reviews Claude + GPT      │
└───────────────────────────────────────┘
        │
        ▼
┌───────────────────────────────────────┐
│  Phase 3 — Chairman's Verdict         │
│  👑 GPT-4o-mini reads everything      │
│     and delivers the final decision   │
└───────────────────────────────────────┘
```

---

## Setup

### 1. Install dependencies

```bash
cd llm_council
pip install -r requirements.txt
```

### 2. Configure API keys

```bash
cp .env.example .env
# Edit .env and fill in your keys:
# ANTHROPIC_API_KEY=sk-ant-...
# OPENAI_API_KEY=sk-...
# GEMINI_API_KEY=AIza...
```

### 3. Run

```bash
python main.py
```

Open **http://localhost:8765** in your browser.

---

## Usage

1. **Paste your sprint overview** — plain text, markdown, or JSON ticket list
2. **Optionally upload a graph/screenshot** — Jira board, burndown chart, etc.
3. Click **Convene Council**
4. Watch the three-phase council session stream in real-time

---

## Tech Stack

| Component | Tech |
|-----------|------|
| Backend   | FastAPI + uvicorn (async) |
| Streaming | Server-Sent Events (SSE) |
| Claude    | Anthropic SDK (claude-sonnet-4) |
| GPT-4o    | OpenAI SDK (gpt-4o + gpt-4o-mini) |
| Gemini    | google-generativeai (gemini-2.0-flash) |
| Frontend  | Vanilla JS, no framework |

---

## Extending

- **Add a new council member**: Add an entry to `MEMBER_CONFIG` in `orchestrator.py`,
  implement `_[model]_analyze()` and `_[model]_review()`, and include in `asyncio.gather()`.
- **Custom chairman**: Change `MEMBER_CONFIG["chairman"]["model"]` to any OpenAI model.
- **Persist results**: Add SQLite/Redis output after the `done` event in `orchestrator.py`.
- **Slack output**: Post chairman verdict to Slack via webhook after Phase 3.
