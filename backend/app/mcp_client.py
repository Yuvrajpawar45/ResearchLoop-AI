"""
Sets up a MultiServerMCPClient connecting to the Tavily MCP server (web search)
and the official GitHub MCP server (repository search). Both servers are
launched as local subprocesses over stdio the first time tools are requested,
then reused for the lifetime of the app process.

Why MCP instead of calling the Tavily/GitHub REST APIs directly: tools are
exposed as standard LangChain BaseTool objects regardless of provider, so a
different search backend can be swapped in later (e.g. Brave Search MCP,
another code-search MCP) without touching any node code in graphs/.
The tradeoff is real: subprocess-based MCP servers add startup latency and
another moving part to deploy/monitor, which is why some solo projects skip
MCP entirely and call REST APIs directly. Here we're taking that tradeoff on
purpose, to standardize the tool interface.
"""

from langchain_mcp_adapters.client import MultiServerMCPClient

from app.config import settings

_client: MultiServerMCPClient | None = None
_tools_cache = None


def get_mcp_client() -> MultiServerMCPClient:
    global _client
    if _client is None:
        _client = MultiServerMCPClient(
            {
                "tavily": {
                    "command": "npx",
                    "args": ["-y", "tavily-mcp"],
                    "transport": "stdio",
                    "env": {"TAVILY_API_KEY": settings.tavily_api_key},
                },
                "github": {
                    "command": "npx",
                    "args": ["-y", "@modelcontextprotocol/server-github"],
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
    Cached after first call — call reset_tools_cache() if servers restart."""
    global _tools_cache
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