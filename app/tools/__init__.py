"""AgentCare tools — real DB-backed functions invoked by the agents."""
from app.tools.audit import write_audit
from app.tools.patients import find_or_create_patient
from app.tools.departments import lookup_department, list_departments
from app.tools.appointments import (
    get_available_slots, book_appointment,
    reschedule_appointment, cancel_appointment, expire_past_appointments,
    find_active_department_appointment,
    record_appointment_outcome,
)
from app.tools.documents import (
    classify_document, classify_and_store_document, check_missing_documents,
)
from app.tools.reminders import create_reminder, create_followup
from app.tools.escalations import create_escalation

__all__ = [
    "write_audit",
    "find_or_create_patient",
    "lookup_department", "list_departments",
    "get_available_slots", "book_appointment", "expire_past_appointments",
    "reschedule_appointment", "cancel_appointment", "record_appointment_outcome",
    "find_active_department_appointment",
    "classify_document", "classify_and_store_document", "check_missing_documents",
    "create_reminder", "create_followup",
    "create_escalation",
]