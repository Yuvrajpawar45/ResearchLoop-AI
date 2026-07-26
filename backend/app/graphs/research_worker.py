from app.mcp_client import get_tools
from app.mcp_search import gather_and_score
from app.state import ResearchState


async def research_one(state: ResearchState) -> dict:
    """
    Researches exactly ONE question — either one of the planner's original
    sub-questions, or the single broadened query from a self-correction
    retry. Invoked in PARALLEL, once per entry in pending_questions, via
    LangGraph's Send() API (see graph_builder.py's fan_out_research()).

    This replaces the earlier sequential version, which looped over
    sub-questions one at a time. All parallel branches write to
    search_results, which uses an operator.add reducer, so LangGraph merges
    every branch's results automatically before the graph proceeds to the
    aggregate node.
    """
    sub_q = state["current_question"]
    tools = await get_tools()
    results = await gather_and_score(tools, sub_q)
    return {"search_results": results}
