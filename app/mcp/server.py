"""
AgentCare MCP Server — exposes the hospital administration tools over the Model
Context Protocol so any MCP client (e.g. Claude Desktop) can drive the system:
look up departments, check availability, book / reschedule / cancel appointments,
coordinate documents, and read the audit trail.

These are the SAME real, DB-backed tools the internal agents use — not stubs.

Run it (stdio transport, for Claude Desktop etc.):
    python -m app.mcp.server

Register in an MCP client (example claude_desktop_config.json):
{
  "mcpServers": {
    "agentcare": {
      "command": "python",
      "args": ["-m", "app.mcp.server"],
      "cwd": "/absolute/path/to/agentcare"
    }
  }
}
"""
import base64
from typing import Optional

from mcp.server.fastmcp import FastMCP

from app.database import SessionLocal, init_db
from app.tools import (
    find_or_create_patient, list_departments as _list_departments, lookup_department,
    get_available_slots, book_appointment, reschedule_appointment, cancel_appointment,
    classify_and_store_document, check_missing_documents,
    create_reminder, create_followup,
)
from app.models import AuditEvent

mcp = FastMCP("agentcare")


def _db():
    return SessionLocal()


# ── Read tools ───────────────────────────────────────────────────────────────
@mcp.tool()
def list_departments() -> list[dict]:
    """List all active hospital departments."""
    db = _db()
    try:
        return _list_departments(db)
    finally:
        db.close()


@mcp.tool()
def find_department(hint: str) -> dict:
    """Resolve a department by name or hint (exact then fuzzy match)."""
    db = _db()
    try:
        return lookup_department(db, hint)
    finally:
        db.close()


@mcp.tool()
def available_slots(department_id: Optional[int] = None,
                    doctor_id: Optional[int] = None, limit: int = 10) -> list[dict]:
    """List open, future appointment slots, optionally filtered by department/doctor."""
    db = _db()
    try:
        return get_available_slots(db, department_id=department_id,
                                   doctor_id=doctor_id, limit=limit)
    finally:
        db.close()


# ── Patient + booking tools ──────────────────────────────────────────────────
@mcp.tool()
def register_patient(name: str, email: str, phone: Optional[str] = None) -> dict:
    """Find an existing patient by email or create a new patient record."""
    db = _db()
    try:
        return find_or_create_patient(db, name=name, email=email, phone=phone)
    finally:
        db.close()


@mcp.tool()
def book(patient_id: int, slot_id: int, reason: Optional[str] = None) -> dict:
    """Book an open slot for a patient (real conflict + past-time checks)."""
    db = _db()
    try:
        return book_appointment(db, patient_id, slot_id, reason=reason)
    finally:
        db.close()


@mcp.tool()
def reschedule(appointment_id: int, new_slot_id: int) -> dict:
    """Reschedule an existing appointment to a new open slot."""
    db = _db()
    try:
        return reschedule_appointment(db, appointment_id, new_slot_id)
    finally:
        db.close()


@mcp.tool()
def cancel(appointment_id: int) -> dict:
    """Cancel an appointment and free its slot."""
    db = _db()
    try:
        return cancel_appointment(db, appointment_id)
    finally:
        db.close()


# ── Document tools ───────────────────────────────────────────────────────────
@mcp.tool()
def store_document(patient_id: int, filename: str, content_base64: str,
                   declared_type: Optional[str] = None) -> dict:
    """Classify and store a patient document (SHA-256 dedupe). Content is base64."""
    db = _db()
    try:
        content = base64.b64decode(content_base64)
        return classify_and_store_document(db, patient_id, filename, content,
                                           declared_type=declared_type)
    finally:
        db.close()


@mcp.tool()
def missing_documents(patient_id: int, department_name: str) -> dict:
    """Report which required documents a patient is missing for a department."""
    db = _db()
    try:
        return check_missing_documents(db, patient_id, department_name)
    finally:
        db.close()


# ── Follow-up tools ──────────────────────────────────────────────────────────
@mcp.tool()
def schedule_reminder(patient_id: int, appointment_id: int) -> dict:
    """Create an appointment reminder for a patient."""
    db = _db()
    try:
        return create_reminder(db, patient_id, appointment_id)
    finally:
        db.close()


@mcp.tool()
def schedule_followup(patient_id: int, appointment_id: int, days_after: int = 14) -> dict:
    """Schedule a post-visit follow-up task."""
    db = _db()
    try:
        return create_followup(db, patient_id, appointment_id, days_after=days_after)
    finally:
        db.close()


# ── Audit (read) ─────────────────────────────────────────────────────────────
@mcp.tool()
def recent_audit(limit: int = 20) -> list[dict]:
    """Read the most recent audit-trail events (transparency for the client)."""
    db = _db()
    try:
        events = (db.query(AuditEvent)
                  .order_by(AuditEvent.created_at.desc()).limit(limit).all())
        return [{
            "id": e.id, "action": e.action, "actor_type": e.actor_type,
            "entity_type": e.entity_type, "entity_id": e.entity_id,
            "created_at": e.created_at.isoformat() if e.created_at else None,
        } for e in events]
    finally:
        db.close()


def main():
    init_db()          # ensure schema exists before serving
    mcp.run()          # stdio transport by default


if __name__ == "__main__":
    main()