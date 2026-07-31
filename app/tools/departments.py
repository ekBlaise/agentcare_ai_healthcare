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


def add_department(db: Session, name: str, description: str | None = None,
                   actor_id: int | None = None) -> dict:
    """Create a new department (admin). Names are unique."""
    from app.models import Department
    from app.tools.audit import write_audit
    name = (name or "").strip()
    if not name:
        return {"success": False, "error": "name_required"}
    if db.query(Department).filter(Department.name == name).first():
        return {"success": False, "error": "department_exists"}
    dept = Department(name=name, description=(description or "").strip() or None, active=True)
    db.add(dept)
    db.commit()
    db.refresh(dept)
    write_audit(db, action="department_added", entity_type="department", entity_id=dept.id,
                actor_id=actor_id, actor_type="admin", metadata={"name": name})
    return {"success": True, "department_id": dept.id, "name": dept.name, "active": True}


def update_department(db: Session, department_id: int, name: str | None = None,
                      description: str | None = None, active: bool | None = None,
                      actor_id: int | None = None) -> dict:
    """Update a department's name, description, or active status (admin)."""
    from app.models import Department
    from app.tools.audit import write_audit
    dept = db.query(Department).filter(Department.id == department_id).first()
    if dept is None:
        return {"success": False, "error": "department_not_found"}
    changes = {}
    if name is not None and name.strip():
        clash = (db.query(Department)
                 .filter(Department.name == name.strip(), Department.id != department_id)
                 .first())
        if clash:
            return {"success": False, "error": "department_exists"}
        dept.name = name.strip(); changes["name"] = dept.name
    if description is not None:
        dept.description = description.strip() or None; changes["description"] = dept.description
    if active is not None:
        dept.active = bool(active); changes["active"] = dept.active
    db.commit()
    db.refresh(dept)
    write_audit(db, action="department_updated", entity_type="department",
                entity_id=dept.id, actor_id=actor_id, actor_type="admin", metadata=changes)
    return {"success": True, "department_id": dept.id, "name": dept.name,
            "description": dept.description, "active": bool(dept.active)}