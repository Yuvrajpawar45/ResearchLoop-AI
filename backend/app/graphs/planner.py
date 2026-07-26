import json

from app.config import settings
from app.llm import call_with_fallback
from app.state import ResearchState

PLANNER_PROMPT = """You are a research planner. Break the following query into \
exactly {n} focused sub-questions that together give a complete picture: \
one covering the core definition/concept, one covering comparisons or \
alternatives, one covering real-world use cases, and one covering \
limitations or open problems.

Query: {query}

Respond with ONLY a JSON array of {n} strings, nothing else."""


async def decompose_query(state: ResearchState) -> dict:
    query = state["query"]
    prompt = PLANNER_PROMPT.format(query=query, n=settings.max_sub_questions)

    try:
        raw = await call_with_fallback(prompt, temperature=0.1)
        cleaned = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        try:
            sub_questions = json.loads(cleaned)
        except json.JSONDecodeError:
            # Fallback: treat each non-empty line as a sub-question if the model
            # didn't return clean JSON
            sub_questions = [line.strip("-• ") for line in cleaned.splitlines() if line.strip()]
        if not sub_questions:
            raise ValueError("planner returned no sub-questions")
    except Exception:
        # Graceful degradation: if the planner LLM call fails entirely (rate
        # limit, malformed response, etc.), don't crash the whole request —
        # fall back to researching the raw query as a single "sub-question".
        # Less thorough than 4 focused angles, but the pipeline still
        # produces a real result instead of a 500.
        sub_questions = [query]

    sub_questions = sub_questions[: settings.max_sub_questions]
    return {
        "sub_questions": sub_questions,
        "pending_questions": sub_questions,
        "retry_count": 0,
    }