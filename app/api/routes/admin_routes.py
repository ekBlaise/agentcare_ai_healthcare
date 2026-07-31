"""
Admin endpoints — user administration. Admin-only (enforced in the backend):
list all staff and patients, and create new staff or patient accounts.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User, PatientProfile, UserRole
from app.api.deps import require_admin
from app.api.schemas import CreateUserIn
from app.security import hash_password
from app.tools import write_audit

router = APIRouter(prefix="/admin", tags=["admin"])


def _user_dict(u: User) -> dict:
    return {
        "id": u.id, "name": u.name, "email": u.email, "role": u.role.value,
        "created_at": u.created_at.isoformat() if u.created_at else None,
    }


@router.get("/users")
def list_users(role: str = "all", user: User = Depends(require_admin),
               db: Session = Depends(get_db)):
    """List all users, optionally filtered by role (patient / staff / admin)."""
    q = db.query(User)
    if role != "all":
        try:
            q = q.filter(User.role == UserRole(role))
        except ValueError:
            raise HTTPException(400, f"Invalid role '{role}'")
    return [_user_dict(u) for u in q.order_by(User.created_at.desc()).all()]


@router.post("/users", status_code=201)
def create_user(body: CreateUserIn, user: User = Depends(require_admin),
                db: Session = Depends(get_db)):
    """Create a new staff or patient account. Patients also get a profile."""
    name = (body.name or "").strip()
    email = (body.email or "").strip().lower()
    if not (name and email and body.password):
        raise HTTPException(400, "Name, email, and password are all required.")
    if len(body.password) < 6:
        raise HTTPException(400, "Password must be at least 6 characters.")
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(409, "An account with this email already exists.")

    role = UserRole(body.role)
    new_user = User(name=name, email=email,
                    password_hash=hash_password(body.password), role=role)
    db.add(new_user)
    db.flush()
    if role == UserRole.PATIENT:
        db.add(PatientProfile(user_id=new_user.id, preferred_language="English"))
    db.commit()

    write_audit(db, action="user_created", entity_type="user", entity_id=new_user.id,
                actor_id=user.id, actor_type=user.role.value,
                metadata={"role": role.value, "email": email})
    return _user_dict(new_user)


# ── Doctor management (doctors are schedulable resources, not login users) ──
@router.get("/doctors")
def admin_list_doctors(department_id: int | None = None,
                       user: User = Depends(require_admin), db: Session = Depends(get_db)):
    from app.tools import list_doctors
    return list_doctors(db, department_id=department_id)


@router.post("/doctors", status_code=201)
def admin_add_doctor(name: str, department_id: int,
                     user: User = Depends(require_admin), db: Session = Depends(get_db)):
    from app.tools import add_doctor
    result = add_doctor(db, name, department_id, actor_id=user.id)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "add_failed"))
    return result


@router.patch("/doctors/{doctor_id}")
def admin_update_doctor(doctor_id: int, name: str | None = None,
                        department_id: int | None = None, active: bool | None = None,
                        user: User = Depends(require_admin), db: Session = Depends(get_db)):
    from app.tools import update_doctor
    result = update_doctor(db, doctor_id, name=name, department_id=department_id,
                           active=active, actor_id=user.id)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "update_failed"))
    return result


# ── Department management ──
@router.get("/departments")
def admin_list_departments(user: User = Depends(require_admin), db: Session = Depends(get_db)):
    from app.models import Department, Doctor
    out = []
    for d in db.query(Department).order_by(Department.name).all():
        doc_count = db.query(Doctor).filter(Doctor.department_id == d.id).count()
        out.append({"department_id": d.id, "name": d.name, "description": d.description,
                    "active": bool(d.active), "doctor_count": doc_count})
    return out


@router.post("/departments", status_code=201)
def admin_add_department(name: str, description: str | None = None,
                         user: User = Depends(require_admin), db: Session = Depends(get_db)):
    from app.tools import add_department
    result = add_department(db, name, description, actor_id=user.id)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "add_failed"))
    return result


@router.patch("/departments/{department_id}")
def admin_update_department(department_id: int, name: str | None = None,
                            description: str | None = None, active: bool | None = None,
                            user: User = Depends(require_admin), db: Session = Depends(get_db)):
    from app.tools import update_department
    result = update_department(db, department_id, name=name, description=description,
                               active=active, actor_id=user.id)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "update_failed"))
    return result