"""
Appointment Agent — retrieves availability, checks conflicts, and books a slot
in the routed department. Purely tool-driven (deterministic, persisted).
"""
from app.database import SessionLocal
from app.tools import get_available_slots, book_appointment, write_audit, expire_past_appointments


def appointment_agent(state: dict) -> dict:
    db = SessionLocal()
    try:
        dept_id = state.get("department_id")
        patient_id = state.get("patient_id")
        msgs = state.get("messages", [])

        if not dept_id or not patient_id:
            msgs.append("Appointment: skipped (no department or patient).")
            return {"messages": msgs}

        # Self-healing: expire any past appointments/slots before offering times.
        expire_past_appointments(db)

        slots = get_available_slots(db, department_id=dept_id, limit=10)
        if not slots:
            msgs.append("Appointment: no open slots available.")
            return {"messages": msgs, "appointment_status": "no_slots"}

        # If the patient chose a specific slot, try that first; otherwise try the
        # open slots in time order, skipping any that conflict with an existing
        # appointment, and book the first one that succeeds.
        preferred = state.get("preferred_slot_id")
        ordered_ids = [s["slot_id"] for s in slots]
        if preferred in ordered_ids:
            ordered_ids = [preferred] + [i for i in ordered_ids if i != preferred]

        last_error = None
        for slot_id in ordered_ids:
            result = book_appointment(db, patient_id, slot_id, reason=state.get("request", ""))
            if result.get("success"):
                msgs.append(f"Appointment: booked #{result['appointment_id']} "
                            f"({result['status']}) at {result['start_time']}")
                return {
                    "appointment_id": result["appointment_id"],
                    "appointment_status": result["status"],
                    "booked_slot": {"slot_id": slot_id, "start_time": result["start_time"]},
                    "messages": msgs,
                }
            last_error = result.get("error")
            # a time conflict just means "try the next slot"; other errors do too
            continue

        # Every candidate slot conflicted or failed.
        if last_error == "patient_time_conflict":
            msgs.append("Appointment: you already have an appointment at every "
                        "available time in this department.")
            return {"appointment_status": "failed:patient_time_conflict", "messages": msgs}
        msgs.append(f"Appointment: booking failed ({last_error}).")
        return {"appointment_status": f"failed:{last_error}", "messages": msgs}
    finally:
        db.close()