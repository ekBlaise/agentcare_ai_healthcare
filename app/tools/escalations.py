"""
Escalation tool — the human-in-the-loop record. Creates a persisted Escalation
that staff must review/approve. Used by the Safety and Routing agents.
"""
from sqlalchemy.orm import Session

from app.models import Escalation, WorkflowRun, EscalationStatus, WorkflowStatus
from app.tools.audit import write_audit


def create_escalation(
    db: Session,
    reason: str,
    category: str = "general",           # emergency | sensitive | uncertain | general
    workflow_run_id: int | None = None,
) -> dict:
    """Record an escalation for human review and mark the workflow as escalated."""
    esc = Escalation(
        workflow_run_id=workflow_run_id,
        reason=reason,
        category=category,
        status=EscalationStatus.OPEN,
    )
    db.add(esc)

    if workflow_run_id is not None:
        run = db.query(WorkflowRun).filter(WorkflowRun.id == workflow_run_id).first()
        if run:
            run.status = WorkflowStatus.ESCALATED

    db.commit()
    db.refresh(esc)

    write_audit(db, action="escalation_created", entity_type="escalation", entity_id=esc.id,
                metadata={"category": category, "reason": reason,
                          "workflow_run_id": workflow_run_id})
    return {
        "success": True, "escalation_id": esc.id,
        "category": category, "status": esc.status.value,
    }
