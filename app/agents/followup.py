"""
Follow-up Agent — creates an appointment reminder and schedules a post-visit
follow-up task. Tool-driven and persisted.
"""
from app.database import SessionLocal
from app.tools import create_reminder, create_followup, write_audit


def followup_agent(state: dict) -> dict:
    db = SessionLocal()
    try:
        patient_id = state.get("patient_id")
        appt_id = state.get("appointment_id")
        msgs = state.get("messages", [])
        reminder_ids = []

        if patient_id and appt_id:
            r = create_reminder(db, patient_id, appt_id, reminder_type="appointment")
            reminder_ids.append(r["reminder_id"])
            f = create_followup(db, patient_id, appt_id, days_after=14)
            reminder_ids.append(f["followup_id"])
            msgs.append(f"Follow-up: reminder #{r['reminder_id']} + "
                        f"follow-up #{f['followup_id']} scheduled")
        else:
            msgs.append("Follow-up: skipped (no appointment).")

        write_audit(db, action="followup_scheduled", entity_type="patient_profile",
                    entity_id=patient_id, metadata={"reminders": reminder_ids})
        return {"reminder_ids": reminder_ids, "messages": msgs}
    finally:
        db.close()
