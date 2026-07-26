"""
Safety & Escalation Agent — the guardrail. Screens every request for emergency
situations and for diagnosis/prescription-seeking language BEFORE any booking.
Emergencies and unsafe requests produce a persisted Escalation and halt the
autonomous workflow (human-in-the-loop).
"""
from app.config import get_settings
from app.database import SessionLocal
from app.tools import create_escalation, write_audit
from app.agents.llm import llm_available, chat

settings = get_settings()

SYSTEM_PROMPT = (
    "You are the Safety triage classifier in a hospital ADMINISTRATION system.\n"
    "The system's job is to BOOK APPOINTMENTS, ROUTE to departments, and HANDLE\n"
    "DOCUMENTS. Naming a specialty, symptom, condition, or medical document is a\n"
    "NORMAL part of an administrative request and is SAFE by itself.\n\n"
    "Classify the request into exactly ONE label:\n\n"
    "SAFE - administrative: booking, rescheduling, cancelling, routing to a\n"
    "  department, attaching or asking about documents/records, reminders. Mentioning\n"
    "  a condition or specialty to get to the right place is SAFE.\n"
    "  Examples (ALL SAFE):\n"
    "    - 'I need a cardiology follow-up next week and want to attach my old ECG.'\n"
    "    - 'Book me a dermatology appointment for a skin check.'\n"
    "    - 'Reschedule my orthopedics visit; here is my referral.'\n"
    "    - 'I have diabetes and need my regular endocrinology follow-up.'\n\n"
    "SENSITIVE - the patient asks YOU to practice medicine: to diagnose them, to\n"
    "  tell them what medication/dose to take, to interpret results clinically, or\n"
    "  to advise treatment.\n"
    "  Examples (SENSITIVE):\n"
    "    - 'What medication should I take for my headache?'\n"
    "    - 'Do I have cancer? What do my ECG results mean?'\n"
    "    - 'What dose of insulin is right for me?'\n\n"
    "EMERGENCY - an acute emergency needing immediate care (chest pain now,\n"
    "  can't breathe, stroke signs, severe bleeding, suicidal intent, overdose).\n\n"
    "When unsure between SAFE and SENSITIVE, choose SAFE unless the patient is\n"
    "clearly asking you to make a clinical judgement. Reply with ONLY one word:\n"
    "SAFE, SENSITIVE, or EMERGENCY."
)

# Diagnosis / prescription-seeking phrases (deterministic backstop).
# This runs even when no LLM is configured, so it must catch the common ways a
# patient asks for medication, treatment, or a diagnosis — not just polite ones.
SENSITIVE_PATTERNS = [
    # asking what/whether to take something
    "what medicine", "what medication", "should i take", "prescribe",
    "prescription for", "what dose", "dosage", "diagnose", "diagnosis",
    "what's wrong with me", "is it cancer", "do i have", "treat my",
    # asking to be given drugs / medication / treatment / a cure
    "drugs for", "drug for", "medication for", "medicine for", "meds for",
    "pills for", "treatment for", "cure for", "chemo", "chemotherapy",
    "drugs to", "drug to", "medication to", "medicine to", "meds to", "pills to",
    "want drugs", "want medication", "want medicine", "want meds",
    "need drugs", "need medication", "need medicine", "need meds",
    "give me drugs", "give me medication", "give me medicine",
    # reproductive / clearly clinical procedures
    "abortion", "terminate pregnancy", "terminate my pregnancy",
    "remove pregnancy", "end my pregnancy", "end this pregnancy",
]


def _heuristic_verdict(request: str) -> tuple[str, str]:
    text = (request or "").lower()
    for kw in settings.emergency_keyword_list:
        if kw in text:
            return "emergency", f"Emergency keyword detected: '{kw}'"
    for pat in SENSITIVE_PATTERNS:
        if pat in text:
            return "sensitive", f"Diagnosis/prescription-seeking phrase: '{pat}'"
    return "safe", "No emergency or clinical-advice indicators found."


def safety_agent(state: dict) -> dict:
    db = SessionLocal()
    try:
        req = state.get("request", "")

        # Deterministic emergency keyword check ALWAYS runs (never skipped)
        verdict, reason = _heuristic_verdict(req)

        # If keywords say safe, let the LLM catch subtler cases. We parse the
        # FIRST word only (the prompt asks for a single-word answer) so that an
        # explanatory mention of "emergency"/"sensitive" doesn't trip a false
        # escalation on an otherwise administrative request.
        if verdict == "safe" and llm_available():
            try:
                raw = chat(SYSTEM_PROMPT, f"Request: {req}", temperature=0.0)
                token = raw.strip().upper().split()[0].strip(".:,!") if raw.strip() else ""
                if token == "EMERGENCY":
                    verdict, reason = "emergency", "LLM classified as emergency."
                elif token == "SENSITIVE":
                    verdict, reason = "sensitive", "LLM classified as clinical-advice request."
                # any other output (incl. SAFE) leaves the safe verdict intact
            except Exception:
                pass  # fall back to heuristic verdict

        msgs = state.get("messages", [])
        msgs.append(f"Safety: verdict = {verdict} ({reason})")

        update = {"safety_verdict": verdict, "safety_reason": reason, "messages": msgs}

        if verdict in ("emergency", "sensitive"):
            esc = create_escalation(
                db,
                reason=f"[{verdict}] {reason} | request: {req[:200]}",
                category=verdict,
                workflow_run_id=state.get("workflow_run_id"),
            )
            update.update({
                "escalated": True,
                "escalation_id": esc["escalation_id"],
                "status": "escalated",
            })
            write_audit(db, action="safety_escalation", entity_type="escalation",
                        entity_id=esc["escalation_id"], metadata={"verdict": verdict})
        return update
    finally:
        db.close()