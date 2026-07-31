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
    """List appointments by status.

    status="awaiting_confirmation" (default): past appointments needing an outcome.
    status="upcoming": future active appointments (the staff schedule view),
      sorted by appointment start time.
    status="all" or any specific status value: filtered accordingly.
    """
    from datetime import datetime, timezone
    from app.models import Appointment, AppointmentSlot, AppointmentStatus

    q = db.query(Appointment)

    if status == "upcoming":
        now = datetime.now(timezone.utc)
        q = (q.join(AppointmentSlot, Appointment.slot_id == AppointmentSlot.id)
             .filter(AppointmentSlot.start_time >= now,
                     Appointment.status.in_([
                         AppointmentStatus.PENDING,
                         AppointmentStatus.CONFIRMED,
                         AppointmentStatus.RESCHEDULED,
                     ]))
             .order_by(AppointmentSlot.start_time.asc()))
    elif status != "all":
        try:
            q = q.filter(Appointment.status == AppointmentStatus(status))
            q = q.order_by(Appointment.created_at.desc())
        except ValueError:
            raise HTTPException(400, f"Invalid status '{status}'")
    else:
        q = q.order_by(Appointment.created_at.desc())

    rows = q.all()

    def _patient_name(a):
        if a.patient and a.patient.user:
            return a.patient.user.name
        return None

    def _patient_email(a):
        if a.patient and a.patient.user:
            return a.patient.user.email
        return None

    def _patient_mrn(a):
        return a.patient.mrn if a.patient else None

    return [{
        "appointment_id": a.id,
        "patient_id": a.patient_id,
        "patient_name": _patient_name(a),
        "patient_email": _patient_email(a),
        "patient_mrn": _patient_mrn(a),
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


@router.get("/analytics")
def analytics(user: User = Depends(require_staff), db: Session = Depends(get_db)):
    """
    Operational analytics computed live from persisted data (no hardcoded values):
    appointment status mix, escalation breakdown, department load, workflow
    outcomes, document stats, and headline KPIs.
    """
    from sqlalchemy import func
    from app.models import (
        Appointment, AppointmentStatus, Escalation, EscalationStatus,
        WorkflowRun, WorkflowStatus, Department, Doctor, PatientDocument,
        PatientProfile, Reminder,
    )

    def _counts(rows):
        return {str(k.value if hasattr(k, "value") else k): int(v) for k, v in rows}

    # Appointment status mix
    appt_rows = (db.query(Appointment.status, func.count(Appointment.id))
                 .group_by(Appointment.status).all())
    appt_by_status = _counts(appt_rows)

    # Escalations by category and by status
    esc_cat = _counts(db.query(Escalation.category, func.count(Escalation.id))
                      .group_by(Escalation.category).all())
    esc_status = _counts(db.query(Escalation.status, func.count(Escalation.id))
                         .group_by(Escalation.status).all())

    # Department load: appointments per department
    dept_rows = (db.query(Department.name, func.count(Appointment.id))
                 .select_from(Appointment)
                 .join(Doctor, Appointment.doctor_id == Doctor.id)
                 .join(Department, Doctor.department_id == Department.id)
                 .group_by(Department.name)
                 .order_by(func.count(Appointment.id).desc())
                 .all())
    dept_load = [{"department": n, "appointments": int(c)} for n, c in dept_rows]

    # Workflow outcomes
    wf_status = _counts(db.query(WorkflowRun.status, func.count(WorkflowRun.id))
                        .group_by(WorkflowRun.status).all())

    # Documents
    total_docs = db.query(func.count(PatientDocument.id)).scalar() or 0
    doc_types = _counts(db.query(PatientDocument.document_type, func.count(PatientDocument.id))
                        .group_by(PatientDocument.document_type).all())

    # Headline KPIs
    total_appts = sum(appt_by_status.values())
    completed = appt_by_status.get("completed", 0)
    missed = appt_by_status.get("missed", 0)
    finished = completed + missed
    attendance_rate = round(100 * completed / finished, 1) if finished else None
    open_escalations = esc_status.get("open", 0)
    total_patients = db.query(func.count(PatientProfile.id)).scalar() or 0
    total_reminders = db.query(func.count(Reminder.id)).scalar() or 0

    return {
        "kpis": {
            "total_appointments": total_appts,
            "total_patients": total_patients,
            "open_escalations": open_escalations,
            "attendance_rate_pct": attendance_rate,   # completed / (completed+missed)
            "total_documents": total_docs,
            "total_reminders": total_reminders,
        },
        "appointments_by_status": appt_by_status,
        "escalations_by_category": esc_cat,
        "escalations_by_status": esc_status,
        "department_load": dept_load,
        "workflows_by_status": wf_status,
        "documents_by_type": doc_types,
    }