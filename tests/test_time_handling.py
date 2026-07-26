"""
Time-handling tests: the system must never offer or book a slot in the past,
and past appointments should expire to 'completed'.
"""
import os
os.environ["AGENTCARE_FAKE_LLM"] = "1"

from datetime import datetime, timedelta, timezone
import pytest


@pytest.fixture
def setup(db_session_factory=None):
    from app.database import init_db, SessionLocal
    from app.models import (Department, Doctor, AppointmentSlot, SlotStatus,
                            User, PatientProfile, UserRole)
    from app.security import hash_password
    import uuid
    init_db()
    db = SessionLocal()
    dept = db.query(Department).filter_by(name="TimeCardio").first()
    if dept is None:
        dept = Department(name="TimeCardio", description="H", active=True)
        db.add(dept); db.flush()
    doc = db.query(Doctor).filter_by(department_id=dept.id).first()
    if doc is None:
        doc = Doctor(department_id=dept.id, name="Dr T", active=True)
        db.add(doc); db.flush()
    now = datetime.now(timezone.utc)
    past = AppointmentSlot(doctor_id=doc.id, start_time=now - timedelta(days=1),
                           end_time=now - timedelta(days=1) + timedelta(minutes=30),
                           status=SlotStatus.OPEN)
    future = AppointmentSlot(doctor_id=doc.id, start_time=now + timedelta(days=1),
                             end_time=now + timedelta(days=1) + timedelta(minutes=30),
                             status=SlotStatus.OPEN)
    db.add_all([past, future]); db.flush()
    email = f"time-{uuid.uuid4().hex[:8]}@example.com"
    u = User(name="T", email=email,
             password_hash=hash_password("x"), role=UserRole.PATIENT)
    db.add(u); db.flush()
    prof = PatientProfile(user_id=u.id); db.add(prof); db.commit()
    data = {"db": db, "dept_id": dept.id, "past_id": past.id,
            "future_id": future.id, "patient_id": prof.id}
    yield data
    db.close()


def test_past_slots_not_offered(setup):
    from app.tools import get_available_slots
    slots = get_available_slots(setup["db"], department_id=setup["dept_id"])
    ids = [s["slot_id"] for s in slots]
    assert setup["past_id"] not in ids
    assert setup["future_id"] in ids


def test_cannot_book_past_slot(setup):
    from app.tools import book_appointment
    r = book_appointment(setup["db"], setup["patient_id"], setup["past_id"])
    assert r["success"] is False and r["error"] == "slot_in_past"


def test_can_book_future_slot(setup):
    from app.tools import book_appointment
    r = book_appointment(setup["db"], setup["patient_id"], setup["future_id"])
    assert r["success"] is True


def test_expire_past_appointments(setup):
    from app.models import Appointment, AppointmentSlot, SlotStatus, AppointmentStatus
    from app.tools import expire_past_appointments
    db = setup["db"]
    now = datetime.now(timezone.utc)
    doctor_id = setup["db"].query(__import__("app.models", fromlist=["Doctor"]).Doctor).first().id
    slot = AppointmentSlot(doctor_id=doctor_id, start_time=now - timedelta(days=2),
                           end_time=now - timedelta(days=2) + timedelta(minutes=30),
                           status=SlotStatus.BOOKED)
    db.add(slot); db.flush()
    appt = Appointment(patient_id=setup["patient_id"], doctor_id=doctor_id, slot_id=slot.id,
                       status=AppointmentStatus.CONFIRMED)
    db.add(appt); db.commit()
    res = expire_past_appointments(db)
    db.refresh(appt)
    # Past appointments await human confirmation of the real outcome (not auto-completed)
    assert appt.status == AppointmentStatus.AWAITING_CONFIRMATION
    assert res["awaiting_confirmation"] >= 1

    # Staff records the actual outcome
    from app.tools import record_appointment_outcome
    r = record_appointment_outcome(db, appt.id, attended=True)
    db.refresh(appt)
    assert r["success"] and appt.status == AppointmentStatus.COMPLETED

    # And a missed one
    r2 = record_appointment_outcome(db, appt.id, attended=False)
    db.refresh(appt)
    assert appt.status == AppointmentStatus.MISSED