"""
Sets up a MultiServerMCPClient connecting to the Tavily MCP server (web search)
and the official GitHub MCP server (repository search).

Both servers are installed GLOBALLY at Docker build time (see backend/
Dockerfile) and launched here by calling their installed binaries directly —
NOT via `npx -y <package>`. Runtime npx downloads caused a production
failure: parallel Send() research branches racing to npx-install into the
same cache directory simultaneously corrupted it permanently. Baking the
packages into the image at build time removes runtime downloading (and that
whole class of bug) entirely.

For LOCAL development without rebuilding the Docker image, `npm install -g
tavily-mcp @modelcontextprotocol/server-github` once on your machine achieves
the same effect — after that, `tavily-mcp` and `mcp-server-github` are on
your PATH directly, same as inside the container.

Why MCP instead of calling the Tavily/GitHub REST APIs directly: tools are
exposed as standard LangChain BaseTool objects regardless of provider, so a
different search backend can be swapped in later (e.g. Brave Search MCP,
another code-search MCP) without touching any node code in graphs/.
The tradeoff is real: subprocess-based MCP servers add startup latency and
another moving part to deploy/monitor, which is why some solo projects skip
MCP entirely and call REST APIs directly. Here we're taking that tradeoff on
purpose, to standardize the tool interface.
"""

import asyncio

from langchain_mcp_adapters.client import MultiServerMCPClient

from app.config import settings

_client: MultiServerMCPClient | None = None
_tools_cache = None
# Kept even after removing npx: still useful in case get_tools() is ever
# called concurrently before the first result is cached — avoids redundant
# subprocess spawning either way.
_tools_lock = asyncio.Lock()


def get_mcp_client() -> MultiServerMCPClient:
    global _client
    if _client is None:
        _client = MultiServerMCPClient(
            {
                "tavily": {
                    "command": "tavily-mcp",
                    "args": [],
                    "transport": "stdio",
                    "env": {"TAVILY_API_KEY": settings.tavily_api_key},
                },
                "github": {
                    "command": "mcp-server-github",
                    "args": [],
                    "transport": "stdio",
                    "env": {
                        "GITHUB_PERSONAL_ACCESS_TOKEN": settings.github_token
                    },
                },
            }
        )
    return _client


async def get_tools():
    """Returns LangChain BaseTool objects for all connected MCP servers.
    Cached after first call — call reset_tools_cache() if servers restart.
    Double-checked locking: cheap fast path once cached, but the FIRST call
    (however many concurrent callers hit it) only actually triggers one
    real client.get_tools() call — see _tools_lock comment above."""
    global _tools_cache
    if _tools_cache is not None:
        return _tools_cache
    async with _tools_lock:
        if _tools_cache is None:
            client = get_mcp_client()
            _tools_cache = await client.get_tools()
    return _tools_cache


async def get_server_status() -> dict:
    """Used by the /api/health/mcp endpoint. Returns per-server connection
    status and the tool names each server exposes."""
    client = get_mcp_client()
    status = {}
    for server_name in ("tavily", "github"):
        try:
            async with client.session(server_name) as session:
                tools_result = await session.list_tools()
                status[server_name] = {
                    "status": "connected",
                    "tools": [t.name for t in tools_result.tools],
                }
        except Exception as e:
            status[server_name] = {"status": "error", "detail": str(e)}
    return status