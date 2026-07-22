"""
Patient identity tool: find an existing patient by email, or create a new
User + PatientProfile. Real DB logic — no fixed responses.
"""
from sqlalchemy.orm import Session

from app.models import User, PatientProfile, UserRole
from app.security import hash_password
from app.tools.audit import write_audit


def find_or_create_patient(
    db: Session,
    name: str,
    email: str,
    phone: str | None = None,
    date_of_birth: str | None = None,
    preferred_language: str = "English",
    emergency_contact: str | None = None,
) -> dict:
    """
    Resolve a patient by email. If the user exists, return their profile
    (creating a PatientProfile if somehow missing). Otherwise create both.
    """
    email = email.strip().lower()
    user = db.query(User).filter(User.email == email).first()
    created = False

    if user is None:
        user = User(
            name=name.strip(),
            email=email,
            password_hash=hash_password("changeme-" + email),  # placeholder; real auth on Day 4
            role=UserRole.PATIENT,
        )
        db.add(user)
        db.flush()
        created = True

    profile = db.query(PatientProfile).filter(PatientProfile.user_id == user.id).first()
    if profile is None:
        profile = PatientProfile(
            user_id=user.id,
            phone=phone,
            date_of_birth=date_of_birth,
            preferred_language=preferred_language,
            emergency_contact=emergency_contact,
        )
        db.add(profile)
        db.flush()
        created = True

    db.commit()
    db.refresh(profile)

    write_audit(
        db,
        action="patient_created" if created else "patient_resolved",
        entity_type="patient_profile",
        entity_id=profile.id,
        actor_id=user.id,
        actor_type="agent",
        metadata={"email": email, "created": created},
    )

    return {
        "patient_id": profile.id,
        "user_id": user.id,
        "name": user.name,
        "email": user.email,
        "created": created,
    }
