"""
Patient identity tool: find an existing patient by email, or create a new
User + PatientProfile. Real DB logic — no fixed responses.
"""
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import User, PatientProfile, UserRole
from app.security import hash_password
from app.tools.audit import write_audit


def _generate_mrn(db: Session) -> str:
    """Generate a unique medical record number, e.g. MRN-000042."""
    from app.models import PatientProfile as _PP
    n = db.query(_PP).count() + 1
    for _ in range(1000):
        candidate = f"MRN-{n:06d}"
        if db.query(_PP).filter(_PP.mrn == candidate).first() is None:
            return candidate
        n += 1
    import uuid
    return f"MRN-{uuid.uuid4().hex[:8].upper()}"


def find_or_create_patient(
    db: Session,
    name: str,
    email: str,
    phone: str | None = None,
    date_of_birth: str | None = None,
    preferred_language: str = "English",
    emergency_contact: str | None = None,
    mrn: str | None = None,
) -> dict:
    """
    Resolve a patient by stable identity, then create if unmatched.

    Identity resolution order (strongest first):
      1. MRN, if provided (the canonical medical-record identifier)
      2. email (unique login identity)
      3. name + date_of_birth (catches the same person arriving with a new email)

    Each new patient is assigned a unique MRN.
    """
    email = email.strip().lower()
    name = name.strip()
    created = False
    profile = None

    # 1. MRN match (canonical identity)
    if mrn:
        profile = db.query(PatientProfile).filter(PatientProfile.mrn == mrn).first()

    # 2. email match
    user = db.query(User).filter(User.email == email).first()
    if profile is None and user is not None:
        profile = db.query(PatientProfile).filter(PatientProfile.user_id == user.id).first()

    # 3. name + DOB match (same person, different email)
    if profile is None and date_of_birth:
        candidate = (db.query(PatientProfile)
                     .join(User, PatientProfile.user_id == User.id)
                     .filter(func.lower(User.name) == name.lower(),
                             PatientProfile.date_of_birth == date_of_birth)
                     .first())
        if candidate is not None:
            profile = candidate
            user = candidate.user

    if user is None:
        user = User(
            name=name,
            email=email,
            password_hash=hash_password("changeme-" + email),  # placeholder; real auth via /auth
            role=UserRole.PATIENT,
        )
        db.add(user)
        db.flush()
        created = True

    if profile is None:
        profile = PatientProfile(
            user_id=user.id,
            mrn=mrn or _generate_mrn(db),
            phone=phone,
            date_of_birth=date_of_birth,
            preferred_language=preferred_language,
            emergency_contact=emergency_contact,
        )
        db.add(profile)
        db.flush()
        created = True
    elif profile.mrn is None:
        # backfill an MRN for any legacy profile that lacks one
        profile.mrn = _generate_mrn(db)
        db.flush()

    db.commit()
    db.refresh(profile)

    if created:
        # New patients start with default consents granted (revocable any time).
        from app.tools.consents import set_consent
        for ctype in ("document_storage", "data_processing", "communications"):
            set_consent(db, profile.id, ctype, True, actor_id=user.id)

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
        "mrn": profile.mrn,
        "user_id": user.id,
        "name": user.name,
        "email": user.email,
        "created": created,
    }