import json
import re

from app.config import settings
from app.llm import call_with_fallback
from app.mcp_client import get_tools
from app.state import ResearchState, SearchResult

SCORER_PROMPT = """Rate how relevant this search result is to the sub-question \
on a scale of 0.0 to 1.0. Respond with ONLY a number.

Sub-question: {sub_question}
Result title: {title}
Result snippet: {snippet}"""

# Tavily's MCP server returns ONE text block containing all results formatted as
# repeated "Title: ...\nURL: ...\nContent: ..." entries, not structured JSON per
# result. Confirmed via /api/debug/tool-raw — this regex splits that text back
# into individual results.
_TAVILY_ENTRY_RE = re.compile(
    r"Title:\s*(.*?)\nURL:\s*(.*?)\nContent:\s*(.*?)(?=\n\nTitle:|\Z)", re.DOTALL
)


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
        # blocks" (dicts with a 'type' key), not a list of result dicts —
        # confirmed via /api/debug/tool-raw. Extract the actual text first.
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


async def _score_result(sub_question: str, title: str, snippet: str) -> float:
    # Tavily's raw Content field can be thousands of words — truncate before
    # sending to the LLM or it blows past Groq's per-minute token limit
    # (hit a 413 "Request too large" error on the full-length version).
    snippet = snippet[:500]
    title = title[:200]
    prompt = SCORER_PROMPT.format(sub_question=sub_question, title=title, snippet=snippet)
    raw = await call_with_fallback(prompt, temperature=0.0)
    try:
        return max(0.0, min(1.0, float(raw.strip())))
    except ValueError:
        return 0.5  # neutral default if the model returns something unparseable


async def research_sub_questions(state: ResearchState) -> dict:
    """
    Runs sub-questions ONE AT A TIME against the MCP tools (Tavily web search,
    GitHub repo search), then LLM-scores each result for relevance.

    Known limitation, stated plainly: this loop is sequential, not parallel.
    A parallel version using LangGraph's Send() API to fan out sub-questions
    concurrently is a real, scoped next step — not implemented here yet.
    """
    tools = await get_tools()
    all_results: list[SearchResult] = []

    for sub_q in state["sub_questions"]:
        web_hits = await _run_tool(tools, "tavily_search", sub_q)
        repo_hits = await _run_tool(tools, "search_repositories", sub_q)

        for hit in web_hits[: settings.sources_per_query]:
            title = hit.get("title", "")
            snippet = hit.get("content", hit.get("snippet", ""))
            score = await _score_result(sub_q, title, snippet)
            all_results.append(
                SearchResult(
                    title=title,
                    url=hit.get("url", ""),
                    snippet=snippet,
                    source="tavily",
                    relevance_score=score,
                )
            )

        for hit in repo_hits[: settings.sources_per_query]:
            title = hit.get("full_name", hit.get("name", ""))
            snippet = hit.get("description", "") or ""
            score = await _score_result(sub_q, title, snippet)
            all_results.append(
                SearchResult(
                    title=title,
                    url=hit.get("html_url", ""),
                    snippet=snippet,
                    source="github",
                    relevance_score=score,
                )
            )

    scored = [r for r in all_results if r["relevance_score"] >= settings.min_relevance_score]
    scored.sort(key=lambda r: r["relevance_score"], reverse=True)

    # dedupe by URL
    seen = set()
    deduped = []
    for r in scored:
        if r["url"] not in seen:
            seen.add(r["url"])
            deduped.append(r)

    return {"search_results": all_results, "scored_sources": deduped}