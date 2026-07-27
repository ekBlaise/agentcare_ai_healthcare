"""
Analytics tests: the /staff/analytics endpoint aggregates real persisted data,
reflects bookings/escalations, and is protected by RBAC (staff/admin only).
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
    if db.query(User).filter_by(email="astaff@example.com").first() is None:
        db.add(User(name="A Staff", email="astaff@example.com",
                    password_hash=hash_password("secret1"), role=UserRole.STAFF))
    if db.query(User).filter_by(email="apat@example.com").first() is None:
        u = User(name="A Pat", email="apat@example.com",
                 password_hash=hash_password("secret1"), role=UserRole.PATIENT)
        db.add(u); db.flush()
        db.add(PatientProfile(user_id=u.id))
    db.commit()
    dept = db.query(Department).filter_by(name="AnCardio").first()
    if dept is None:
        dept = Department(name="AnCardio", description="H", active=True)
        db.add(dept); db.flush()
    doc = db.query(Doctor).filter_by(department_id=dept.id).first()
    if doc is None:
        doc = Doctor(department_id=dept.id, name="Dr A", active=True)
        db.add(doc); db.flush()
    if db.query(AppointmentSlot).filter_by(status=SlotStatus.OPEN).count() < 2:
        base = datetime.now(timezone.utc).replace(microsecond=0) + timedelta(days=6)
        for i in range(4):
            st = base + timedelta(hours=3 * i)
            db.add(AppointmentSlot(doctor_id=doc.id, start_time=st,
                                   end_time=st + timedelta(minutes=30), status=SlotStatus.OPEN))
    db.commit(); db.close()
    from app.api.main import app
    return TestClient(app)


def _tok(c, email):
    return c.post("/auth/login", data={"username": email, "password": "secret1"}).json()["access_token"]


def _auth(t):
    return {"Authorization": f"Bearer {t}"}


def test_analytics_structure_and_rbac(client):
    # patient cannot access analytics
    ptok = _tok(client, "apat@example.com")
    assert client.get("/staff/analytics", headers=_auth(ptok)).status_code == 403

    stok = _tok(client, "astaff@example.com")
    r = client.get("/staff/analytics", headers=_auth(stok))
    assert r.status_code == 200
    a = r.json()
    for key in ("kpis", "appointments_by_status", "escalations_by_category",
                "department_load", "workflows_by_status", "documents_by_type"):
        assert key in a


def test_analytics_reflects_activity(client):
    ptok = _tok(client, "apat@example.com")
    # a booking and an escalating request
    client.post("/requests", headers=_auth(ptok),
                json={"request": "ancardio follow-up next week"})
    client.post("/requests", headers=_auth(ptok),
                json={"request": "what medication should I take for my headache"})

    stok = _tok(client, "astaff@example.com")
    a = client.get("/staff/analytics", headers=_auth(stok)).json()
    # workflows should include at least one completed and one escalated
    assert a["kpis"]["total_appointments"] >= 1
    assert a["kpis"]["open_escalations"] >= 1
    assert sum(a["workflows_by_status"].values()) >= 2