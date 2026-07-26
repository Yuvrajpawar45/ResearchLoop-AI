from langchain_groq import ChatGroq

from app.config import settings


def get_llm(temperature: float = 0.2) -> ChatGroq:
    """Primary model. Wrap calls in try/except at the call site and fall back
    to get_fallback_llm() on a 429 from Groq's daily token cap — same pattern
    used in the other project, since Groq's free tier caps are shared and can
    hit mid-demo."""
    return ChatGroq(
        model=settings.llm_model,
        temperature=temperature,
        api_key=settings.groq_api_key,
    )


def get_fallback_llm(temperature: float = 0.2) -> ChatGroq:
    return ChatGroq(
        model=settings.fallback_llm_model,
        temperature=temperature,
        api_key=settings.groq_api_key,
    )


def _is_rate_limit_error(e: Exception) -> bool:
    return "rate_limit" in str(e).lower() or "429" in str(e)


async def call_with_fallback(prompt: str, temperature: float = 0.2) -> str:
    """
    Tries the primary model, falls back to the smaller model on a 429.

    NOTE: an earlier version of this function also retried the fallback
    model after a sleep if IT hit a 429 too. That made things worse under
    eval_harness.py load — waiting and retrying added latency without fixing
    the actual problem (~40 LLM calls per query from per-result scoring).
    The real fix was batching all of one sub-question's results into a
    single scoring call (see mcp_search.py's _score_batch), which cuts calls
    per query from ~40 to ~4-5. If the fallback model still 429s after that
    reduction, callers (mcp_search._score_batch) catch the exception and
    degrade gracefully to neutral scores rather than retrying blindly.
    """
    llm = get_llm(temperature)
    try:
        response = await llm.ainvoke(prompt)
        return response.content
    except Exception as e:
        if not _is_rate_limit_error(e):
            raise

    fallback = get_fallback_llm(temperature)
    response = await fallback.ainvoke(prompt)  # let this raise on failure — caller handles it
    return response.content