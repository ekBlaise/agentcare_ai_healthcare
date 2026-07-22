"""Auth endpoints: login -> JWT."""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.database import get_db
from app.api.auth import authenticate_user, create_access_token
from app.api.schemas import TokenResponse
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
