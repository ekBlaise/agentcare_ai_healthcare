"""
Workflow service — compiles the LangGraph once and runs it with basic
retry/recovery (error-handling requirement).
"""
import time
import uuid

from app.agents import build_graph, get_checkpointer

_graph = None


def get_graph():
    global _graph
    if _graph is None:
        _graph = build_graph(checkpointer=get_checkpointer())
    return _graph


def run_workflow(initial_state: dict, max_attempts: int = 2) -> dict:
    """Invoke the graph with a fresh thread id, retrying once on transient errors."""
    graph = get_graph()
    thread_id = f"api-{uuid.uuid4().hex[:10]}"
    config = {"configurable": {"thread_id": thread_id}}

    last_err = None
    for attempt in range(1, max_attempts + 1):
        try:
            return graph.invoke(initial_state, config=config)
        except Exception as e:              # transient LLM/DB hiccup -> retry once
            last_err = e
            time.sleep(0.5 * attempt)
    # Recovery: return a failed-but-structured result instead of crashing
    return {
        "status": "failed",
        "error": str(last_err),
        "confirmation": "We could not process your request automatically. Staff will follow up.",
        "messages": [f"Workflow failed after {max_attempts} attempts: {last_err}"],
    }
