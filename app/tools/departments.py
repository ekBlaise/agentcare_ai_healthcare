"""
Department lookup tool: maps a routing decision (a department name or hint)
to a real Department row. Uses exact then fuzzy substring matching against
the persisted department list — not a hardcoded map.
"""
from sqlalchemy.orm import Session

from app.models import Department
from app.tools.audit import write_audit


def list_departments(db: Session) -> list[dict]:
    rows = db.query(Department).filter(Department.active == True).all()  # noqa: E712
    return [{"id": d.id, "name": d.name, "description": d.description} for d in rows]


def lookup_department(db: Session, hint: str) -> dict:
    """
    Resolve a department by name/hint.
    Returns the matched department, or a list of candidates if uncertain.
    """
    hint_clean = (hint or "").strip().lower()
    departments = db.query(Department).filter(Department.active == True).all()  # noqa: E712

    # 1. exact (case-insensitive) match
    for d in departments:
        if d.name.lower() == hint_clean:
            write_audit(db, action="department_matched", entity_type="department",
                        entity_id=d.id, metadata={"hint": hint, "match": "exact"})
            return {"matched": True, "department_id": d.id, "name": d.name, "confidence": "exact"}

    # 2. substring match (hint in name or name in hint)
    partial = [d for d in departments
               if hint_clean and (hint_clean in d.name.lower() or d.name.lower() in hint_clean)]
    if len(partial) == 1:
        d = partial[0]
        write_audit(db, action="department_matched", entity_type="department",
                    entity_id=d.id, metadata={"hint": hint, "match": "partial"})
        return {"matched": True, "department_id": d.id, "name": d.name, "confidence": "partial"}

    # 3. uncertain — return candidates for the routing agent to disambiguate/escalate
    candidates = [{"id": d.id, "name": d.name} for d in (partial or departments)]
    write_audit(db, action="department_uncertain", entity_type="department",
                metadata={"hint": hint, "candidate_count": len(candidates)})
    return {"matched": False, "candidates": candidates, "confidence": "uncertain"}
