"""
Reminder & follow-up tools. Creates persisted reminder/follow-up tasks tied to
a patient and (optionally) an appointment.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models import Reminder, Appointment, ReminderStatus
from app.tools.audit import write_audit


def create_reminder(
    db: Session,
    patient_id: int,
    appointment_id: int | None = None,
    reminder_type: str = "appointment",
    message: str | None = None,
    scheduled_at: datetime | None = None,
) -> dict:
    """Create a reminder. Defaults to 24h before the appointment start if available.

    Idempotent: if an active reminder of this type already exists for the
    appointment, it is returned instead of creating a duplicate.
    """
    if appointment_id is not None:
        existing = (db.query(Reminder)
                    .filter(Reminder.appointment_id == appointment_id,
                            Reminder.reminder_type == reminder_type,
                            Reminder.status == ReminderStatus.SCHEDULED)
                    .first())
        if existing:
            return {"success": True, "reminder_id": existing.id,
                    "reminder_type": reminder_type,
                    "scheduled_at": existing.scheduled_at.isoformat()
                    if existing.scheduled_at else None,
                    "duplicate": True}

    if scheduled_at is None and appointment_id is not None:
        appt = db.query(Appointment).filter(Appointment.id == appointment_id).first()
        if appt and appt.slot:
            scheduled_at = appt.slot.start_time - timedelta(hours=24)
    if scheduled_at is None:
        scheduled_at = datetime.now(timezone.utc) + timedelta(days=1)

    reminder = Reminder(
        patient_id=patient_id,
        appointment_id=appointment_id,
        reminder_type=reminder_type,
        message=message or "You have an upcoming appointment.",
        scheduled_at=scheduled_at,
        status=ReminderStatus.SCHEDULED,
    )
    db.add(reminder)
    db.commit()
    db.refresh(reminder)

    write_audit(db, action="reminder_created", entity_type="reminder", entity_id=reminder.id,
                metadata={"type": reminder_type, "appointment_id": appointment_id})
    return {
        "success": True, "reminder_id": reminder.id,
        "reminder_type": reminder_type,
        "scheduled_at": scheduled_at.isoformat(),
    }


def create_followup(
    db: Session,
    patient_id: int,
    appointment_id: int | None = None,
    days_after: int = 14,
    message: str | None = None,
) -> dict:
    """Schedule a post-visit follow-up task N days after the appointment.

    Idempotent: if an active follow-up already exists for the appointment, it is
    returned instead of creating a duplicate.
    """
    if appointment_id is not None:
        existing = (db.query(Reminder)
                    .filter(Reminder.appointment_id == appointment_id,
                            Reminder.reminder_type == "follow_up",
                            Reminder.status == ReminderStatus.SCHEDULED)
                    .first())
        if existing:
            return {"success": True, "followup_id": existing.id,
                    "scheduled_at": existing.scheduled_at.isoformat()
                    if existing.scheduled_at else None,
                    "duplicate": True}

    base = datetime.now(timezone.utc)
    if appointment_id is not None:
        appt = db.query(Appointment).filter(Appointment.id == appointment_id).first()
        if appt and appt.slot:
            base = appt.slot.start_time
    scheduled_at = base + timedelta(days=days_after)

    reminder = Reminder(
        patient_id=patient_id,
        appointment_id=appointment_id,
        reminder_type="follow_up",
        message=message or f"Post-visit follow-up ({days_after} days after your appointment).",
        scheduled_at=scheduled_at,
        status=ReminderStatus.SCHEDULED,
    )
    db.add(reminder)
    db.commit()
    db.refresh(reminder)

    write_audit(db, action="followup_created", entity_type="reminder", entity_id=reminder.id,
                metadata={"days_after": days_after, "appointment_id": appointment_id})
    return {
        "success": True, "followup_id": reminder.id,
        "scheduled_at": scheduled_at.isoformat(),
    }


def cancel_reminders_for_appointment(db: Session, appointment_id: int) -> dict:
    """Cancel all scheduled reminders/follow-ups tied to an appointment.

    Called when an appointment is cancelled or rescheduled so reminders never
    point at a stale appointment. Returns the count cancelled.
    """
    rows = (db.query(Reminder)
            .filter(Reminder.appointment_id == appointment_id,
                    Reminder.status == ReminderStatus.SCHEDULED)
            .all())
    for r in rows:
        r.status = ReminderStatus.CANCELLED
    db.commit()
    if rows:
        write_audit(db, action="reminders_cancelled", entity_type="appointment",
                    entity_id=appointment_id, metadata={"count": len(rows)})
    return {"cancelled": len(rows)}