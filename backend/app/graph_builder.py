try:
    from langgraph.types import Send
except ImportError:  # older langgraph versions exposed Send from .graph
    from langgraph.graph import Send

from langgraph.graph import END, StateGraph

from app.graphs.aggregate import aggregate_sources, route_after_aggregate
from app.graphs.broaden import broaden_query
from app.graphs.planner import decompose_query
from app.graphs.research_worker import research_one
from app.graphs.writer import synthesize_report
from app.state import ResearchState


def fan_out_research(state: ResearchState):
    """
    Dispatches one Send() per pending question, so all of them are researched
    in PARALLEL rather than the earlier sequential loop. Used as the
    conditional edge after BOTH planner (first round) and broaden (retry
    round) — each round's pending_questions determines the fan-out.
    """
    return [Send("research_one", {**state, "current_question": q}) for q in state["pending_questions"]]


def build_graph():
    graph = StateGraph(ResearchState)

    graph.add_node("planner", decompose_query)
    graph.add_node("research_one", research_one)
    graph.add_node("aggregate", aggregate_sources)
    graph.add_node("broaden", broaden_query)
    graph.add_node("writer", synthesize_report)

    graph.set_entry_point("planner")

    # Fan out in parallel after both the initial plan and any broadened retry
    graph.add_conditional_edges("planner", fan_out_research, ["research_one"])
    graph.add_conditional_edges("broaden", fan_out_research, ["research_one"])

    graph.add_edge("research_one", "aggregate")

    # Self-correction: too few relevant sources -> broaden and retry once;
    # otherwise proceed to writing.
    graph.add_conditional_edges("aggregate", route_after_aggregate, {"broaden": "broaden", "writer": "writer"})

    graph.add_edge("writer", END)

    return graph.compile()


compiled_graph = build_graph()
