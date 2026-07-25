"""Pydantic schemas for API request/response validation."""
from typing import Literal, Optional
from pydantic import BaseModel


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    name: str


class DocumentIn(BaseModel):
    filename: str
    content_base64: str
    declared_type: Optional[str] = None


class RequestIn(BaseModel):
    request: str
    documents: list[DocumentIn] = []
    preferred_slot_id: Optional[int] = None


class WorkflowResult(BaseModel):
    workflow_run_id: Optional[int]
    status: str
    confirmation: Optional[str]
    department_name: Optional[str] = None
    appointment_id: Optional[int] = None
    escalated: bool = False
    missing_documents: list[str] = []
    trace: list[str] = []


class ReviewIn(BaseModel):
    decision: Literal["approve", "reject"]
    notes: str = ""


class RegisterIn(BaseModel):
    """Public patient self-registration."""
    name: str
    email: str
    password: str


class CreateUserIn(BaseModel):
    """Admin-created account (staff or patient)."""
    name: str
    email: str
    password: str
    role: Literal["patient", "staff", "admin"] = "staff"


class UserOut(BaseModel):
    id: int
    name: str
    email: str
    role: str
    created_at: Optional[str] = None
