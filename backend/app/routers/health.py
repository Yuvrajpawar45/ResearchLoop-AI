from fastapi import APIRouter

from app.mcp_client import get_server_status

router = APIRouter()


@router.get("/api/health")
async def health():
    return {"status": "ok", "service": "researchloop-ai"}


@router.get("/api/health/mcp")
async def health_mcp():
    status = await get_server_status()
    connected = sum(1 for s in status.values() if s.get("status") == "connected")
    return {**status, "total_connected": connected}
