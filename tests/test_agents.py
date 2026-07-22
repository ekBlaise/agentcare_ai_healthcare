"""
Agent / graph tests — prove the full LangGraph workflow runs end to end,
routes correctly, escalates emergencies and diagnosis-seeking requests, and
persists workflow state. Runs in offline (fake-LLM) mode so no key is needed.
"""
import os
os.environ["AGENTCARE_FAKE_LLM"] = "1"   # force deterministic offline mode

import uuid
import pytest


@pytest.fixture(scope="module")
def graph_and_db():
    from app.database import init_db, SessionLocal
    from app.models import Department, Doctor, AppointmentSlot, SlotStatus
    from datetime import datetime, timedelta, timezone
    init_db()
    db = SessionLocal()
    # seed a department + doctor + slots if empty
    if db.query(Department).filter_by(name="Cardiology").first() is None:
        dept = Department(name="Cardiology", description="Heart", active=True)
        db.add(dept); db.flush()
        doc = Doctor(department_id=dept.id, name="Dr. Heart", active=True)
        db.add(doc); db.flush()
        base = datetime.now(timezone.utc).replace(microsecond=0) + timedelta(days=1)
        for i in range(4):
            st = base + timedelta(hours=3 * i)
            db.add(AppointmentSlot(doctor_id=doc.id, start_time=st,
                                   end_time=st + timedelta(minutes=30), status=SlotStatus.OPEN))
        db.commit()

    from app.agents import build_graph
    graph = build_graph(checkpointer=None)   # business state still persists via WorkflowRun
    yield graph, db
    db.close()


def _run(graph, request, email, docs=None):
    initial = {
        "request": request,
        "patient_input": {"name": "Test", "email": email},
        "documents_input": docs or [],
        "messages": [], "status": "running",
    }
    cfg = {"configurable": {"thread_id": f"t-{uuid.uuid4().hex[:8]}"}}
    return graph.invoke(initial, config=cfg)


def test_normal_flow_books_and_completes(graph_and_db):
    graph, _ = graph_and_db
    final = _run(graph, "I need a cardiology follow-up next week.",
                 "flow@example.com", [{"filename": "ecg.pdf", "content": b"ECG-XYZ"}])
    assert final["status"] == "completed"
    assert final.get("appointment_id") is not None
    assert final.get("department_name") == "Cardiology"
    assert "confirmed" in (final.get("confirmation") or "").lower()


def test_emergency_escalates_without_booking(graph_and_db):
    graph, _ = graph_and_db
    final = _run(graph, "I have severe chest pain and can't breathe.",
                 "emergency@example.com")
    assert final["status"] == "escalated"
    assert final.get("safety_verdict") == "emergency"
    assert final.get("appointment_id") is None      # NO booking on emergency


def test_diagnosis_request_escalates(graph_and_db):
    graph, _ = graph_and_db
    final = _run(graph, "What medication should I take for my headache?",
                 "diag@example.com")
    assert final["status"] == "escalated"
    assert final.get("safety_verdict") == "sensitive"
    assert final.get("appointment_id") is None


def test_workflow_state_persisted(graph_and_db):
    graph, db = graph_and_db
    final = _run(graph, "cardiology follow-up please", "persist@example.com")
    from app.models import WorkflowRun
    run = db.query(WorkflowRun).filter(WorkflowRun.id == final["workflow_run_id"]).first()
    assert run is not None
    assert run.status.value in ("completed", "escalated")
    assert isinstance(run.state, dict) and "safety_verdict" in run.state


def test_three_distinct_agents_ran(graph_and_db):
    """The trace must show distinct agents acting (coordinator, safety, routing...)."""
    graph, _ = graph_and_db
    final = _run(graph, "cardiology follow-up", "distinct@example.com")
    joined = " | ".join(final["messages"]).lower()
    assert "coordinator" in joined
    assert "safety" in joined
    assert "routing" in joined
    assert "appointment" in joined
