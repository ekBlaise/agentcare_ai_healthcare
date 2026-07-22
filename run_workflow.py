"""
Run the AgentCare workflow from the command line (demo / manual testing).

Offline mode (no Groq key needed):
    AGENTCARE_FAKE_LLM=1 python run_workflow.py

With a real LLM:
    # set GROQ_API_KEY in .env, then:
    python run_workflow.py
"""
import uuid

from app.agents import build_graph, get_checkpointer


def run(request: str, patient: dict, documents: list | None = None):
    graph = build_graph(checkpointer=get_checkpointer())
    thread_id = f"thread-{uuid.uuid4().hex[:8]}"

    initial = {
        "request": request,
        "patient_input": patient,
        "documents_input": documents or [],
        "messages": [],
        "status": "running",
    }
    config = {"configurable": {"thread_id": thread_id}}
    final = graph.invoke(initial, config=config)

    print("\n" + "=" * 66)
    print(f"REQUEST: {request}")
    print("-" * 66)
    for m in final.get("messages", []):
        print("  •", m)
    print("-" * 66)
    print("STATUS:", final.get("status"))
    print("CONFIRMATION:", final.get("confirmation"))
    print("=" * 66)
    return final


if __name__ == "__main__":
    # Example 1 — normal administrative flow
    run(
        "I need a cardiology follow-up next week and want to attach my old ECG.",
        {"name": "Ada Test", "email": "ada.demo@example.com", "phone": "+237-600-222-222"},
        [{"filename": "old_ecg.pdf", "content": b"ECG-DEMO-BYTES"}],
    )

    # Example 2 — emergency -> should escalate, no booking
    run(
        "I'm having severe chest pain and can't breathe right now.",
        {"name": "Urgent Person", "email": "urgent@example.com"},
    )

    # Example 3 — diagnosis-seeking -> should escalate as sensitive
    run(
        "Can you tell me what medication I should take for my headache?",
        {"name": "Curious Person", "email": "curious@example.com"},
    )
