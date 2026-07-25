"""Auth endpoints: login -> JWT, and public patient self-registration."""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.database import get_db
from app.api.auth import authenticate_user, create_access_token
from app.api.schemas import TokenResponse, RegisterIn
from app.models import User, PatientProfile, UserRole
from app.security import hash_password
from app.tools import write_audit

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    # OAuth2 form uses 'username' — we treat it as the email.
    user = authenticate_user(db, form.username, form.password)
    if user is None:
        raise HTTPException(status_code=401, detail="Incorrect email or password")
    token = create_access_token(user.id, user.role.value)
    write_audit(db, action="login", entity_type="user", entity_id=user.id,
                actor_id=user.id, actor_type=user.role.value)
    return TokenResponse(access_token=token, role=user.role.value, name=user.name)


@router.post("/register", response_model=TokenResponse, status_code=201)
def register(body: RegisterIn, db: Session = Depends(get_db)):
    """Public patient sign-up. Creates a patient User + PatientProfile and signs them in."""
    name = (body.name or "").strip()
    email = (body.email or "").strip().lower()
    if not (name and email and body.password):
        raise HTTPException(400, "Name, email, and password are all required.")
    if len(body.password) < 6:
        raise HTTPException(400, "Password must be at least 6 characters.")
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(409, "An account with this email already exists.")

    user = User(name=name, email=email,
                password_hash=hash_password(body.password), role=UserRole.PATIENT)
    db.add(user)
    db.flush()
    db.add(PatientProfile(user_id=user.id, preferred_language="English"))
    db.commit()

    write_audit(db, action="register", entity_type="user", entity_id=user.id,
                actor_id=user.id, actor_type=user.role.value)
    token = create_access_token(user.id, user.role.value)
    return TokenResponse(access_token=token, role=user.role.value, name=user.name)
