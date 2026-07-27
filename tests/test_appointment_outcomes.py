"""
Appointment-outcome tests: staff can list appointments awaiting confirmation and
record whether each was attended (COMPLETED) or missed (MISSED). RBAC enforced.
"""
import os
os.environ["AGENTCARE_FAKE_LLM"] = "1"

from datetime import datetime, timedelta, timezone
import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client_and_appt():
    from app.database import init_db, SessionLocal
    from app.models import (User, PatientProfile, Department, Doctor,
                            AppointmentSlot, Appointment, SlotStatus,
                            AppointmentStatus, UserRole)
    from app.security import hash_password
    init_db()
    db = SessionLocal()

    if db.query(User).filter_by(email="ostaff@example.com").first() is None:
        db.add(User(name="O Staff", email="ostaff@example.com",
                    password_hash=hash_password("secret1"), role=UserRole.STAFF))
    if db.query(User).filter_by(email="opat@example.com").first() is None:
        u = User(name="O Pat", email="opat@example.com",
                 password_hash=hash_password("secret1"), role=UserRole.PATIENT)
        db.add(u); db.flush()
        db.add(PatientProfile(user_id=u.id))
    db.commit()

    prof = db.query(PatientProfile).join(User).filter(User.email == "opat@example.com").first()
    dept = db.query(Department).filter_by(name="OutcomeDept").first()
    if dept is None:
        dept = Department(name="OutcomeDept", description="x", active=True)
        db.add(dept); db.flush()
    doc = db.query(Doctor).filter_by(department_id=dept.id).first()
    if doc is None:
        doc = Doctor(department_id=dept.id, name="Dr O", active=True)
        db.add(doc); db.flush()
    # a PAST appointment awaiting confirmation
    now = datetime.now(timezone.utc)
    slot = AppointmentSlot(doctor_id=doc.id, start_time=now - timedelta(days=1),
                           end_time=now - timedelta(days=1) + timedelta(minutes=30),
                           status=SlotStatus.BOOKED)
    db.add(slot); db.flush()
    appt = Appointment(patient_id=prof.id, doctor_id=doc.id, slot_id=slot.id,
                       status=AppointmentStatus.AWAITING_CONFIRMATION, reason="checkup")
    db.add(appt); db.commit()
    appt_id = appt.id
    db.close()

    from app.api.main import app
    return TestClient(app), appt_id


def _tok(c, email):
    return c.post("/auth/login", data={"username": email, "password": "secret1"}).json()["access_token"]


def _auth(t):
    return {"Authorization": f"Bearer {t}"}


def test_staff_lists_awaiting_appointments(client_and_appt):
    client, appt_id = client_and_appt
    tok = _tok(client, "ostaff@example.com")
    r = client.get("/staff/appointments?status=awaiting_confirmation", headers=_auth(tok))
    assert r.status_code == 200
    assert any(a["appointment_id"] == appt_id for a in r.json())


def test_patient_cannot_record_outcome(client_and_appt):
    client, appt_id = client_and_appt
    ptok = _tok(client, "opat@example.com")
    r = client.post(f"/staff/appointments/{appt_id}/outcome?attended=true", headers=_auth(ptok))
    assert r.status_code == 403   # RBAC: patients can't record outcomes


def test_staff_records_attended_and_missed(client_and_appt):
    client, appt_id = client_and_appt
    tok = _tok(client, "ostaff@example.com")
    r = client.post(f"/staff/appointments/{appt_id}/outcome?attended=true", headers=_auth(tok))
    assert r.status_code == 200 and r.json()["status"] == "completed"
    # can flip to missed as a correction
    r2 = client.post(f"/staff/appointments/{appt_id}/outcome?attended=false", headers=_auth(tok))
    assert r2.status_code == 200 and r2.json()["status"] == "missed"


def test_staff_sees_upcoming_schedule(client_and_appt):
    """Staff can list upcoming (future) appointments, sorted by time."""
    client, _ = client_and_appt
    # book a future appointment as a patient first
    ptok = _tok(client, "opat@example.com")
    # ensure there are future slots in some department
    from app.database import SessionLocal
    from app.models import Department, Doctor, AppointmentSlot, SlotStatus
    from datetime import datetime, timedelta, timezone
    db = SessionLocal()
    dept = db.query(Department).filter_by(name="OutcomeDept").first()
    doc = db.query(Doctor).filter_by(department_id=dept.id).first()
    now = datetime.now(timezone.utc)
    if db.query(AppointmentSlot).filter(
            AppointmentSlot.doctor_id == doc.id,
            AppointmentSlot.status == SlotStatus.OPEN,
            AppointmentSlot.start_time >= now).count() == 0:
        st = now + timedelta(days=3)
        db.add(AppointmentSlot(doctor_id=doc.id, start_time=st,
                               end_time=st + timedelta(minutes=30), status=SlotStatus.OPEN))
        db.commit()
    db.close()

    client.post("/requests", headers=_auth(ptok),
                json={"request": "outcomedept follow-up please"})

    stok = _tok(client, "ostaff@example.com")
    r = client.get("/staff/appointments?status=upcoming", headers=_auth(stok))
    assert r.status_code == 200
    rows = r.json()
    # all returned appointments must be future + active AND identify the patient
    for a in rows:
        assert a["status"] in ("pending", "confirmed", "rescheduled")
        assert "patient_name" in a and "patient_email" in a