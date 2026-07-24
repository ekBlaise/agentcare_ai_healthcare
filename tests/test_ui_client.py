"""
UI API-client tests — prove the Streamlit UI's data layer is genuinely wired to
the backend (not hardcoded). Each api_client function is exercised against the
live FastAPI app via TestClient (which shares httpx's interface).
"""
import os
os.environ["AGENTCARE_FAKE_LLM"] = "1"

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    from app.database import init_db, SessionLocal
    from app.models import (User, PatientProfile, Department, Doctor,
                            AppointmentSlot, SlotStatus, UserRole)
    from app.security import hash_password
    from datetime import datetime, timedelta, timezone

    init_db()
    db = SessionLocal()
    if db.query(User).filter_by(email="staff@agentcare.local").first() is None:
        db.add(User(name="Sam Staff", email="staff@agentcare.local",
                    password_hash=hash_password("staff123"), role=UserRole.STAFF))
    if db.query(User).filter_by(email="patient@agentcare.local").first() is None:
        p = User(name="Pat Patient", email="patient@agentcare.local",
                 password_hash=hash_password("patient123"), role=UserRole.PATIENT)
        db.add(p); db.flush()
        db.add(PatientProfile(user_id=p.id, preferred_language="English"))
    db.commit()
    dept = db.query(Department).filter_by(name="Cardiology").first()
    if dept is None:
        dept = Department(name="Cardiology", description="Heart", active=True)
        db.add(dept); db.flush()
    doc = db.query(Doctor).filter_by(department_id=dept.id).first()
    if doc is None:
        doc = Doctor(department_id=dept.id, name="Dr. Heart", active=True)
        db.add(doc); db.flush()
    if db.query(AppointmentSlot).filter_by(status=SlotStatus.OPEN).count() < 2:
        base = datetime.now(timezone.utc).replace(microsecond=0) + timedelta(days=3)
        for i in range(6):
            st = base + timedelta(hours=3*i)
            db.add(AppointmentSlot(doctor_id=doc.id, start_time=st,
                                   end_time=st+timedelta(minutes=30), status=SlotStatus.OPEN))
    db.commit(); db.close()

    from app.api.main import app
    return TestClient(app)


def test_ui_login_and_request_flow(client):
    from app.ui import api_client as api
    ok, data = api.login("patient@agentcare.local", "patient123", client=client)
    assert ok and data["role"] == "patient"
    token = data["access_token"]

    ok, result = api.submit_request(
        token, "cardiology follow-up next week",
        documents=[{"filename": "ecg.pdf", "content": b"ECG-UI"}], client=client)
    assert ok and result["status"] == "completed"
    assert result["appointment_id"] is not None

    ok, appts = api.my_appointments(token, client=client)
    assert ok and len(appts) >= 1


def test_ui_staff_escalation_review(client):
    from app.ui import api_client as api
    # patient triggers an escalation
    ok, pdata = api.login("patient@agentcare.local", "patient123", client=client)
    api.submit_request(pdata["access_token"],
                       "what medication should I take for my headache", client=client)

    ok, sdata = api.login("staff@agentcare.local", "staff123", client=client)
    stoken = sdata["access_token"]
    ok, escs = api.list_escalations(stoken, status="open", client=client)
    assert ok and len(escs) >= 1

    ok, res = api.review_escalation(stoken, escs[0]["escalation_id"], "approve",
                                    "looks fine", client=client)
    assert ok and res["status"] == "approved"

    ok, audit = api.audit_trail(stoken, client=client)
    assert ok and any(a["action"] == "escalation_approved" for a in audit)
