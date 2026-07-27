"""
Reminder-sync tests: reminders stay consistent with appointments —
no duplicates on repeat requests, cancelled when the appointment is cancelled,
and regenerated at the new time on reschedule.
"""
import os
os.environ["AGENTCARE_FAKE_LLM"] = "1"

from datetime import datetime, timedelta, timezone
import pytest


@pytest.fixture
def setup():
    from app.database import init_db, SessionLocal
    from app.models import (Department, Doctor, AppointmentSlot, SlotStatus,
                            User, PatientProfile, UserRole)
    from app.security import hash_password
    import uuid
    init_db()
    db = SessionLocal()
    dept = db.query(Department).filter_by(name="RemDept").first()
    if dept is None:
        dept = Department(name="RemDept", description="x", active=True)
        db.add(dept); db.flush()
        doc = Doctor(department_id=dept.id, name="Dr Rem", active=True)
        db.add(doc); db.flush()
    else:
        doc = db.query(Doctor).filter_by(department_id=dept.id).first()
    now = datetime.now(timezone.utc)
    s1 = AppointmentSlot(doctor_id=doc.id, start_time=now + timedelta(days=40),
                         end_time=now + timedelta(days=40, minutes=30), status=SlotStatus.OPEN)
    s2 = AppointmentSlot(doctor_id=doc.id, start_time=now + timedelta(days=41),
                         end_time=now + timedelta(days=41, minutes=30), status=SlotStatus.OPEN)
    db.add_all([s1, s2]); db.flush()
    email = f"rem-{uuid.uuid4().hex[:8]}@example.com"
    u = User(name="Rem", email=email, password_hash=hash_password("x"), role=UserRole.PATIENT)
    db.add(u); db.flush()
    prof = PatientProfile(user_id=u.id); db.add(prof); db.commit()
    data = {"db": db, "patient_id": prof.id, "s1": s1.id, "s2": s2.id}
    yield data
    db.close()


def _scheduled(db, patient_id):
    from app.models import Reminder, ReminderStatus
    return db.query(Reminder).filter_by(patient_id=patient_id,
                                        status=ReminderStatus.SCHEDULED).count()


def test_no_duplicate_reminders(setup):
    from app.tools import book_appointment, create_reminder, create_followup
    db, pid = setup["db"], setup["patient_id"]
    b = book_appointment(db, pid, setup["s1"])
    create_reminder(db, pid, b["appointment_id"])
    create_followup(db, pid, b["appointment_id"])
    # calling again must NOT create duplicates (idempotent)
    create_reminder(db, pid, b["appointment_id"])
    create_followup(db, pid, b["appointment_id"])
    assert _scheduled(db, pid) == 2


def test_cancel_cancels_reminders(setup):
    from app.tools import book_appointment, create_reminder, create_followup, cancel_appointment
    db, pid = setup["db"], setup["patient_id"]
    b = book_appointment(db, pid, setup["s1"])
    create_reminder(db, pid, b["appointment_id"])
    create_followup(db, pid, b["appointment_id"])
    assert _scheduled(db, pid) == 2
    cancel_appointment(db, b["appointment_id"])
    assert _scheduled(db, pid) == 0


def test_reschedule_regenerates_reminders(setup):
    from app.tools import book_appointment, create_reminder, create_followup, reschedule_appointment
    from app.models import Reminder, ReminderStatus
    db, pid = setup["db"], setup["patient_id"]
    b = book_appointment(db, pid, setup["s1"])
    create_reminder(db, pid, b["appointment_id"])
    create_followup(db, pid, b["appointment_id"])
    old = db.query(Reminder).filter_by(appointment_id=b["appointment_id"],
                                       reminder_type="appointment",
                                       status=ReminderStatus.SCHEDULED).first().scheduled_at
    res = reschedule_appointment(db, b["appointment_id"], setup["s2"])
    assert res["success"]
    assert _scheduled(db, pid) == 2          # exactly 2 fresh
    new = db.query(Reminder).filter_by(appointment_id=b["appointment_id"],
                                       reminder_type="appointment",
                                       status=ReminderStatus.SCHEDULED).first().scheduled_at
    assert new != old                        # timed to the new slot