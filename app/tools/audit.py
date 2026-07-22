"""
Audit logging tool. Every meaningful action in AgentCare writes an AuditEvent,
producing a complete, queryable trail (required by the challenge).
"""
from sqlalchemy.orm import Session

from app.models import AuditEvent


def write_audit(
    db: Session,
    action: str,
    entity_type: str | None = None,
    entity_id: int | None = None,
    actor_id: int | None = None,
    actor_type: str = "agent",
    metadata: dict | None = None,
) -> dict:
    """Persist an audit event and return its id + summary."""
    event = AuditEvent(
        actor_id=actor_id,
        actor_type=actor_type,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        event_metadata=metadata or {},
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return {
        "audit_id": event.id,
        "action": action,
        "entity_type": entity_type,
        "entity_id": entity_id,
    }
