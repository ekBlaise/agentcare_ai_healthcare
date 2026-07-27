"""
Day 6 hardening — edge cases through the API:
reschedule, cancel, ownership enforcement (a patient cannot touch another
patient's appointment), duplicate-document handling, and cancel-of-cancelled.
Runs in offline (fake-LLM) mode.
"""
import os
os.environ["AGENTCARE_FAKE_LLM"] = "1"

import base64
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

    def ensure_patient(email):
        if db.query(User).filter_by(email=email).first() is None:
            u = User(name=email.split("@")[0], email=email,
                     password_hash=hash_password("secret1"), role=UserRole.PATIENT)
            db.add(u); db.flush()
            prof = PatientProfile(user_id=u.id, preferred_language="English")
            db.add(prof); db.flush()
            from app.tools import set_consent
            for ct in ("document_storage", "data_processing", "communications"):
                set_consent(db, prof.id, ct, True)
    ensure_patient("edge1@example.com")
    ensure_patient("edge2@example.com")
    db.commit()

    dept = db.query(Department).filter_by(name="Cardiology").first()
    if dept is None:
        dept = Department(name="Cardiology", description="Heart", active=True)
        db.add(dept); db.flush()
    doc = db.query(Doctor).filter_by(department_id=dept.id).first()
    if doc is None:
        doc = Doctor(department_id=dept.id, name="Dr. Heart", active=True)
        db.add(doc); db.flush()
    if db.query(AppointmentSlot).filter_by(status=SlotStatus.OPEN).count() < 6:
        base = datetime.now(timezone.utc).replace(microsecond=0) + timedelta(days=4)
        for i in range(8):
            st = base + timedelta(hours=3*i)
            db.add(AppointmentSlot(doctor_id=doc.id, start_time=st,
                                   end_time=st+timedelta(minutes=30), status=SlotStatus.OPEN))
    db.commit(); db.close()

    from app.api.main import app
    return TestClient(app)


def _tok(client, email):
    return client.post("/auth/login", data={"username": email, "password": "secret1"}).json()["access_token"]


def _auth(t):
    return {"Authorization": f"Bearer {t}"}


def _book(client, token):
    r = client.post("/requests", headers=_auth(token),
                    json={"request": "cardiology follow-up next week"})
    return r.json()["appointment_id"]


def test_reschedule_through_api(client):
    tok = _tok(client, "edge1@example.com")
    appt_id = _book(client, tok)
    assert appt_id is not None
    resp = client.get(f"/me/available-slots?appointment_id={appt_id}", headers=_auth(tok))
    assert resp.status_code == 200
    slots = resp.json()
    assert len(slots) >= 1
    r = client.post(f"/me/appointments/{appt_id}/reschedule?new_slot_id={slots[0]['slot_id']}",
                    headers=_auth(tok))
    assert r.status_code == 200 and r.json()["status"] == "rescheduled"


def test_cancel_and_double_cancel(client):
    tok = _tok(client, "edge1@example.com")
    appt_id = _book(client, tok)
    r1 = client.post(f"/me/appointments/{appt_id}/cancel", headers=_auth(tok))
    assert r1.status_code == 200 and r1.json()["status"] == "cancelled"
    # cancelling again -> 409 conflict, not a crash
    r2 = client.post(f"/me/appointments/{appt_id}/cancel", headers=_auth(tok))
    assert r2.status_code == 409


def test_ownership_enforced_on_reschedule_and_cancel(client):
    """A patient must NOT be able to touch another patient's appointment."""
    tok1 = _tok(client, "edge1@example.com")
    appt_id = _book(client, tok1)

    tok2 = _tok(client, "edge2@example.com")
    # patient 2 tries to cancel patient 1's appointment -> 404 (not found for them)
    assert client.post(f"/me/appointments/{appt_id}/cancel",
                       headers=_auth(tok2)).status_code == 404
    assert client.post(f"/me/appointments/{appt_id}/reschedule?new_slot_id=1",
                       headers=_auth(tok2)).status_code == 404
    assert client.get(f"/me/available-slots?appointment_id={appt_id}",
                      headers=_auth(tok2)).status_code == 404


def test_duplicate_document_via_api(client):
    tok = _tok(client, "edge2@example.com")
    payload = {"request": "cardiology follow-up",
               "documents": [{"filename": "ecg.pdf",
                              "content_base64": base64.b64encode(b"SAME-ECG-BYTES").decode()}]}
    client.post("/requests", headers=_auth(tok), json=payload)
    # submit the identical document again -> deduped, patient docs shouldn't double it
    client.post("/requests", headers=_auth(tok), json=payload)
    docs = client.get("/me/documents", headers=_auth(tok)).json()
    ecgs = [d for d in docs if d.get("type") == "ECG"]
    assert len(ecgs) == 1   # SHA-256 dedupe kept only one


def test_empty_request_does_not_book():
    """An empty/whitespace request is handled gracefully and books nothing."""
    import uuid
    from app.database import init_db
    from app.agents import build_graph
    init_db()
    graph = build_graph(checkpointer=None)
    final = graph.invoke(
        {"request": "   ", "patient_input": {"name": "E", "email": "empty@example.com"},
         "documents_input": [], "messages": [], "status": "running"},
        config={"configurable": {"thread_id": f"t-{uuid.uuid4().hex[:8]}"}})
    assert final.get("appointment_id") is None
    assert final["status"] == "completed"


def test_agent_skips_conflicting_slots_and_books_next():
    """A patient booking repeatedly gets successive non-conflicting slots,
    and rapid same-patient requests don't collide on workflow thread_id."""
    import uuid
    from app.database import init_db, SessionLocal
    from app.models import Department, Doctor, AppointmentSlot, SlotStatus
    from datetime import datetime, timedelta, timezone
    init_db()
    db = SessionLocal()
    # dedicated department so this test never competes for Cardiology slots
    dept = db.query(Department).filter_by(name="Neurology").first()
    if dept is None:
        dept = Department(name="Neurology", description="Nerve", active=True)
        db.add(dept); db.flush()
    doc = db.query(Doctor).filter_by(department_id=dept.id).first()
    if doc is None:
        doc = Doctor(department_id=dept.id, name="Dr. Nerve", active=True)
        db.add(doc); db.flush()
    base = datetime.now(timezone.utc).replace(microsecond=0) + timedelta(days=20)
    for i in range(8):
        st = base + timedelta(hours=3 * i)
        db.add(AppointmentSlot(doctor_id=doc.id, start_time=st,
                               end_time=st + timedelta(minutes=30), status=SlotStatus.OPEN))
    db.commit()
    db.close()

    from app.agents import build_graph
    graph = build_graph(checkpointer=None)
    booked = []
    # THREE DIFFERENT patients booking the same department -> three distinct
    # appointments on successive open slots (tests slot-skipping without tripping
    # the same-patient duplicate guard).
    for i in range(3):
        final = graph.invoke(
            {"request": "neurology follow-up next week",
             "patient_input": {"name": f"Multi{i}", "email": f"multi{i}@example.com"},
             "documents_input": [], "messages": [], "status": "running"},
            config={"configurable": {"thread_id": f"t-{uuid.uuid4().hex[:8]}"}})
        assert final["status"] == "completed"
        assert final.get("appointment_id") is not None
        booked.append(final["appointment_id"])
    assert len(set(booked)) == 3   # three distinct appointments, different slots


def test_duplicate_department_appointment_prevented():
    """Submitting the same request twice must not create two appointments in the
    same department; the second reuses the first, and any document still attaches."""
    import uuid
    from app.database import init_db, SessionLocal
    from app.models import (Department, Doctor, AppointmentSlot, SlotStatus,
                            Appointment, PatientProfile, User)
    from datetime import datetime, timedelta, timezone
    init_db()
    db = SessionLocal()
    dept = db.query(Department).filter_by(name="DupDept").first()
    if dept is None:
        dept = Department(name="DupDept", description="x", active=True)
        db.add(dept); db.flush()
        doc = Doctor(department_id=dept.id, name="Dr Dup", active=True)
        db.add(doc); db.flush()
        base = datetime.now(timezone.utc).replace(microsecond=0) + timedelta(days=15)
        for i in range(6):
            st = base + timedelta(hours=3 * i)
            db.add(AppointmentSlot(doctor_id=doc.id, start_time=st,
                                   end_time=st + timedelta(minutes=30), status=SlotStatus.OPEN))
        db.commit()
    db.close()

    from app.agents import build_graph
    graph = build_graph(checkpointer=None)

    def submit(docs=None):
        return graph.invoke(
            {"request": "dupdept please, i need an appointment",
             "patient_input": {"name": "DupPat", "email": "duppat@example.com"},
             "documents_input": docs or [], "messages": [], "status": "running"},
            config={"configurable": {"thread_id": f"t-{uuid.uuid4().hex[:8]}"}})

    f1 = submit()
    f2 = submit([{"filename": "scan.pdf", "content": b"DUP-SCAN"}])
    # Both requests resolve to the SAME appointment (no duplicate)
    assert f1.get("appointment_id") == f2.get("appointment_id")
    assert f2.get("duplicate_prevented") is True

    db = SessionLocal()
    prof = db.query(PatientProfile).join(User).filter(User.email == "duppat@example.com").first()
    assert db.query(Appointment).filter_by(patient_id=prof.id).count() == 1
    db.close()


def test_reschedule_does_not_conflict_with_itself():
    """An appointment must not block its own reschedule (same-time / different
    doctor), but must still be blocked from moving onto ANOTHER appointment's time."""
    from app.database import init_db, SessionLocal
    from app.models import Department, Doctor, AppointmentSlot, SlotStatus
    from app.tools import find_or_create_patient, book_appointment, reschedule_appointment
    from datetime import datetime, timedelta, timezone
    init_db()
    db = SessionLocal()
    dept = db.query(Department).filter_by(name="SelfConflictDept").first()
    if dept is None:
        dept = Department(name="SelfConflictDept", description="x", active=True)
        db.add(dept); db.flush()
        d1 = Doctor(department_id=dept.id, name="Dr One", active=True)
        d2 = Doctor(department_id=dept.id, name="Dr Two", active=True)
        db.add_all([d1, d2]); db.flush()
    else:
        d1, d2 = db.query(Doctor).filter_by(department_id=dept.id).limit(2).all()
    now = datetime.now(timezone.utc)
    t9 = now + timedelta(days=50)
    t11 = now + timedelta(days=50, hours=2)
    s9 = AppointmentSlot(doctor_id=d1.id, start_time=t9, end_time=t9 + timedelta(minutes=30), status=SlotStatus.OPEN)
    s9b = AppointmentSlot(doctor_id=d2.id, start_time=t9, end_time=t9 + timedelta(minutes=30), status=SlotStatus.OPEN)
    s11 = AppointmentSlot(doctor_id=d1.id, start_time=t11, end_time=t11 + timedelta(minutes=30), status=SlotStatus.OPEN)
    s11b = AppointmentSlot(doctor_id=d2.id, start_time=t11, end_time=t11 + timedelta(minutes=30), status=SlotStatus.OPEN)
    db.add_all([s9, s9b, s11, s11b]); db.commit()

    p = find_or_create_patient(db, "Self Conflict", "selfconflict@example.com")
    a1 = book_appointment(db, p["patient_id"], s9.id)

    # reschedule onto the SAME time with a different doctor -> allowed (no self-conflict)
    r_same = reschedule_appointment(db, a1["appointment_id"], s9b.id)
    assert r_same["success"] is True

    # now book a SECOND appointment at 11:00, then try to move the first onto it -> blocked
    a2 = book_appointment(db, p["patient_id"], s11.id)
    r_clash = reschedule_appointment(db, a1["appointment_id"], s11b.id)
    assert r_clash["success"] is False and r_clash["error"] == "patient_time_conflict"
    db.close()