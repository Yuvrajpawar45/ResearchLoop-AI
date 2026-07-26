"""
Shared search + scoring helpers used by graphs/research_worker.py.

Moved here (out of graphs/research.py) so the self-correction loop's
broadened-query pass and the original per-sub-question pass can both call
the same tested parsing logic without duplicating it.
"""

import asyncio
import json
import re

from app.config import settings
from app.llm import call_with_fallback
from app.state import SearchResult

BATCH_SCORER_PROMPT = """Rate how relevant each of the following search results is \
to the sub-question, on a scale of 0.0 to 1.0.

Sub-question: {sub_question}

Results:
{numbered_results}

Respond with ONLY a JSON array of {n} numbers between 0.0 and 1.0, in the exact \
same order as the results above, and nothing else. Example: [0.8, 0.3, 0.9]"""

# Tavily's MCP server returns ONE text block containing all results formatted as
# repeated "Title: ...\nURL: ...\nContent: ..." entries, not structured JSON per
# result. Confirmed via /api/debug/tool-raw during initial integration — this
# regex splits that text back into individual results.
_TAVILY_ENTRY_RE = re.compile(
    r"Title:\s*(.*?)\nURL:\s*(.*?)\nContent:\s*(.*?)(?=\n\nTitle:|\Z)", re.DOTALL
)

# A light safety net, not the primary fix — batching (below) already cuts
# per-query LLM calls from ~40 to ~1 per sub-question (~4-5 total), which is
# what actually resolved the Groq TPM rate-limit failures seen under
# eval_harness.py's back-to-back load. This just guards against still
# running too many sub-questions' batch calls at once.
_llm_semaphore = asyncio.Semaphore(settings.max_concurrent_llm_calls)


def _parse_tavily_text(text: str) -> list[dict]:
    matches = _TAVILY_ENTRY_RE.findall(text)
    return [
        {"title": title.strip(), "url": url.strip(), "content": content.strip()}
        for title, url, content in matches
    ]


async def _run_tool(tools, tool_name: str, query: str) -> list[dict]:
    tool = next((t for t in tools if t.name == tool_name), None)
    if tool is None:
        return []
    try:
        result = await tool.ainvoke({"query": query})

        # Both Tavily and GitHub's MCP servers return a list of MCP "content
        # blocks" (dicts with a 'type' key), not a list of result dicts.
        if isinstance(result, list) and result and isinstance(result[0], dict) and "type" in result[0]:
            text = "\n".join(block.get("text", "") for block in result if block.get("type") == "text")
            if tool_name == "tavily_search":
                return _parse_tavily_text(text)
            # GitHub's block text is usually a JSON array or a
            # {"total_count":.., "items":[...]} object as a string.
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                return []
            if isinstance(parsed, dict):
                return parsed.get("items", [])
            return parsed if isinstance(parsed, list) else []

        if isinstance(result, str):
            return json.loads(result) if result.strip().startswith("[") else []
        return result if isinstance(result, list) else result.get("results", [])
    except Exception:
        return []


async def _score_batch(sub_question: str, items: list[dict]) -> list[float]:
    """
    Scores ALL results for one sub-question in a SINGLE LLM call, instead of
    one call per result. This is the real fix for the Groq TPM rate-limit
    failures seen under eval_harness.py — with 4 parallel sub-questions each
    previously making ~10 individual scoring calls, a single query could
    fire ~40 near-simultaneous LLM calls. Batching cuts that to ~1 call per
    sub-question (~4-5 per full query).

    Truncates each item's snippet before building the prompt, same reason
    as before — Tavily's raw Content field can be thousands of words.
    """
    if not items:
        return []

    numbered = "\n".join(
        f"{i+1}. Title: {item['title'][:200]}\n   Snippet: {item['snippet'][:400]}"
        for i, item in enumerate(items)
    )
    prompt = BATCH_SCORER_PROMPT.format(sub_question=sub_question, numbered_results=numbered, n=len(items))

    try:
        async with _llm_semaphore:
            raw = await call_with_fallback(prompt, temperature=0.0)
        cleaned = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        scores = json.loads(cleaned)
        if not isinstance(scores, list):
            raise ValueError("expected a JSON list")
        # Defensively pad/truncate in case the model returns the wrong count
        # rather than crashing the whole sub-question's results.
        scores = [max(0.0, min(1.0, float(s))) for s in scores][: len(items)]
        while len(scores) < len(items):
            scores.append(0.5)
        return scores
    except Exception:
        # Graceful degradation: if the batch call fails entirely (still
        # rate-limited even after llm.py's fallback+retry, or a malformed
        # response), score everything neutrally rather than raising and
        # failing the whole /api/research request over one sub-question.
        return [0.5] * len(items)


async def gather_and_score(tools, sub_question: str) -> list[SearchResult]:
    """Runs one sub-question against Tavily + GitHub MCP tools and scores
    every result in ONE batched LLM call (see _score_batch). Used by
    research_worker.research_one for each parallel fan-out branch, and again
    for the broadened query on a self-correction retry."""
    web_hits = await _run_tool(tools, "tavily_search", sub_question)
    repo_hits = await _run_tool(tools, "search_repositories", sub_question)

    items = []
    for hit in web_hits[: settings.sources_per_query]:
        items.append(
            {
                "title": hit.get("title", ""),
                "snippet": hit.get("content", hit.get("snippet", "")),
                "url": hit.get("url", ""),
                "source": "tavily",
            }
        )
    for hit in repo_hits[: settings.sources_per_query]:
        items.append(
            {
                "title": hit.get("full_name", hit.get("name", "")),
                "snippet": hit.get("description", "") or "",
                "url": hit.get("html_url", ""),
                "source": "github",
            }
        )

    scores = await _score_batch(sub_question, items)

    return [
        SearchResult(
            title=item["title"],
            url=item["url"],
            snippet=item["snippet"],
            source=item["source"],
            relevance_score=score,
        )
        for item, score in zip(items, scores)
    ]