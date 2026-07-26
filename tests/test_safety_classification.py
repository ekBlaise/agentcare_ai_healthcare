"""
Regression tests for Safety-agent classification. Locks in that routine
administrative requests (including the rubric's canonical example) are SAFE and
complete, while genuine clinical-advice / emergency requests escalate.
Runs offline (fake-LLM) so it is deterministic.
"""
import os
os.environ["AGENTCARE_FAKE_LLM"] = "1"

import pytest

SAFE_REQUESTS = [
    "I need a cardiology follow-up next week and want to attach my old ECG.",
    "Book me a dermatology appointment for a skin check.",
    "I have diabetes and need my regular endocrinology follow-up.",
    "Reschedule my orthopedics visit; here is my referral.",
]
SENSITIVE_REQUESTS = [
    "What medication should I take for my headache?",
    "Do I have cancer?",
    "What dose of insulin is right for me?",
]
EMERGENCY_REQUESTS = [
    "I have severe chest pain and can't breathe.",
    "I think I'm having a stroke.",
]


@pytest.mark.parametrize("text", SAFE_REQUESTS)
def test_admin_requests_are_safe(text):
    from app.agents.safety import _heuristic_verdict
    verdict, _ = _heuristic_verdict(text)
    assert verdict == "safe", f"expected safe for: {text}"


@pytest.mark.parametrize("text", SENSITIVE_REQUESTS)
def test_clinical_requests_are_sensitive(text):
    from app.agents.safety import _heuristic_verdict
    verdict, _ = _heuristic_verdict(text)
    assert verdict == "sensitive", f"expected sensitive for: {text}"


@pytest.mark.parametrize("text", EMERGENCY_REQUESTS)
def test_emergencies_are_emergency(text):
    from app.agents.safety import _heuristic_verdict
    verdict, _ = _heuristic_verdict(text)
    assert verdict == "emergency", f"expected emergency for: {text}"


def test_rubric_example_completes_and_books():
    """The rubric's canonical request must flow end-to-end and book, not escalate."""
    import uuid
    from app.database import init_db, SessionLocal
    from app.models import Department, Doctor, AppointmentSlot, SlotStatus
    from datetime import datetime, timedelta, timezone
    init_db()
    db = SessionLocal()
    if db.query(Department).filter_by(name="Cardiology").first() is None:
        dept = Department(name="Cardiology", description="Heart", active=True)
        db.add(dept); db.flush()
        doc = Doctor(department_id=dept.id, name="Dr. Heart", active=True)
        db.add(doc); db.flush()
        base = datetime.now(timezone.utc).replace(microsecond=0) + timedelta(days=5)
        for i in range(4):
            st = base + timedelta(hours=3*i)
            db.add(AppointmentSlot(doctor_id=doc.id, start_time=st,
                                   end_time=st+timedelta(minutes=30), status=SlotStatus.OPEN))
        db.commit()
    db.close()

    from app.agents import build_graph
    graph = build_graph(checkpointer=None)
    final = graph.invoke({
        "request": "I need a cardiology follow-up next week and want to attach my old ECG.",
        "patient_input": {"name": "Rubric Pat", "email": "rubric@example.com"},
        "documents_input": [{"filename": "old_ecg.pdf", "content": b"ECG-RUBRIC"}],
        "messages": [], "status": "running",
    }, config={"configurable": {"thread_id": f"t-{uuid.uuid4().hex[:8]}"}})

    assert final["status"] == "completed", f"expected completed, got {final['status']}"
    assert final.get("department_name") == "Cardiology"
    assert final.get("appointment_id") is not None
    assert final.get("safety_verdict") == "safe"