"""
Smoke tests for the MCP connection layer. These hit real endpoints but don't
run the full research pipeline (no LLM calls) — fast, and confirm the two
MCP subprocess servers (Tavily, GitHub) actually launch and connect.

Requires real API keys in .env (TAVILY_API_KEY, GITHUB_TOKEN) and Node.js
installed locally, since both MCP servers launch via `npx` subprocesses.

Run: pytest tests/test_mcp_health.py -v
"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_health_ok():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_mcp_servers_connect():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/api/health/mcp")
    assert resp.status_code == 200
    data = resp.json()
    assert data["tavily"]["status"] == "connected"
    assert data["github"]["status"] == "connected"
    assert data["total_connected"] == 2
    # Confirm the specific tool names the parsing logic in mcp_search.py
    # depends on are actually present — catches a future MCP server version
    # bump that silently renames a tool before it breaks the pipeline.
    assert "tavily_search" in data["tavily"]["tools"]
    assert "search_repositories" in data["github"]["tools"]
