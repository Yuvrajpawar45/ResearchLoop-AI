from app.config import settings
from app.state import ResearchState


async def aggregate_sources(state: ResearchState) -> dict:
    """
    Runs once after ALL parallel research_one() branches for the current
    round finish (LangGraph waits for the full fan-out before continuing).
    Filters by relevance threshold, dedupes by URL, and ranks.

    NOTE: on a self-correction retry, search_results contains BOTH the
    original round's results AND the broadened round's results (operator.add
    accumulates across rounds) — so a retry re-evaluates everything gathered
    so far, not just the new broadened pass.
    """
    all_results = state["search_results"]

    scored = [r for r in all_results if r["relevance_score"] >= settings.min_relevance_score]
    scored.sort(key=lambda r: r["relevance_score"], reverse=True)

    seen = set()
    deduped = []
    for r in scored:
        if r["url"] not in seen:
            seen.add(r["url"])
            deduped.append(r)

    return {"scored_sources": deduped}


def route_after_aggregate(state: ResearchState) -> str:
    """
    Self-correction trigger. If we ended up with too few relevant sources
    and haven't already retried settings.max_retries times, loop back to
    broaden the query instead of letting the Writer synthesize a thin
    report off a handful of weak sources.
    """
    too_few_sources = len(state["scored_sources"]) < settings.min_sources_threshold
    retries_left = state["retry_count"] < settings.max_retries

    if too_few_sources and retries_left:
        return "broaden"
    return "writer"
