# 🔬 ResearchLoop AI

Autonomous research agent: decomposes a question into sub-questions, searches the live web (Tavily MCP) and GitHub (GitHub MCP) for each one, LLM-scores every result for relevance, and synthesizes a cited markdown report — with live progress streamed to the frontend over SSE.

## Architecture

```
User Query
    │
    ▼
┌─────────────────────────────────────────┐
│           FastAPI Backend                │
│   POST /api/research (sync, rate-limited)│
│   POST /api/research/stream (SSE)         │
└───────────────────┬─────────────────────┘
                     ▼
┌─────────────────────────────────────────┐
│        LangGraph StateGraph              │
│                                           │
│  planner  → decompose_query               │
│      │       → sub_questions: [...]       │
│      ▼                                   │
│  [Send() fan-out — PARALLEL]              │
│      ├─ research_one (sub-q 1)            │
│      ├─ research_one (sub-q 2)            │
│      ├─ research_one (sub-q 3)            │
│      └─ research_one (sub-q 4)            │
│      │       (merged via operator.add)     │
│      ▼                                   │
│  aggregate → dedupe + filter + rank        │
│      │       → scored_sources: [...]       │
│      ▼                                   │
│  ┌─ too few sources? ─┐                  │
│  │                    │                  │
│  ▼ yes                ▼ no               │
│  broaden          writer → synthesize      │
│  (retry once,          report             │
│   re-fan-out)     │       → report: "..." │
│  └───────┘        │                      │
└───────────────────┼─────────────────────┘
                     │
              ┌──────┴──────┐
              ▼             ▼
        Tavily MCP     GitHub MCP
       (web search)   (repo search)
```

## Self-correction loop

If `aggregate` ends up with fewer than `min_sources_threshold` (default: 3) scored sources, the graph routes to `broaden` instead of `writer`. `broaden` re-queries with the original, unmodified user question (broader than any sub-question by design) and increments `retry_count`, capped by `max_retries` (default: 1) so a genuinely low-signal query can't loop forever.

**Honest limitation:** the broadening strategy is fixed (fall back to the original query), not an LLM-driven reformulation of *why* the first pass came up thin. A stronger version would ask the LLM to diagnose the failure (too narrow? too niche? bad phrasing?) and rewrite accordingly.

## Testing

```bash
cd backend
pytest tests/test_mcp_health.py -v      # MCP connection smoke tests, no LLM calls
pytest tests/test_failure_modes.py -v   # input validation, no API calls
pytest tests/test_pipeline.py -v -s     # full pipeline, requires live API keys, costs quota
```

## Evaluation

```bash
cd backend
python -m eval.eval_harness
```

Runs 20 fixed test queries against the live pipeline and computes: % of sources scoring above a 0.7 relevance threshold, average sources per query, citation count per report, and how often the self-correction loop fires. Writes full per-query results to `eval/results.json` — the summary numbers are reproducible, not just claimed.

## Why MCP

Tools connect through `langchain-mcp-adapters` to the Tavily MCP server and the official GitHub MCP server, rather than calling their REST APIs directly. This means a different search or code-search provider can be swapped in later without touching any node logic in `app/graphs/`.

The honest tradeoff: MCP servers run as local subprocesses, which adds startup latency and one more moving part to deploy and monitor compared to a direct API call. That cost is worth it here because the goal is a swappable, standardized tool layer — not because MCP is strictly necessary for a single search integration.

## Known limitations (stated plainly, not hidden)

- **Self-correction broadening is a fixed strategy** (fall back to the original query), not an LLM-driven reformulation. See "Self-correction loop" above.
- **LLM-based relevance scoring** costs one extra Groq call per search result. On Groq's free tier this is the most likely rate-limit pressure point — the fallback model (`llama-3.1-8b-instant`) kicks in automatically on a 429.
- **No vector DB / no persistent memory** — each query is stateless; there's no session history yet.
- **CORS is now an explicit allowlist**, not `*` — add your deployed frontend's origin to `ALLOWED_ORIGINS` once you have one, rather than widening it back to `*`.
- **Rate limiting is per-IP, in-memory** (via slowapi) — resets on server restart and doesn't share state across multiple server instances. Fine for a portfolio deploy, not for production scale.

## Setup

### 1. Get free API keys
| Service | URL | Free tier |
|---|---|---|
| Groq | console.groq.com | Fast, generous free tier |
| Tavily | app.tavily.com | 1,000 searches/month |
| GitHub Token | github.com/settings/tokens | Free — needs `public_repo` + `read:user` |

### 2. Backend
```bash
cd backend
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env       # fill in your keys
uvicorn app.main:app --reload --port 8000
```

MCP servers launch via `npx`, so **Node.js 18+ must be installed locally and on your deploy target** (see `railway.toml` — this is the exact kind of thing that silently breaks a deploy if skipped).

### 3. Frontend
Edit `API_BASE` in `frontend/index.html` to point at your deployed (or local) backend, then open it directly in a browser — no build step.

### 4. Deploy
- **Backend → Railway**: push this repo, set root directory to `backend`, add your three env vars, Railway reads `railway.toml`.
- **Frontend → Netlify/Vercel**: drag the `frontend/` folder in, or connect the repo with `frontend` as the publish directory.

**Before you consider this "deployed"**: actually open the live frontend URL in an incognito window and run a real query. A demo that only works against `localhost` is worse than no demo — it fails the first time someone you're interviewing with clicks it.

## Project structure

```
ResearchLoop-AI/
├── backend/
│   ├── app/
│   │   ├── graphs/
│   │   │   ├── planner.py        # decompose_query node
│   │   │   ├── research_worker.py# research_one node — ONE Send() fan-out branch
│   │   │   ├── aggregate.py      # dedupe/filter/rank + self-correction router
│   │   │   ├── broaden.py        # self-correction retry node
│   │   │   └── writer.py         # synthesize_report node
│   │   ├── routers/
│   │   │   ├── health.py         # /api/health, /api/health/mcp
│   │   │   └── research.py       # /api/research, /api/research/stream (SSE, rate-limited)
│   │   ├── config.py
│   │   ├── limiter.py            # shared slowapi Limiter instance
│   │   ├── llm.py                # Groq client + fallback-on-429 logic
│   │   ├── mcp_client.py         # MultiServerMCPClient setup
│   │   ├── mcp_search.py         # shared Tavily/GitHub search + scoring helpers
│   │   ├── state.py              # ResearchState TypedDict
│   │   ├── graph_builder.py      # wires nodes, Send() fan-out, self-correction edge
│   │   └── main.py               # FastAPI app + locked-down CORS + rate limiter
│   ├── tests/
│   │   ├── test_mcp_health.py    # MCP connection smoke tests
│   │   ├── test_pipeline.py      # full pipeline + self-correction integration test
│   │   └── test_failure_modes.py # input validation tests
│   ├── eval/
│   │   └── eval_harness.py       # 20-query retrieval/quality eval, writes results.json
│   ├── requirements.txt
│   ├── pytest.ini
│   ├── railway.toml
│   └── .env.example
└── frontend/
    ├── index.html                 # landing page + live SSE demo
    └── netlify.toml               # Netlify deploy config
```
