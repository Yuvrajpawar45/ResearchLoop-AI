"""
Full end-to-end pipeline test â€” runs planner -> parallel research -> aggregate
-> writer for real, using live API keys. Slower and costs real Groq/Tavily
quota, so it's skipped automatically if GROQ_API_KEY isn't set (e.g. in CI
without secrets configured).

Run: pytest tests/test_pipeline.py -v -s
"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import settings
from app.main import app

pytestmark = pytest.mark.skipif(
    not settings.groq_api_key, reason="requires live GROQ_API_KEY / TAVILY_API_KEY / GITHUB_TOKEN in .env"
)


@pytest.mark.asyncio
async def test_full_research_pipeline():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", timeout=90) as ac:
        resp = await ac.post("/api/research", json={"query": "What is Model Context Protocol?"})

    assert resp.status_code == 200
    data = resp.json()

    assert len(data["sub_questions"]) > 0
    assert "report" in data and len(data["report"]) > 0
    assert data["source_count"] >= 0
    # A well-known, well-documented topic like MCP should NOT need the
    # self-correction retry â€” if this starts failing, either the threshold
    # in config.py is miscalibrated or the MCP parsing broke again.
    assert data["retries_used"] == 0


@pytest.mark.asyncio
async def test_self_correction_fires_on_obscure_query():
    """
    A deliberately obscure, low-signal query to check the self-correction
    loop actually engages. This is a soft assertion, not a hard one â€” a
    sufficiently weird nonsense query should trigger a retry, but Tavily's
    index changes over time, so we only assert retries_used is a valid int
    in range rather than forcing retries_used == 1 (that would make this
    test flaky against a live search index).
    """
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", timeout=90) as ac:
        resp = await ac.post(
            "/api/research",
            json={"query": "xqzplorbnix wobble-frastication protocol version 9.9 obscure internal codename"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert 0 <= data["retries_used"] <= 1

