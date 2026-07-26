from app.llm import call_with_fallback
from app.state import ResearchState

WRITER_PROMPT = """Write a structured markdown research report answering: {query}

Use ONLY the numbered sources below. Cite sources inline as [1], [2] etc. \
Include an Executive Summary, Key Findings (bullets), and end with a Sources \
list mapping each number to its URL.

Sources:
{sources_block}
"""


async def synthesize_report(state: ResearchState) -> dict:
    sources = state["scored_sources"]
    sources_block = "\n".join(
        f"[{i+1}] {s['title']} — {s['snippet'][:200]} ({s['url']})"
        for i, s in enumerate(sources)
    )

    if not sources_block:
        return {"report": "No sources met the relevance threshold. Try rephrasing the query."}

    prompt = WRITER_PROMPT.format(query=state["query"], sources_block=sources_block)
    try:
        report = await call_with_fallback(prompt, temperature=0.3)
    except Exception:
        # Graceful degradation: if the Writer's LLM call fails (rate limit,
        # etc.), don't crash the whole request — return the raw ranked
        # source list instead of a synthesized report. Less polished, but
        # the person still gets real, usable results instead of a 500.
        report = (
            "**Report synthesis temporarily unavailable — showing ranked sources instead:**\n\n"
            + sources_block
        )
    return {"report": report}