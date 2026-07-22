"""
Role-based access control — enforced in the backend (not by hiding UI).
Every protected endpoint depends on one of these; unauthorized roles get 403.
"""
from fastapi import Depends, HTTPException, status

from app.models import User, UserRole, PatientProfile
from app.database import get_db
from app.api.auth import get_current_user
from sqlalchemy.orm import Session


def require_roles(*roles: UserRole):
    def checker(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires role in {[r.value for r in roles]}; you are '{user.role.value}'.",
            )
        return user
    return checker


require_staff = require_roles(UserRole.STAFF, UserRole.ADMIN)
require_patient = require_roles(UserRole.PATIENT)
require_any = require_roles(UserRole.PATIENT, UserRole.STAFF, UserRole.ADMIN)


def current_patient_profile(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PatientProfile:
    """Resolve the authenticated patient's own profile (patients only see their own data)."""
    profile = db.query(PatientProfile).filter(PatientProfile.user_id == user.id).first()
    if profile is None:
        raise HTTPException(status_code=404, detail="No patient profile for this user.")
    return profile
