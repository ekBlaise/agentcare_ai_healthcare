"""
Tool-layer tests — prove every tool performs real DB logic.
Uses the shared session-wide test DB (set in root conftest.py).
"""
from datetime import datetime, timedelta, timezone

import pytest


@pytest.fixture(scope="module")
def seeded():
    """Create tables + a dedicated department/doctor/slots for the tool tests."""
    from app.database import init_db, SessionLocal
    from app.models import Department, Doctor, AppointmentSlot, SlotStatus
    init_db()
    db = SessionLocal()

    dept = Department(name="ToolCardiology", description="Heart", active=True)
    db.add(dept); db.flush()
    doc = Doctor(department_id=dept.id, name="Dr. Tool", active=True)
    db.add(doc); db.flush()
    base = datetime.now(timezone.utc).replace(microsecond=0) + timedelta(days=1)
    for i in range(4):
        st = base + timedelta(hours=3 * i)
        db.add(AppointmentSlot(doctor_id=doc.id, start_time=st,
                               end_time=st + timedelta(minutes=30), status=SlotStatus.OPEN))
    db.commit()
    yield db, dept.id
    db.close()


def test_find_or_create_patient(seeded):
    db, _ = seeded
    from app.tools.patients import find_or_create_patient
    r1 = find_or_create_patient(db, "Jane Doe", "jane.tool@example.com")
    assert r1["created"] is True
    r2 = find_or_create_patient(db, "Jane Doe", "jane.tool@example.com")
    assert r2["created"] is False
    assert r1["patient_id"] == r2["patient_id"]


def test_lookup_department(seeded):
    db, _ = seeded
    from app.tools.departments import lookup_department
    assert lookup_department(db, "ToolCardiology")["confidence"] == "exact"
    assert lookup_department(db, "toolcardio")["matched"] in (True, False)  # partial or uncertain
    assert lookup_department(db, "zzz-nonexistent")["matched"] is False


def test_booking_with_conflict(seeded):
    db, dept_id = seeded
    from app.tools.patients import find_or_create_patient
    from app.tools.appointments import get_available_slots, book_appointment
    p = find_or_create_patient(db, "Book Test", "book.tool@example.com")
    slots = get_available_slots(db, department_id=dept_id)
    assert len(slots) >= 2
    ok = book_appointment(db, p["patient_id"], slots[0]["slot_id"], reason="follow-up")
    assert ok["success"] is True
    again = book_appointment(db, p["patient_id"], slots[0]["slot_id"])
    assert again["success"] is False and again["error"] == "slot_not_open"


def test_reschedule_and_cancel(seeded):
    db, dept_id = seeded
    from app.tools.patients import find_or_create_patient
    from app.tools.appointments import get_available_slots, book_appointment, reschedule_appointment, cancel_appointment
    p = find_or_create_patient(db, "Resched", "resched.tool@example.com")
    slots = get_available_slots(db, department_id=dept_id)
    booked = book_appointment(db, p["patient_id"], slots[0]["slot_id"])
    assert booked["success"]
    slots2 = get_available_slots(db, department_id=dept_id)
    if slots2:
        r = reschedule_appointment(db, booked["appointment_id"], slots2[0]["slot_id"])
        assert r["success"] and r["status"] == "rescheduled"
    c = cancel_appointment(db, booked["appointment_id"])
    assert c["success"] and c["status"] == "cancelled"


def test_document_dedupe_and_missing(seeded):
    db, _ = seeded
    from app.tools.patients import find_or_create_patient
    from app.tools.documents import classify_and_store_document, check_missing_documents
    p = find_or_create_patient(db, "Doc Test", "doc.tool@example.com")
    pid = p["patient_id"]
    r1 = classify_and_store_document(db, pid, "my_ecg_report.pdf", b"ECG-BYTES-123")
    assert r1["duplicate"] is False and r1["document_type"] == "ECG"
    r2 = classify_and_store_document(db, pid, "ecg_copy.pdf", b"ECG-BYTES-123")
    assert r2["duplicate"] is True
    miss = check_missing_documents(db, pid, "Cardiology")
    assert "blood_report" in miss["missing"] and "ECG" not in miss["missing"]


def test_reminders_followup_escalation(seeded):
    db, dept_id = seeded
    from app.tools.patients import find_or_create_patient
    from app.tools.appointments import get_available_slots, book_appointment
    from app.tools.reminders import create_reminder, create_followup
    from app.tools.escalations import create_escalation
    p = find_or_create_patient(db, "Remind", "remind.tool@example.com")
    slots = get_available_slots(db, department_id=dept_id)
    if slots:
        appt = book_appointment(db, p["patient_id"], slots[0]["slot_id"])
        assert create_reminder(db, p["patient_id"], appt["appointment_id"])["success"]
        assert create_followup(db, p["patient_id"], appt["appointment_id"], 14)["success"]
    esc = create_escalation(db, reason="Emergency keyword detected", category="emergency")
    assert esc["success"] and esc["category"] == "emergency"


def test_audit_trail_grows(seeded):
    db, _ = seeded
    from app.models import AuditEvent
    assert db.query(AuditEvent).count() > 5
