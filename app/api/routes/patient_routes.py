"""
Patient endpoints — submit an administrative request (runs the agent workflow)
and view OWN status. Patients can only ever see their own data (enforced here).
"""
import base64

from fastapi import APIRouter, Depends, UploadFile, File
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User, Appointment, PatientDocument, Reminder
from app.api.deps import require_any, current_patient_profile
from app.api.auth import get_current_user
from app.api.schemas import RequestIn, WorkflowResult
from app.api.service import run_workflow
from app.tools import classify_and_store_document

router = APIRouter(tags=["patient"])


@router.post("/requests", response_model=WorkflowResult)
def submit_request(body: RequestIn, user: User = Depends(require_any),
                   db: Session = Depends(get_db)):
    """Submit an administrative request; the multi-agent workflow handles it."""
    docs = []
    for d in body.documents:
        try:
            content = base64.b64decode(d.content_base64)
        except Exception:
            content = b""
        docs.append({"filename": d.filename, "content": content,
                     "declared_type": d.declared_type})

    initial = {
        "request": body.request,
        "patient_input": {"name": user.name, "email": user.email},
        "documents_input": docs,
        "preferred_slot_id": body.preferred_slot_id,
        "messages": [], "status": "running",
    }
    final = run_workflow(initial)
    return WorkflowResult(
        workflow_run_id=final.get("workflow_run_id"),
        status=final.get("status", "unknown"),
        confirmation=final.get("confirmation"),
        department_name=final.get("department_name"),
        appointment_id=final.get("appointment_id"),
        escalated=bool(final.get("escalated")),
        missing_documents=final.get("missing_documents", []),
        trace=final.get("messages", []),
    )


@router.get("/me/appointments")
def my_appointments(profile=Depends(current_patient_profile), db: Session = Depends(get_db)):
    appts = db.query(Appointment).filter(Appointment.patient_id == profile.id).all()
    return [{
        "appointment_id": a.id,
        "status": a.status.value,
        "doctor": a.doctor.name if a.doctor else None,
        "department": a.doctor.department.name if a.doctor and a.doctor.department else None,
        "start_time": a.slot.start_time.isoformat() if a.slot else None,
        "reason": a.reason,
    } for a in appts]


@router.get("/me/documents")
def my_documents(profile=Depends(current_patient_profile), db: Session = Depends(get_db)):
    docs = db.query(PatientDocument).filter(PatientDocument.patient_id == profile.id).all()
    return [{"document_id": d.id, "type": d.document_type,
             "date": d.document_date, "checksum": d.checksum} for d in docs]


@router.get("/me/reminders")
def my_reminders(profile=Depends(current_patient_profile), db: Session = Depends(get_db)):
    rems = db.query(Reminder).filter(Reminder.patient_id == profile.id).all()
    return [{"reminder_id": r.id, "type": r.reminder_type,
             "scheduled_at": r.scheduled_at.isoformat() if r.scheduled_at else None,
             "status": r.status.value, "message": r.message} for r in rems]


@router.post("/me/documents/upload")
def upload_document(file: UploadFile = File(...),
                    profile=Depends(current_patient_profile), db: Session = Depends(get_db)):
    """Real multipart file upload -> classify + checksum-dedupe + store."""
    content = file.file.read()
    result = classify_and_store_document(db, profile.id, file.filename, content)
    return result
