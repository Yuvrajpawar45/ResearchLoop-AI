"""
Retrieval/quality eval harness for ResearchLoop AI.

Same purpose as the retrieval eval suite behind the Indian Legal Assistant's
"~90% accuracy" line — run a fixed set of test queries against the real
pipeline and compute a concrete, defensible number instead of eyeballing a
few demo runs.

Requires the backend running locally (or set EVAL_BASE_URL to point at a
deployed instance) with real API keys, since this makes real Groq/Tavily/
GitHub calls for every query — running the full 20-query set costs real
API quota, budget for that.

Run:
    cd backend
    python -m eval.eval_harness

Output: prints a summary to stdout AND writes eval/results.json with the
full per-query breakdown, so the numbers are reproducible and inspectable,
not just a claimed percentage.
"""

import asyncio
import json
import os
import re
import time

import httpx

BASE_URL = os.getenv("EVAL_BASE_URL", "http://localhost:8000")
RELEVANCE_THRESHOLD = 0.7
MIN_CITATIONS = 2  # a report citing fewer than this doesn't really "answer" the query

TEST_QUERIES = [
    "What is Model Context Protocol?",
    "How does RAG work in production LLM systems?",
    "Best vector databases for AI applications 2026",
    "What is LangGraph and how does it differ from LangChain?",
    "How do AI agents use tool calling?",
    "What is retrieval-augmented generation used for?",
    "Compare FAISS vs Qdrant for vector search",
    "What is the difference between fine-tuning and RAG?",
    "How does Groq achieve fast LLM inference?",
    "What are the security risks of MCP servers?",
    "How do multi-agent systems coordinate tasks?",
    "What is a LangGraph StateGraph?",
    "How does semantic search differ from keyword search?",
    "What is prompt engineering?",
    "How do you evaluate a RAG pipeline?",
    "What is the role of embeddings in search?",
    "How does the Tavily search API work?",
    "What are common failure modes in agentic AI systems?",
    "How does citation grounding reduce hallucination?",
    "What is the tradeoff between sequential and parallel agent execution?",
]


def count_citations(report: str) -> int:
    """Counts unique [n] citation markers in the report."""
    return len(set(re.findall(r"\[(\d+)\]", report)))


async def run_query(client: httpx.AsyncClient, query: str) -> dict:
    start = time.time()
    try:
        resp = await client.post(f"{BASE_URL}/api/research", json={"query": query}, timeout=120)
        elapsed = time.time() - start
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        return {"query": query, "error": str(e), "elapsed_sec": round(time.time() - start, 1)}

    sources = data.get("sources", [])
    scores = [s["relevance_score"] for s in sources]
    above_threshold = [s for s in scores if s >= RELEVANCE_THRESHOLD]
    citations = count_citations(data.get("report", ""))

    return {
        "query": query,
        "elapsed_sec": round(elapsed, 1),
        "source_count": len(sources),
        "avg_relevance": round(sum(scores) / len(scores), 3) if scores else 0.0,
        "pct_above_threshold": round(len(above_threshold) / len(scores) * 100, 1) if scores else 0.0,
        "citation_count": citations,
        "report_length": len(data.get("report", "")),
        "retries_used": data.get("retries_used", 0),
        "passed": citations >= MIN_CITATIONS and len(sources) > 0,
    }


async def main():
    print(f"Running {len(TEST_QUERIES)} eval queries against {BASE_URL} ...\n")
    results = []
    async with httpx.AsyncClient() as client:
        for i, q in enumerate(TEST_QUERIES, 1):
            print(f"[{i}/{len(TEST_QUERIES)}] {q}")
            result = await run_query(client, q)
            results.append(result)
            status = "PASS" if result.get("passed") else ("ERROR" if "error" in result else "FAIL")
            print(f"    -> {status}")

    valid = [r for r in results if "error" not in r]
    errors = [r for r in results if "error" in r]
    passed = sum(1 for r in valid if r["passed"])
    total_sources = sum(r["source_count"] for r in valid)
    # Weighted average across all sources from all queries, not an average of
    # per-query percentages (which would over-weight low-source queries).
    total_above_weighted = sum(r["pct_above_threshold"] * r["source_count"] / 100 for r in valid if r["source_count"])
    retries_fired = sum(1 for r in valid if r.get("retries_used", 0) > 0)

    summary = {
        "total_queries": len(TEST_QUERIES),
        "successful_runs": len(valid),
        "errored_runs": len(errors),
        "queries_passed": passed,
        "pass_rate_pct": round(passed / len(valid) * 100, 1) if valid else 0.0,
        "overall_pct_sources_above_relevance_threshold": (
            round(total_above_weighted / total_sources * 100, 1) if total_sources else 0.0
        ),
        "avg_sources_per_query": round(total_sources / len(valid), 1) if valid else 0.0,
        "avg_elapsed_sec": round(sum(r["elapsed_sec"] for r in valid) / len(valid), 1) if valid else 0.0,
        "self_correction_fired_on_n_queries": retries_fired,
    }

    output = {"summary": summary, "results": results}
    os.makedirs(os.path.dirname(__file__) or ".", exist_ok=True)
    results_path = os.path.join(os.path.dirname(__file__), "results.json")
    with open(results_path, "w") as f:
        json.dump(output, f, indent=2)

    print("\n=== SUMMARY ===")
    for k, v in summary.items():
        print(f"{k}: {v}")
    print(f"\nFull per-query results written to {results_path}")


if __name__ == "__main__":
    asyncio.run(main())
