from app.state import ResearchState


async def broaden_query(state: ResearchState) -> dict:
    """
    Self-correction node. Fires only when aggregate.route_after_aggregate()
    decides evidence is too thin (see aggregate.py).

    Deliberately simple broadening strategy: re-query with the user's
    original, unmodified question instead of the narrower sub-questions —
    sub-questions are precise by design (definition/comparison/use-cases/
    limitations), which is exactly what makes them prone to returning too
    few results for a niche or very new topic. The plain original query is
    strictly broader.

    Known limitation, stated plainly: this is one fixed broadening strategy,
    not an LLM-driven query reformulation. A version that asks the LLM to
    rewrite the query based on *why* the first pass came up thin (too
    narrow? too niche? bad phrasing?) would be a stronger next step.
    """
    return {
        "pending_questions": [state["query"]],
        "retry_count": state["retry_count"] + 1,
    }
