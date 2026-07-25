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
    "You are the Safety agent in a hospital ADMINISTRATION system. Your ONLY job "
    "is to classify an incoming request into exactly one label:\n"
    "  EMERGENCY  - describes an acute medical emergency needing immediate care\n"
    "  SENSITIVE  - asks for diagnosis, prescription, dosage, or clinical advice\n"
    "  SAFE       - a purely administrative request (booking, documents, routing)\n"
    "You never provide medical advice yourself. Reply with ONLY the single label."
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

        # If keywords say safe, optionally let the LLM catch subtler cases
        if verdict == "safe" and llm_available():
            try:
                label = chat(SYSTEM_PROMPT, f"Request: {req}").strip().upper()
                if "EMERGENCY" in label:
                    verdict, reason = "emergency", "LLM classified as emergency."
                elif "SENSITIVE" in label:
                    verdict, reason = "sensitive", "LLM classified as clinical-advice request."
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
