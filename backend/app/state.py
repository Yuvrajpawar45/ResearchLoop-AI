import operator
from typing import Annotated, TypedDict


class SearchResult(TypedDict):
    title: str
    url: str
    snippet: str
    source: str          # "tavily" or "github"
    relevance_score: float  # filled in by the LLM scorer node


class ResearchState(TypedDict):
    query: str
    sub_questions: list[str]
    # Questions to research in the CURRENT round — either the initial
    # sub_questions from the planner, or a single broadened query from the
    # self-correction loop. Read by the Send()-based fan-out.
    pending_questions: list[str]
    # Set only inside each parallel research_one() invocation via Send(),
    # not persisted as top-level pipeline state.
    current_question: str
    # Sub-questions are now researched in PARALLEL via LangGraph's Send() API
    # (previously sequential — see project history). Each research_one()
    # branch appends its own results here; operator.add merges all branches.
    search_results: Annotated[list[SearchResult], operator.add]
    scored_sources: list[SearchResult]
    # Self-correction: incremented each time the broaden node fires. Capped
    # by settings.max_retries so a genuinely low-signal query can't loop
    # forever.
    retry_count: int
    report: str
