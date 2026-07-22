"""
Appointment Agent — retrieves availability, checks conflicts, and books a slot
in the routed department. Purely tool-driven (deterministic, persisted).
"""
from app.database import SessionLocal
from app.tools import get_available_slots, book_appointment, write_audit


def appointment_agent(state: dict) -> dict:
    db = SessionLocal()
    try:
        dept_id = state.get("department_id")
        patient_id = state.get("patient_id")
        msgs = state.get("messages", [])

        if not dept_id or not patient_id:
            msgs.append("Appointment: skipped (no department or patient).")
            return {"messages": msgs}

        slots = get_available_slots(db, department_id=dept_id, limit=5)
        if not slots:
            msgs.append("Appointment: no open slots available.")
            return {"messages": msgs, "appointment_status": "no_slots"}

        # honor a preferred slot if the patient chose one, else take the earliest
        preferred = state.get("preferred_slot_id")
        slot_id = preferred if preferred in {s["slot_id"] for s in slots} else slots[0]["slot_id"]

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

        msgs.append(f"Appointment: booking failed ({result.get('error')}).")
        return {"appointment_status": f"failed:{result.get('error')}", "messages": msgs}
    finally:
        db.close()
