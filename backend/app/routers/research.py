import json

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.graph_builder import compiled_graph
from app.limiter import limiter

router = APIRouter()


class ResearchRequest(BaseModel):
    # min_length guards against the empty/near-empty query failure mode —
    # see tests/test_failure_modes.py.
    query: str = Field(..., min_length=3, max_length=500)


@router.post("/api/research")
@limiter.limit("10/minute")
async def research(request: Request, req: ResearchRequest):
    """Non-streaming endpoint: runs the full graph and returns the final state."""
    result = await compiled_graph.ainvoke({"query": req.query})
    return {
        "query": req.query,
        "sub_questions": result.get("sub_questions", []),
        "sources": result.get("scored_sources", []),
        "report": result.get("report", ""),
        "source_count": len(result.get("scored_sources", [])),
        "retries_used": result.get("retry_count", 0),
    }


@router.post("/api/research/stream")
@limiter.limit("10/minute")
async def research_stream(request: Request, req: ResearchRequest):
    """
    SSE endpoint. Streams a named event each time a graph node completes.

    NOTE: node names now include "research_one" (fired once per PARALLEL
    sub-question via Send — see graph_builder.py), "aggregate", and
    optionally "broaden" if the self-correction loop fires. The frontend's
    event handling maps these to Planner/Research/Writer phases; if you add
    more nodes here, the frontend's node-name switch needs a matching update.

    Wrapped in a top-level try/except so a mid-stream error becomes a
    visible SSE error event instead of a silently truncated connection.
    """

    async def event_generator():
        try:
            async for event in compiled_graph.astream(
                {"query": req.query}, stream_mode="updates"
            ):
                for node_name, node_output in event.items():
                    payload = {"node": node_name, "output": node_output}
                    yield f"event: node_update\ndata: {json.dumps(payload, default=str)}\n\n"
            yield "event: done\ndata: {}\n\n"
        except Exception as e:
            yield f"event: error\ndata: {json.dumps({'detail': str(e)})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
