"""
Consent tools — patient authorization is recorded and enforced. Consents are
persisted, auditable, and can be granted or revoked at any time. Sensitive
actions (e.g. storing documents) check consent first.
"""
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models import Consent, ConsentType
from app.tools.audit import write_audit


def _now() -> datetime:
    return datetime.now(timezone.utc)


def set_consent(db: Session, patient_id: int, consent_type: str, granted: bool,
                actor_id: int | None = None) -> dict:
    """Grant or revoke a consent for a patient. Idempotent; persisted + audited."""
    try:
        ctype = ConsentType(consent_type)
    except ValueError:
        return {"success": False, "error": f"invalid_consent_type:{consent_type}"}

    row = (db.query(Consent)
           .filter(Consent.patient_id == patient_id, Consent.consent_type == ctype)
           .first())
    if row is None:
        row = Consent(patient_id=patient_id, consent_type=ctype, granted=False)
        db.add(row)
        db.flush()

    row.granted = granted
    if granted:
        row.granted_at = _now()
    else:
        row.revoked_at = _now()
    db.commit()

    write_audit(db, action="consent_granted" if granted else "consent_revoked",
                entity_type="consent", entity_id=row.id, actor_id=actor_id,
                actor_type="patient",
                metadata={"consent_type": ctype.value, "granted": granted})
    return {"success": True, "consent_id": row.id,
            "consent_type": ctype.value, "granted": granted}


def has_consent(db: Session, patient_id: int, consent_type: str) -> bool:
    """True if the patient currently grants the given consent type."""
    try:
        ctype = ConsentType(consent_type)
    except ValueError:
        return False
    row = (db.query(Consent)
           .filter(Consent.patient_id == patient_id,
                   Consent.consent_type == ctype,
                   Consent.granted == True)  # noqa: E712
           .first())
    return row is not None


def get_consents(db: Session, patient_id: int) -> list[dict]:
    """Return the patient's consent state for every consent type (defaults false)."""
    existing = {c.consent_type: c for c in
                db.query(Consent).filter(Consent.patient_id == patient_id).all()}
    out = []
    for ctype in ConsentType:
        row = existing.get(ctype)
        out.append({
            "consent_type": ctype.value,
            "granted": bool(row.granted) if row else False,
            "granted_at": row.granted_at.isoformat() if row and row.granted_at else None,
            "revoked_at": row.revoked_at.isoformat() if row and row.revoked_at else None,
        })
    return out