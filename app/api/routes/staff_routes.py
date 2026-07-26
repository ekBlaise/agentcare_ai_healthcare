"""
Staff/admin endpoints — review escalations (human-in-the-loop approval),
inspect workflows and the audit trail, manage departments. All require staff/admin
role, enforced in the backend.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (
    User, Escalation, WorkflowRun, AuditEvent, Department,
    EscalationStatus,
)
from app.api.deps import require_staff
from app.api.schemas import ReviewIn
from app.tools import write_audit, create_reminder

router = APIRouter(prefix="/staff", tags=["staff"])


@router.get("/escalations")
def list_escalations(status: str = "open", user: User = Depends(require_staff),
                     db: Session = Depends(get_db)):
    q = db.query(Escalation)
    if status != "all":
        try:
            q = q.filter(Escalation.status == EscalationStatus(status))
        except ValueError:
            raise HTTPException(400, f"Invalid status '{status}'")
    return [{
        "escalation_id": e.id, "category": e.category, "reason": e.reason,
        "status": e.status.value, "workflow_run_id": e.workflow_run_id,
        "created_at": e.created_at.isoformat() if e.created_at else None,
    } for e in q.order_by(Escalation.created_at.desc()).all()]


@router.post("/escalations/{escalation_id}/review")
def review_escalation(escalation_id: int, body: ReviewIn,
                      user: User = Depends(require_staff), db: Session = Depends(get_db)):
    """Approve or reject an escalation — a persisted human-in-the-loop decision."""
    esc = db.query(Escalation).filter(Escalation.id == escalation_id).first()
    if esc is None:
        raise HTTPException(404, "Escalation not found")
    if esc.status != EscalationStatus.OPEN:
        raise HTTPException(409, f"Escalation already {esc.status.value}")

    esc.status = EscalationStatus.APPROVED if body.decision == "approve" else EscalationStatus.REJECTED
    esc.reviewed_by = user.id
    esc.review_notes = body.notes
    esc.reviewed_at = datetime.now(timezone.utc)
    db.commit()

    write_audit(db, action=f"escalation_{body.decision}d", entity_type="escalation",
                entity_id=esc.id, actor_id=user.id, actor_type=user.role.value,
                metadata={"notes": body.notes})

    # Notify the patient of the decision so they see the outcome (not silent).
    run = esc.workflow_run
    if run is not None and run.patient_id is not None:
        decision_word = "approved" if body.decision == "approve" else "declined"
        note = f" Staff note: {body.notes}" if body.notes else ""
        create_reminder(
            db, patient_id=run.patient_id, reminder_type="review_update",
            message=(f"A staff member reviewed your request and {decision_word} it.{note}"),
            scheduled_at=datetime.now(timezone.utc),
        )

    return {"escalation_id": esc.id, "status": esc.status.value,
            "reviewed_by": user.name}


@router.get("/workflows")
def list_workflows(user: User = Depends(require_staff), db: Session = Depends(get_db)):
    runs = db.query(WorkflowRun).order_by(WorkflowRun.created_at.desc()).all()
    return [{
        "workflow_run_id": r.id, "patient_id": r.patient_id,
        "status": r.status.value, "current_step": r.current_step,
        "request": r.original_request,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    } for r in runs]


@router.get("/workflows/{run_id}")
def workflow_detail(run_id: int, user: User = Depends(require_staff),
                    db: Session = Depends(get_db)):
    run = db.query(WorkflowRun).filter(WorkflowRun.id == run_id).first()
    if run is None:
        raise HTTPException(404, "Workflow not found")
    return {
        "workflow_run_id": run.id, "status": run.status.value,
        "current_step": run.current_step, "request": run.original_request,
        "state": run.state,   # the persisted agent-state snapshot
    }


@router.get("/audit")
def audit_trail(limit: int = 100, user: User = Depends(require_staff),
                db: Session = Depends(get_db)):
    events = db.query(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(limit).all()
    return [{
        "id": e.id, "action": e.action, "actor_type": e.actor_type,
        "actor_id": e.actor_id, "entity_type": e.entity_type,
        "entity_id": e.entity_id, "metadata": e.event_metadata,
        "created_at": e.created_at.isoformat() if e.created_at else None,
    } for e in events]


@router.get("/departments")
def list_departments_endpoint(user: User = Depends(require_staff),
                              db: Session = Depends(get_db)):
    depts = db.query(Department).all()
    return [{"id": d.id, "name": d.name, "active": d.active,
             "doctors": len(d.doctors)} for d in depts]


@router.get("/appointments")
def list_appointments(status: str = "awaiting_confirmation",
                      user: User = Depends(require_staff), db: Session = Depends(get_db)):
    """List appointments by status (default: those awaiting outcome confirmation)."""
    from app.models import Appointment, AppointmentStatus
    q = db.query(Appointment)
    if status != "all":
        try:
            q = q.filter(Appointment.status == AppointmentStatus(status))
        except ValueError:
            raise HTTPException(400, f"Invalid status '{status}'")
    rows = q.order_by(Appointment.created_at.desc()).all()
    return [{
        "appointment_id": a.id,
        "patient_id": a.patient_id,
        "status": a.status.value,
        "doctor": a.doctor.name if a.doctor else None,
        "department": a.doctor.department.name if a.doctor and a.doctor.department else None,
        "start_time": a.slot.start_time.isoformat() if a.slot else None,
        "reason": a.reason,
    } for a in rows]


@router.post("/appointments/{appointment_id}/outcome")
def record_outcome(appointment_id: int, attended: bool,
                   user: User = Depends(require_staff), db: Session = Depends(get_db)):
    """Record whether a past appointment was attended (COMPLETED) or MISSED."""
    from app.tools import record_appointment_outcome
    result = record_appointment_outcome(db, appointment_id, attended, actor_id=user.id)
    if not result.get("success"):
        raise HTTPException(status_code=409, detail=result.get("error", "record_failed"))
    return result