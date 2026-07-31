"""
SQLAlchemy ORM models for AgentCare.

Implements the full persistent data model required by the challenge:
Users & roles, patient profiles, departments, doctors, slots, appointments,
documents, workflow runs (agent state), reminders, escalations, and an audit log.

All core patient/appointment/document/workflow data lives here in a persistent
SQL database — nothing important is held only in memory.
"""
from datetime import datetime, timezone
import enum

from sqlalchemy import (
    Column, Integer, String, Text, Boolean, DateTime, ForeignKey, Enum, JSON, Float
)
from sqlalchemy.orm import relationship

from app.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ══════════════════════════════════════════════════════════════════════
# ENUMS
# ══════════════════════════════════════════════════════════════════════

class UserRole(str, enum.Enum):
    PATIENT = "patient"
    STAFF = "staff"
    ADMIN = "admin"


class SlotStatus(str, enum.Enum):
    OPEN = "open"
    HELD = "held"
    BOOKED = "booked"


class AppointmentStatus(str, enum.Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    RESCHEDULED = "rescheduled"
    CANCELLED = "cancelled"
    AWAITING_CONFIRMATION = "awaiting_confirmation"  # time passed; outcome not yet recorded
    COMPLETED = "completed"                          # confirmed as attended (by staff)
    MISSED = "missed"                                # confirmed as not attended (by staff)


class WorkflowStatus(str, enum.Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    ESCALATED = "escalated"


class ReminderStatus(str, enum.Enum):
    SCHEDULED = "scheduled"
    SENT = "sent"
    CANCELLED = "cancelled"


class EscalationStatus(str, enum.Enum):
    OPEN = "open"
    APPROVED = "approved"
    REJECTED = "rejected"
    RESOLVED = "resolved"


# ══════════════════════════════════════════════════════════════════════
# IDENTITY & ROLES
# ══════════════════════════════════════════════════════════════════════

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    name = Column(String(120), nullable=False)
    email = Column(String(160), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=True)      # hashed, never plaintext
    external_auth_id = Column(String(160), nullable=True)   # optional SSO id
    role = Column(Enum(UserRole), nullable=False, default=UserRole.PATIENT)
    created_at = Column(DateTime, default=utcnow)

    patient_profile = relationship("PatientProfile", back_populates="user", uselist=False)


class PatientProfile(Base):
    __tablename__ = "patient_profiles"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, unique=True)
    mrn = Column(String(20), nullable=True, unique=True, index=True)  # medical record number (stable identity)
    date_of_birth = Column(String(20), nullable=True)   # ISO date string (synthetic data)
    age = Column(Integer, nullable=True)
    phone = Column(String(40), nullable=True)
    preferred_language = Column(String(40), default="English")
    emergency_contact = Column(String(120), nullable=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    user = relationship("User", back_populates="patient_profile")
    appointments = relationship("Appointment", back_populates="patient")
    documents = relationship("PatientDocument", back_populates="patient")
    workflow_runs = relationship("WorkflowRun", back_populates="patient")
    reminders = relationship("Reminder", back_populates="patient")


# ══════════════════════════════════════════════════════════════════════
# HOSPITAL STRUCTURE
# ══════════════════════════════════════════════════════════════════════

class Department(Base):
    __tablename__ = "departments"

    id = Column(Integer, primary_key=True)
    name = Column(String(120), unique=True, nullable=False, index=True)
    description = Column(Text, nullable=True)
    active = Column(Boolean, default=True)

    doctors = relationship("Doctor", back_populates="department")


class Doctor(Base):
    __tablename__ = "doctors"

    id = Column(Integer, primary_key=True)
    department_id = Column(Integer, ForeignKey("departments.id"), nullable=False)
    name = Column(String(120), nullable=False)
    active = Column(Boolean, default=True)

    department = relationship("Department", back_populates="doctors")
    slots = relationship("AppointmentSlot", back_populates="doctor")


class AppointmentSlot(Base):
    __tablename__ = "appointment_slots"

    id = Column(Integer, primary_key=True)
    doctor_id = Column(Integer, ForeignKey("doctors.id"), nullable=False)
    start_time = Column(DateTime, nullable=False)
    end_time = Column(DateTime, nullable=False)
    status = Column(Enum(SlotStatus), default=SlotStatus.OPEN)

    doctor = relationship("Doctor", back_populates="slots")
    appointment = relationship("Appointment", back_populates="slot", uselist=False)


# ══════════════════════════════════════════════════════════════════════
# APPOINTMENTS
# ══════════════════════════════════════════════════════════════════════

class Appointment(Base):
    __tablename__ = "appointments"

    id = Column(Integer, primary_key=True)
    patient_id = Column(Integer, ForeignKey("patient_profiles.id"), nullable=False)
    doctor_id = Column(Integer, ForeignKey("doctors.id"), nullable=False)
    slot_id = Column(Integer, ForeignKey("appointment_slots.id"), nullable=True)
    status = Column(Enum(AppointmentStatus), default=AppointmentStatus.PENDING)
    reason = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    patient = relationship("PatientProfile", back_populates="appointments")
    doctor = relationship("Doctor")
    slot = relationship("AppointmentSlot", back_populates="appointment")
    reminders = relationship("Reminder", back_populates="appointment")


# ══════════════════════════════════════════════════════════════════════
# DOCUMENTS
# ══════════════════════════════════════════════════════════════════════

class PatientDocument(Base):
    __tablename__ = "patient_documents"

    id = Column(Integer, primary_key=True)
    patient_id = Column(Integer, ForeignKey("patient_profiles.id"), nullable=False)
    appointment_id = Column(Integer, ForeignKey("appointments.id"), nullable=True)  # linked encounter
    document_type = Column(String(80), nullable=True)     # ECG, blood_report, referral...
    file_path = Column(String(400), nullable=True)         # storage reference
    document_date = Column(String(20), nullable=True)
    checksum = Column(String(64), nullable=True, index=True)  # SHA-256 for dedupe
    created_at = Column(DateTime, default=utcnow)

    patient = relationship("PatientProfile", back_populates="documents")


# ══════════════════════════════════════════════════════════════════════
# WORKFLOW STATE (agent state persisted here + LangGraph checkpointer)
# ══════════════════════════════════════════════════════════════════════

class WorkflowRun(Base):
    __tablename__ = "workflow_runs"

    id = Column(Integer, primary_key=True)
    patient_id = Column(Integer, ForeignKey("patient_profiles.id"), nullable=True)
    thread_id = Column(String(80), unique=True, index=True)  # LangGraph checkpoint key
    original_request = Column(Text, nullable=True)
    current_step = Column(String(80), nullable=True)
    state = Column(JSON, nullable=True)          # snapshot of agent state
    status = Column(Enum(WorkflowStatus), default=WorkflowStatus.RUNNING)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    patient = relationship("PatientProfile", back_populates="workflow_runs")
    escalations = relationship("Escalation", back_populates="workflow_run")


# ══════════════════════════════════════════════════════════════════════
# REMINDERS & FOLLOW-UP
# ══════════════════════════════════════════════════════════════════════

class Reminder(Base):
    __tablename__ = "reminders"

    id = Column(Integer, primary_key=True)
    patient_id = Column(Integer, ForeignKey("patient_profiles.id"), nullable=False)
    appointment_id = Column(Integer, ForeignKey("appointments.id"), nullable=True)
    reminder_type = Column(String(60), default="appointment")  # appointment, follow_up, document
    message = Column(Text, nullable=True)
    scheduled_at = Column(DateTime, nullable=True)
    status = Column(Enum(ReminderStatus), default=ReminderStatus.SCHEDULED)
    created_at = Column(DateTime, default=utcnow)

    patient = relationship("PatientProfile", back_populates="reminders")
    appointment = relationship("Appointment", back_populates="reminders")


# ══════════════════════════════════════════════════════════════════════
# ESCALATION (human-in-the-loop)
# ══════════════════════════════════════════════════════════════════════

class Escalation(Base):
    __tablename__ = "escalations"

    id = Column(Integer, primary_key=True)
    workflow_run_id = Column(Integer, ForeignKey("workflow_runs.id"), nullable=True)
    reason = Column(Text, nullable=False)
    category = Column(String(60), default="general")   # emergency, sensitive, uncertain
    status = Column(Enum(EscalationStatus), default=EscalationStatus.OPEN)
    reviewed_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    review_notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utcnow)
    reviewed_at = Column(DateTime, nullable=True)

    workflow_run = relationship("WorkflowRun", back_populates="escalations")
    reviewer = relationship("User")


# ══════════════════════════════════════════════════════════════════════
# AUDIT LOG (every meaningful action)
# ══════════════════════════════════════════════════════════════════════

class AuditEvent(Base):
    __tablename__ = "audit_events"

    id = Column(Integer, primary_key=True)
    actor_id = Column(Integer, ForeignKey("users.id"), nullable=True)   # user or agent
    actor_type = Column(String(40), default="agent")   # agent, patient, staff, system
    action = Column(String(120), nullable=False)
    entity_type = Column(String(80), nullable=True)
    entity_id = Column(Integer, nullable=True)
    event_metadata = Column("metadata", JSON, nullable=True)
    created_at = Column(DateTime, default=utcnow)


# ══════════════════════════════════════════════════════════════════════
# CONSENT MANAGEMENT (patient authorization / oversight)
# ══════════════════════════════════════════════════════════════════════

class ConsentType(str, enum.Enum):
    DOCUMENT_STORAGE = "document_storage"      # store & process my documents
    DATA_PROCESSING = "data_processing"        # process my data for admin tasks
    COMMUNICATIONS = "communications"          # send me reminders / follow-ups


class Consent(Base):
    __tablename__ = "consents"

    id = Column(Integer, primary_key=True)
    patient_id = Column(Integer, ForeignKey("patient_profiles.id"), nullable=False)
    consent_type = Column(Enum(ConsentType), nullable=False)
    granted = Column(Boolean, default=False)   # current state (grant/revoke toggles this)
    granted_at = Column(DateTime, nullable=True)
    revoked_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    patient = relationship("PatientProfile")