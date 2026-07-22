"""
AgentState — the typed state object handed node-to-node through the LangGraph
workflow. Each agent reads what it needs and writes its own results. The whole
state is also persisted to WorkflowRun.state so it survives restarts and is
inspectable by staff.
"""
from typing import TypedDict, Optional, List, Dict, Any


class AgentState(TypedDict, total=False):
    # ── Input ────────────────────────────────────────────────────────────
    request: str                        # the patient's natural-language request
    patient_input: Dict[str, Any]       # name, email, phone, ...
    documents_input: List[Dict[str, Any]]  # [{filename, content(bytes)}]
    preferred_slot_id: Optional[int]    # optional explicit slot choice

    # ── Identity ─────────────────────────────────────────────────────────
    patient_id: Optional[int]
    workflow_run_id: Optional[int]

    # ── Safety ───────────────────────────────────────────────────────────
    safety_verdict: str                 # "safe" | "emergency" | "sensitive"
    safety_reason: str

    # ── Routing ──────────────────────────────────────────────────────────
    department_id: Optional[int]
    department_name: Optional[str]
    routing_confidence: str             # "exact" | "partial" | "uncertain"

    # ── Appointment ──────────────────────────────────────────────────────
    appointment_id: Optional[int]
    appointment_status: Optional[str]
    booked_slot: Optional[Dict[str, Any]]

    # ── Documents ────────────────────────────────────────────────────────
    stored_documents: List[Dict[str, Any]]
    missing_documents: List[str]

    # ── Follow-up ────────────────────────────────────────────────────────
    reminder_ids: List[int]

    # ── Escalation / control ─────────────────────────────────────────────
    escalated: bool
    escalation_id: Optional[int]
    status: str                         # "running" | "completed" | "escalated" | "failed"
    error: Optional[str]
    messages: List[str]                 # human-readable trace
    confirmation: Optional[str]
