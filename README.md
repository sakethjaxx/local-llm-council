# ⚖️ Universal Council Engine v3.0

A futuristic, local web application that convenes a dynamic panel of AI agents to debate, cross-review, and deliver verdicts on any topic—from software architecture sprints to startup pitch decks.

![Council Engine UI Preview](council_preview.png)

---

## 🚀 What's New in v3.0

- **Zero-Cost Web & PDF Scraper**: Paste any URL or `.pdf` link into the topic box. The backend automatically scrapes and extracts the text locally before feeding it to the council!
- **Chairman Web Search Tool**: If the council disputes a factual claim, the Chairman automatically queries DuckDuckGo for live internet data to break the tie.
- **Local MCP Client**: The engine natively connects to local Model Context Protocol (MCP) servers (like `code-review-graph`). If your topic mentions "codebase" or "repo", the agents will pull actual AST/Architecture data from your local machine.
- **Smart Phase 2**: Using local `sentence-transformers`, the engine calculates the cosine similarity of all Phase 1 analyses. If the council is in unanimous agreement, it skips the costly Phase 2 Cross-Review entirely to save you tokens!
- **Long-Term Graph Memory**: The backend extracts a Knowledge Graph of decisions from the Chairman and injects it into future sessions.

---

## ⚙️ Detailed Step-by-Step Setup

Follow these steps precisely to unlock the full power of the Universal Council on your local machine.

### Step 1: Clone and Enter the Repository
```bash
git clone https://github.com/sakethjaxx/local-llm-council.git
cd local-llm-council
```

### Step 2: Install Advanced Dependencies
The engine now uses local machine learning models (for Smart Phase 2) and local scrapers to save you money. Install the required Python packages:

```bash
# Core backend, Litellm, and UI server
pip install -r requirements.txt

# New v3.0 Dependencies (Scrapers, Embeddings, Memory, MCP)
pip install beautifulsoup4 httpx PyMuPDF duckduckgo-search sentence-transformers scikit-learn networkx mcp
```
*(Note: The first time you run a council session, `sentence-transformers` will automatically download a ~90MB embeddings model to your machine.)*

### Step 3: Configure OpenRouter Keys
We use **LiteLLM** to unify API calls to **OpenRouter**, giving you access to 100+ models (Llama 3, DeepSeek, Gemini, etc.) through one endpoint.

```bash
cp env.example .env
```
Edit your `.env` file and insert your OpenRouter key:
```ini
OPENROUTER_API_KEY=sk-or-v1-...
```

### Step 4: Configure Local RAG Injection & Codebase Graph (Optional)

The Universal Council has two powerful context-injection mechanisms:
1. **Long-Term Graph Memory**: Requires zero setup. The Council automatically extracts and saves decisions to `council_memory.json` locally, and injects them back into your future prompts as historical context.
2. **Local Codebase MCP Server**: If you want the Council to analyze your actual code files, you must configure the `code-review-graph` MCP server.
   
   *How to enable codebase analysis:*
   - Install the graph engine on your machine: `pip install code-review-graph`
   - Inside your code repository, run: `crg build` (this parses your code into a local database).
   - In the Universal Council web UI, simply mention the words `"codebase"` or `"repo"` in your topic (e.g., *"Review my codebase architecture"*). The Council backend will automatically spawn a local MCP `stdio` connection to `code-review-graph`, extract your codebase context, and inject it into the Council's RAG pipeline!

### Step 5: Launch the Council
Start the FastAPI server:
```bash
python main.py
```
1. Open your browser to **http://localhost:8765**.
2. **Build your seats** using the left panel (e.g., set the `openrouter/deepseek/deepseek-r1` model).
3. **Paste a topic or URL** (e.g., `https://react.dev/blog`) and watch the council scrape the page, debate the logic, skip Phase 2 if unanimous, and save the decision to its Long-Term Memory!

---

## 🛠️ Architecture Pipeline

1. **I/O Extraction**: Scrape URLs/PDFs locally.
2. **RAG Injection**: Pull from Local Knowledge Graph + Local MCP Server.
3. **Phase 1 (Analysis)**: Agents review independently.
4. **Smart Phase Check**: Compute Cosine Similarity. If > 0.88, skip to Phase 3.
5. **Phase 2 (Cross-Review)**: Agents critique peers (if disputed).
6. **Tool Phase**: Chairman queries DuckDuckGo if needed.
7. **Phase 3 (Verdict)**: Chairman delivers final synthesized decision.
8. **Memory Extraction**: Save outcome to Local Graph Database.
