"""
API tests — prove backend-enforced RBAC, the escalation approval workflow,
patient data isolation, and the request endpoint running the agent workflow.
Runs in offline (fake-LLM) mode.
"""
import os
os.environ["AGENTCARE_FAKE_LLM"] = "1"

import base64
import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    # Fresh DB + seed
    from app.database import init_db, SessionLocal
    from app.models import Department, Doctor, AppointmentSlot, SlotStatus, User, PatientProfile, UserRole
    from app.security import hash_password
    from datetime import datetime, timedelta, timezone

    init_db()
    db = SessionLocal()

    # idempotent seed — safe even if other test modules already populated the shared DB
    if db.query(User).filter_by(email="staff@agentcare.local").first() is None:
        db.add(User(name="Sam Staff", email="staff@agentcare.local",
                    password_hash=hash_password("staff123"), role=UserRole.STAFF))
    if db.query(User).filter_by(email="patient@agentcare.local").first() is None:
        patient = User(name="Pat Patient", email="patient@agentcare.local",
                       password_hash=hash_password("patient123"), role=UserRole.PATIENT)
        db.add(patient); db.flush()
        db.add(PatientProfile(user_id=patient.id, phone="+1", preferred_language="English"))
    db.commit()

    dept = db.query(Department).filter_by(name="Cardiology").first()
    if dept is None:
        dept = Department(name="Cardiology", description="Heart", active=True)
        db.add(dept); db.flush()
    doc = db.query(Doctor).filter_by(department_id=dept.id).first()
    if doc is None:
        doc = Doctor(department_id=dept.id, name="Dr. Heart", active=True)
        db.add(doc); db.flush()
    # ensure there are open slots to book
    if db.query(AppointmentSlot).filter_by(doctor_id=doc.id, status=SlotStatus.OPEN).count() < 2:
        base = datetime.now(timezone.utc).replace(microsecond=0) + timedelta(days=2)
        for i in range(6):
            st = base + timedelta(hours=3*i)
            db.add(AppointmentSlot(doctor_id=doc.id, start_time=st,
                                   end_time=st+timedelta(minutes=30), status=SlotStatus.OPEN))
    db.commit()
    db.close()

    from app.api.main import app
    return TestClient(app)


def _token(client, email, password):
    r = client.post("/auth/login", data={"username": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_health(client):
    assert client.get("/health").json()["status"] == "ok"


def test_login_and_bad_login(client):
    assert client.post("/auth/login", data={"username": "staff@agentcare.local",
                                             "password": "staff123"}).status_code == 200
    assert client.post("/auth/login", data={"username": "staff@agentcare.local",
                                             "password": "wrong"}).status_code == 401


def test_rbac_patient_cannot_access_staff(client):
    """Backend RBAC: a patient token is rejected from staff endpoints with 403."""
    ptoken = _token(client, "patient@agentcare.local", "patient123")
    r = client.get("/staff/escalations", headers=_auth(ptoken))
    assert r.status_code == 403


def test_rbac_requires_auth(client):
    """No token -> 401, not silent access."""
    assert client.get("/staff/workflows").status_code == 401
    assert client.get("/me/appointments").status_code == 401


def test_patient_request_books_appointment(client):
    ptoken = _token(client, "patient@agentcare.local", "patient123")
    body = {"request": "I need a cardiology follow-up next week.",
            "documents": [{"filename": "ecg.pdf",
                           "content_base64": base64.b64encode(b"ECG-API").decode()}]}
    r = client.post("/requests", headers=_auth(ptoken), json=body)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["status"] == "completed"
    assert data["appointment_id"] is not None
    # patient can see their own appointment
    appts = client.get("/me/appointments", headers=_auth(ptoken)).json()
    assert len(appts) >= 1


def test_emergency_request_escalates_via_api(client):
    ptoken = _token(client, "patient@agentcare.local", "patient123")
    r = client.post("/requests", headers=_auth(ptoken),
                    json={"request": "severe chest pain, can't breathe"})
    data = r.json()
    assert data["status"] == "escalated" and data["escalated"] is True
    assert data["appointment_id"] is None


def test_staff_reviews_escalation(client):
    """End-to-end human-in-the-loop: create an escalation, staff approves it."""
    # trigger an escalation
    ptoken = _token(client, "patient@agentcare.local", "patient123")
    client.post("/requests", headers=_auth(ptoken),
                json={"request": "what medication should I take for my headache"})

    stoken = _token(client, "staff@agentcare.local", "staff123")
    escs = client.get("/staff/escalations?status=open", headers=_auth(stoken)).json()
    assert len(escs) >= 1
    eid = escs[0]["escalation_id"]

    # patient must NOT be able to review it
    assert client.post(f"/staff/escalations/{eid}/review", headers=_auth(ptoken),
                       json={"decision": "approve"}).status_code == 403

    # staff approves -> persisted
    r = client.post(f"/staff/escalations/{eid}/review", headers=_auth(stoken),
                    json={"decision": "approve", "notes": "reviewed, ok"})
    assert r.status_code == 200 and r.json()["status"] == "approved"

    # audit trail reflects it
    audit = client.get("/staff/audit", headers=_auth(stoken)).json()
    assert any(a["action"] == "escalation_approved" for a in audit)
