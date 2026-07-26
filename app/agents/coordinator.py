"""
Coordinator Agent — entry point. Resolves the patient, opens a WorkflowRun
(persisted), and records the plan. Delegates the rest to specialized agents.
"""
import uuid
from app.database import SessionLocal
from app.models import WorkflowRun, WorkflowStatus
from app.tools import find_or_create_patient, write_audit
from app.agents.llm import llm_available, chat

SYSTEM_PROMPT = (
    "You are the Coordinator agent in a hospital ADMINISTRATION system. "
    "You never diagnose, prescribe, or give medical advice. You read an "
    "administrative patient request and produce a short, plain restatement of "
    "the administrative goal (e.g. 'book a cardiology follow-up and attach ECG'). "
    "Respond with one short sentence."
)


def coordinator_agent(state: dict) -> dict:
    db = SessionLocal()
    try:
        req = (state.get("request", "") or "").strip()
        pin = state.get("patient_input", {}) or {}

        # Guard: an empty request should not silently book anything.
        if not req:
            msgs = state.get("messages", [])
            msgs.append("Coordinator: empty request received; nothing to process.")
            return {
                "status": "completed",
                "confirmation": "Your message was empty. Please describe what you "
                                "need — for example, booking an appointment or "
                                "attaching a document.",
                "messages": msgs,
                "safety_verdict": "safe",
            }

        # Resolve/create the patient (real DB tool)
        patient = find_or_create_patient(
            db,
            name=pin.get("name", "Unknown Patient"),
            email=pin.get("email", "unknown@example.com"),
            phone=pin.get("phone"),
            date_of_birth=pin.get("date_of_birth"),
        )

        # Restate the goal (LLM if available, else echo the request)
        if llm_available():
            try:
                goal = chat(SYSTEM_PROMPT, f"Patient request: {req}")
            except Exception:
                goal = req
        else:
            goal = req

        # Open a persisted workflow run
        run = WorkflowRun(
            patient_id=patient["patient_id"],
            thread_id=f"wf-{patient['patient_id']}-{uuid.uuid4().hex[:12]}",
            original_request=req,
            current_step="coordinator",
            status=WorkflowStatus.RUNNING,
            state={"goal": goal},
        )
        db.add(run)
        db.commit()
        db.refresh(run)

        write_audit(db, action="workflow_started", entity_type="workflow_run",
                    entity_id=run.id, metadata={"goal": goal})

        msgs = state.get("messages", [])
        msgs.append(f"Coordinator: patient #{patient['patient_id']} resolved; goal = {goal}")
        return {
            "patient_id": patient["patient_id"],
            "workflow_run_id": run.id,
            "status": "running",
            "messages": msgs,
        }
    finally:
        db.close()