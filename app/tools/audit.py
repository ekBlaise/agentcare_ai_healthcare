"""
Audit logging tool. Every meaningful action in AgentCare writes an AuditEvent,
producing a complete, queryable trail (required by the challenge).

Privacy by design: audit metadata is minimized before it is persisted. Direct
identifiers (email, phone, raw filenames) are masked so the audit trail records
*what happened* without duplicating PII across the database. IDs are retained so
an authorized user can still resolve the full record when legitimately needed.
"""
import re

from sqlalchemy.orm import Session

from app.models import AuditEvent

# Metadata keys whose values are treated as personally identifying and masked.
_PII_KEYS = {"email", "phone", "name", "patient_name", "patient_email",
             "emergency_contact", "date_of_birth", "dob", "filename", "file_path"}


def _mask_email(value: str) -> str:
    m = re.match(r"^([^@]).*(@.*)$", value)
    return f"{m.group(1)}***{m.group(2)}" if m else "***"


def _minimize(metadata: dict) -> dict:
    """Return a copy of metadata with PII values masked (data minimization)."""
    clean = {}
    for k, v in (metadata or {}).items():
        if k in _PII_KEYS and isinstance(v, str) and v:
            if "email" in k and "@" in v:
                clean[k] = _mask_email(v)
            elif k in ("filename", "file_path"):
                # keep only the extension, drop the identifying name
                ext = v.rsplit(".", 1)[-1] if "." in v else "file"
                clean[k] = f"***.{ext}"
            else:
                clean[k] = "***"
        else:
            clean[k] = v
    return clean


def write_audit(
    db: Session,
    action: str,
    entity_type: str | None = None,
    entity_id: int | None = None,
    actor_id: int | None = None,
    actor_type: str = "agent",
    metadata: dict | None = None,
) -> dict:
    """Persist an audit event (with PII minimized) and return its id + summary."""
    event = AuditEvent(
        actor_id=actor_id,
        actor_type=actor_type,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        event_metadata=_minimize(metadata),
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