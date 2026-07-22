"""
LangGraph orchestration — wires the six agents into a stateful graph with
conditional edges (emergency/sensitive -> escalate, uncertain route -> escalate)
and a SQL checkpointer so workflow state persists and can be resumed.

Flow:
    START -> coordinator -> safety -> [conditional]
        emergency/sensitive -> escalate -> END
        safe -> routing -> [conditional]
            uncertain -> escalate -> END
            matched  -> appointment -> document -> followup -> confirm -> END
"""
from langgraph.graph import StateGraph, START, END

from app.agents.state import AgentState
from app.agents.coordinator import coordinator_agent
from app.agents.safety import safety_agent
from app.agents.routing import routing_agent
from app.agents.appointment import appointment_agent
from app.agents.document import document_agent
from app.agents.followup import followup_agent
from app.agents.finalize import escalate_node, confirm_node


# ── conditional edge functions ────────────────────────────────────────────
def after_safety(state: dict) -> str:
    return "escalate" if state.get("safety_verdict") in ("emergency", "sensitive") else "routing"


def after_routing(state: dict) -> str:
    return "escalate" if state.get("routing_confidence") == "uncertain" else "appointment"


def build_graph(checkpointer=None):
    """Compile the AgentCare workflow graph. Optionally pass a checkpointer."""
    g = StateGraph(AgentState)

    g.add_node("coordinator", coordinator_agent)
    g.add_node("safety", safety_agent)
    g.add_node("routing", routing_agent)
    g.add_node("appointment", appointment_agent)
    g.add_node("document", document_agent)
    g.add_node("followup", followup_agent)
    g.add_node("escalate", escalate_node)
    g.add_node("confirm", confirm_node)

    g.add_edge(START, "coordinator")
    g.add_edge("coordinator", "safety")
    g.add_conditional_edges("safety", after_safety,
                            {"escalate": "escalate", "routing": "routing"})
    g.add_conditional_edges("routing", after_routing,
                            {"escalate": "escalate", "appointment": "appointment"})
    g.add_edge("appointment", "document")
    g.add_edge("document", "followup")
    g.add_edge("followup", "confirm")
    g.add_edge("confirm", END)
    g.add_edge("escalate", END)

    return g.compile(checkpointer=checkpointer)


def get_checkpointer():
    """
    Return a persistent SQL checkpointer when available, else None.
    LangGraph's SqliteSaver persists agent state keyed by thread_id so an
    interrupted workflow can be resumed. (Business state is ALSO persisted to
    WorkflowRun independently, so persistence never depends on this.)
    """
    try:
        from langgraph.checkpoint.sqlite import SqliteSaver
        import sqlite3
        conn = sqlite3.connect("data/agent_checkpoints.db", check_same_thread=False)
        return SqliteSaver(conn)
    except Exception:
        return None
