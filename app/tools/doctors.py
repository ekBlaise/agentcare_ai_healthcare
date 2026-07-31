"""
Doctor management tools (admin). Doctors are schedulable resources belonging to a
department — not login users. All actions are audited.
"""
from sqlalchemy.orm import Session

from app.models import Doctor, Department, AppointmentSlot, SlotStatus
from app.tools.audit import write_audit


def list_doctors(db: Session, department_id: int | None = None,
                 include_inactive: bool = True) -> list[dict]:
    """List doctors, optionally filtered by department, with slot counts."""
    q = db.query(Doctor)
    if department_id is not None:
        q = q.filter(Doctor.department_id == department_id)
    if not include_inactive:
        q = q.filter(Doctor.active == True)  # noqa: E712
    out = []
    for d in q.order_by(Doctor.name).all():
        open_slots = (db.query(AppointmentSlot)
                      .filter(AppointmentSlot.doctor_id == d.id,
                              AppointmentSlot.status == SlotStatus.OPEN)
                      .count())
        out.append({
            "doctor_id": d.id,
            "name": d.name,
            "active": bool(d.active),
            "department_id": d.department_id,
            "department": d.department.name if d.department else None,
            "open_slots": open_slots,
        })
    return out


def add_doctor(db: Session, name: str, department_id: int,
               actor_id: int | None = None) -> dict:
    """Create a new doctor in a department."""
    name = (name or "").strip()
    if not name:
        return {"success": False, "error": "name_required"}
    dept = db.query(Department).filter(Department.id == department_id).first()
    if dept is None:
        return {"success": False, "error": "department_not_found"}

    doc = Doctor(name=name, department_id=department_id, active=True)
    db.add(doc)
    db.commit()
    db.refresh(doc)
    write_audit(db, action="doctor_added", entity_type="doctor", entity_id=doc.id,
                actor_id=actor_id, actor_type="admin",
                metadata={"name": name, "department_id": department_id})
    return {"success": True, "doctor_id": doc.id, "name": doc.name,
            "department_id": doc.department_id, "active": True}


def update_doctor(db: Session, doctor_id: int, name: str | None = None,
                  department_id: int | None = None, active: bool | None = None,
                  actor_id: int | None = None) -> dict:
    """Update a doctor's name, department, or active status."""
    doc = db.query(Doctor).filter(Doctor.id == doctor_id).first()
    if doc is None:
        return {"success": False, "error": "doctor_not_found"}

    changes = {}
    if name is not None and name.strip():
        doc.name = name.strip(); changes["name"] = doc.name
    if department_id is not None:
        dept = db.query(Department).filter(Department.id == department_id).first()
        if dept is None:
            return {"success": False, "error": "department_not_found"}
        doc.department_id = department_id; changes["department_id"] = department_id
    if active is not None:
        doc.active = bool(active); changes["active"] = doc.active

    db.commit()
    db.refresh(doc)
    write_audit(db, action="doctor_updated", entity_type="doctor", entity_id=doc.id,
                actor_id=actor_id, actor_type="admin", metadata=changes)
    return {"success": True, "doctor_id": doc.id, "name": doc.name,
            "department_id": doc.department_id, "active": bool(doc.active)}


def set_doctor_active(db: Session, doctor_id: int, active: bool,
                      actor_id: int | None = None) -> dict:
    """Activate or deactivate a doctor (deactivated doctors take no new bookings)."""
    return update_doctor(db, doctor_id, active=active, actor_id=actor_id)