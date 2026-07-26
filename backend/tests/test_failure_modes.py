"""
Failure-mode tests — confirm the API rejects bad input cleanly instead of
either crashing with a 500 or silently 200'ing with a garbage response.

Run: pytest tests/test_failure_modes.py -v
"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_empty_query_rejected():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post("/api/research", json={"query": ""})
    # Pydantic's min_length=3 on ResearchRequest.query should reject this
    # before it ever reaches the graph.
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_too_short_query_rejected():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post("/api/research", json={"query": "ok"})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_oversized_query_rejected():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post("/api/research", json={"query": "x" * 600})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_missing_query_field_rejected():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post("/api/research", json={})
    assert resp.status_code == 422
