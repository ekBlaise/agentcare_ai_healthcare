"""
Appointment tools — real availability queries, genuine conflict detection,
and full booking lifecycle (book / reschedule / cancel), all persisted.

Conflict detection is real: a slot can only be booked if it is OPEN and the
patient has no other active appointment overlapping that time window.
"""
from datetime import datetime, timezone

from sqlalchemy import and_
from sqlalchemy.orm import Session

from app.models import (
    Department, Doctor, AppointmentSlot, Appointment,
    SlotStatus, AppointmentStatus,
)
from app.tools.audit import write_audit


def _now() -> datetime:
    return datetime.now(timezone.utc)


def get_available_slots(
    db: Session,
    department_id: int | None = None,
    doctor_id: int | None = None,
    limit: int = 10,
    include_past: bool = False,
) -> list[dict]:
    """Return OPEN, FUTURE slots, optionally filtered by department or doctor.

    Past slots are excluded by default so the system never books an appointment
    in a time that has already passed.
    """
    q = (
        db.query(AppointmentSlot, Doctor, Department)
        .join(Doctor, AppointmentSlot.doctor_id == Doctor.id)
        .join(Department, Doctor.department_id == Department.id)
        .filter(AppointmentSlot.status == SlotStatus.OPEN)
    )
    if not include_past:
        q = q.filter(AppointmentSlot.start_time >= _now())
    if department_id is not None:
        q = q.filter(Department.id == department_id)
    if doctor_id is not None:
        q = q.filter(Doctor.id == doctor_id)

    q = q.order_by(AppointmentSlot.start_time).limit(limit)

    results = []
    for slot, doctor, dept in q.all():
        results.append({
            "slot_id": slot.id,
            "doctor_id": doctor.id,
            "doctor_name": doctor.name,
            "department": dept.name,
            "start_time": slot.start_time.isoformat(),
            "end_time": slot.end_time.isoformat(),
        })
    return results


def _patient_has_conflict(db: Session, patient_id: int, start: datetime, end: datetime) -> bool:
    """True if the patient already has an active appointment overlapping [start, end)."""
    active = (
        db.query(Appointment)
        .join(AppointmentSlot, Appointment.slot_id == AppointmentSlot.id)
        .filter(
            Appointment.patient_id == patient_id,
            Appointment.status.in_([
                AppointmentStatus.PENDING,
                AppointmentStatus.CONFIRMED,
                AppointmentStatus.RESCHEDULED,
            ]),
            # overlap test: existing.start < new.end AND existing.end > new.start
            and_(AppointmentSlot.start_time < end, AppointmentSlot.end_time > start),
        )
        .first()
    )
    return active is not None


def book_appointment(
    db: Session,
    patient_id: int,
    slot_id: int,
    reason: str | None = None,
) -> dict:
    """Book a slot for a patient with real conflict detection. Persists everything."""
    slot = db.query(AppointmentSlot).filter(AppointmentSlot.id == slot_id).first()
    if slot is None:
        return {"success": False, "error": "slot_not_found", "slot_id": slot_id}

    if slot.status != SlotStatus.OPEN:
        write_audit(db, action="booking_rejected", entity_type="slot", entity_id=slot_id,
                    metadata={"reason": "slot_not_open", "status": slot.status.value})
        return {"success": False, "error": "slot_not_open", "slot_id": slot_id}

    # Never book a slot in the past.
    slot_start = slot.start_time
    if slot_start.tzinfo is None:
        slot_start = slot_start.replace(tzinfo=timezone.utc)
    if slot_start < _now():
        write_audit(db, action="booking_rejected", entity_type="slot", entity_id=slot_id,
                    metadata={"reason": "slot_in_past"})
        return {"success": False, "error": "slot_in_past", "slot_id": slot_id}

    if _patient_has_conflict(db, patient_id, slot.start_time, slot.end_time):
        write_audit(db, action="booking_rejected", entity_type="patient", entity_id=patient_id,
                    metadata={"reason": "patient_time_conflict", "slot_id": slot_id})
        return {"success": False, "error": "patient_time_conflict", "slot_id": slot_id}

    appt = Appointment(
        patient_id=patient_id,
        doctor_id=slot.doctor_id,
        slot_id=slot.id,
        status=AppointmentStatus.CONFIRMED,
        reason=reason,
    )
    slot.status = SlotStatus.BOOKED
    db.add(appt)
    db.commit()
    db.refresh(appt)

    write_audit(db, action="appointment_booked", entity_type="appointment", entity_id=appt.id,
                actor_id=None, metadata={"slot_id": slot_id, "patient_id": patient_id})

    return {
        "success": True,
        "appointment_id": appt.id,
        "status": appt.status.value,
        "doctor_id": appt.doctor_id,
        "slot_id": slot.id,
        "start_time": slot.start_time.isoformat(),
    }


def reschedule_appointment(db: Session, appointment_id: int, new_slot_id: int) -> dict:
    """Move an appointment to a new open slot (with conflict checks). Frees the old slot."""
    appt = db.query(Appointment).filter(Appointment.id == appointment_id).first()
    if appt is None:
        return {"success": False, "error": "appointment_not_found"}
    if appt.status in (AppointmentStatus.CANCELLED, AppointmentStatus.COMPLETED):
        return {"success": False, "error": f"cannot_reschedule_{appt.status.value}"}

    new_slot = db.query(AppointmentSlot).filter(AppointmentSlot.id == new_slot_id).first()
    if new_slot is None or new_slot.status != SlotStatus.OPEN:
        return {"success": False, "error": "new_slot_unavailable"}

    if _patient_has_conflict(db, appt.patient_id, new_slot.start_time, new_slot.end_time):
        return {"success": False, "error": "patient_time_conflict"}

    old_slot = db.query(AppointmentSlot).filter(AppointmentSlot.id == appt.slot_id).first()
    if old_slot:
        old_slot.status = SlotStatus.OPEN            # free the old slot

    appt.slot_id = new_slot.id
    appt.doctor_id = new_slot.doctor_id
    appt.status = AppointmentStatus.RESCHEDULED
    new_slot.status = SlotStatus.BOOKED
    db.commit()
    db.refresh(appt)

    write_audit(db, action="appointment_rescheduled", entity_type="appointment",
                entity_id=appt.id, metadata={"from_slot": old_slot.id if old_slot else None,
                                             "to_slot": new_slot.id})
    return {
        "success": True,
        "appointment_id": appt.id,
        "status": appt.status.value,
        "new_slot_id": new_slot.id,
        "start_time": new_slot.start_time.isoformat(),
    }


def cancel_appointment(db: Session, appointment_id: int) -> dict:
    """Cancel an appointment and free its slot."""
    appt = db.query(Appointment).filter(Appointment.id == appointment_id).first()
    if appt is None:
        return {"success": False, "error": "appointment_not_found"}
    if appt.status == AppointmentStatus.CANCELLED:
        return {"success": False, "error": "already_cancelled"}

    slot = db.query(AppointmentSlot).filter(AppointmentSlot.id == appt.slot_id).first()
    if slot:
        slot.status = SlotStatus.OPEN
    appt.status = AppointmentStatus.CANCELLED
    db.commit()

    write_audit(db, action="appointment_cancelled", entity_type="appointment",
                entity_id=appt.id, metadata={"freed_slot": slot.id if slot else None})
    return {"success": True, "appointment_id": appt.id, "status": appt.status.value}


def expire_past_appointments(db: Session) -> dict:
    """
    Housekeeping: mark confirmed/pending appointments whose time has passed as
    COMPLETED, and free/expire OPEN slots that are now in the past. Safe to run
    repeatedly (idempotent). Returns counts.
    """
    now = _now()

    # Past active appointments -> completed
    active = (
        db.query(Appointment)
        .join(AppointmentSlot, Appointment.slot_id == AppointmentSlot.id)
        .filter(
            Appointment.status.in_([
                AppointmentStatus.PENDING,
                AppointmentStatus.CONFIRMED,
                AppointmentStatus.RESCHEDULED,
            ]),
            AppointmentSlot.end_time < now,
        )
        .all()
    )
    for appt in active:
        appt.status = AppointmentStatus.COMPLETED

    # Past OPEN slots -> mark HELD so they are no longer offered (kept for audit)
    stale_slots = (
        db.query(AppointmentSlot)
        .filter(AppointmentSlot.status == SlotStatus.OPEN,
                AppointmentSlot.start_time < now)
        .all()
    )
    for s in stale_slots:
        s.status = SlotStatus.HELD

    db.commit()
    if active or stale_slots:
        write_audit(db, action="appointments_expired", entity_type="system",
                    metadata={"completed": len(active), "expired_slots": len(stale_slots)})
    return {"completed": len(active), "expired_open_slots": len(stale_slots)}