"""
Terminal nodes:
 - escalate_node: finalizes an escalated workflow (state persisted, status set)
 - confirm_node : assembles a confirmation FROM PERSISTED RECORDS and marks the
                  workflow complete. Never fabricates results.
"""
from app.database import SessionLocal
from app.models import WorkflowRun, Appointment, WorkflowStatus
from app.tools import write_audit


def _persist_state(db, state: dict, status: WorkflowStatus, step: str):
    run_id = state.get("workflow_run_id")
    if not run_id:
        return
    run = db.query(WorkflowRun).filter(WorkflowRun.id == run_id).first()
    if run:
        run.status = status
        run.current_step = step
        # store a JSON-safe snapshot of the agent state
        safe = {k: v for k, v in state.items() if k != "documents_input"}
        run.state = safe
        db.commit()


def escalate_node(state: dict) -> dict:
    db = SessionLocal()
    try:
        msgs = state.get("messages", [])
        msgs.append("Workflow halted and escalated for human review.")
        _persist_state(db, {**state, "messages": msgs}, WorkflowStatus.ESCALATED, "escalated")
        write_audit(db, action="workflow_escalated", entity_type="workflow_run",
                    entity_id=state.get("workflow_run_id"))
        return {"status": "escalated", "messages": msgs,
                "confirmation": "Your request needs staff review and has been escalated. "
                                "A staff member will follow up."}
    finally:
        db.close()


def confirm_node(state: dict) -> dict:
    db = SessionLocal()
    try:
        msgs = state.get("messages", [])
        parts = []

        appt_id = state.get("appointment_id")
        if appt_id:
            appt = db.query(Appointment).filter(Appointment.id == appt_id).first()
            if appt and appt.slot:
                parts.append(
                    f"Appointment #{appt.id} confirmed with {appt.doctor.name} "
                    f"({appt.doctor.department.name}) at "
                    f"{appt.slot.start_time.strftime('%Y-%m-%d %H:%M')}."
                )
        if state.get("stored_documents"):
            parts.append(f"{len(state['stored_documents'])} document(s) recorded.")
        if state.get("missing_documents"):
            parts.append(f"Please bring: {', '.join(state['missing_documents'])}.")
        if state.get("reminder_ids"):
            parts.append("A reminder and a follow-up task have been scheduled.")

        confirmation = " ".join(parts) if parts else "Your administrative request has been processed."
        msgs.append("Confirmation assembled from persisted records.")

        _persist_state(db, {**state, "messages": msgs, "confirmation": confirmation},
                       WorkflowStatus.COMPLETED, "completed")
        write_audit(db, action="workflow_completed", entity_type="workflow_run",
                    entity_id=state.get("workflow_run_id"))
        return {"status": "completed", "confirmation": confirmation, "messages": msgs}
    finally:
        db.close()
