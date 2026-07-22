"""
Department Routing Agent — classifies the administrative request and maps it to
a real department using the lookup_department tool. Uncertain routes escalate.
"""
from app.database import SessionLocal
from app.tools import lookup_department, list_departments, create_escalation, write_audit
from app.agents.llm import llm_available, chat

SYSTEM_PROMPT = (
    "You are the Department Routing agent in a hospital ADMINISTRATION system. "
    "Given a patient's administrative request and the list of valid departments, "
    "pick the single most appropriate department. You must choose only from the "
    "provided list. Do not diagnose. Reply with ONLY the department name exactly "
    "as it appears in the list."
)

# Keyword hints for the offline fallback (maps common terms -> department name)
DEPT_HINTS = {
    "heart": "Cardiology", "cardio": "Cardiology", "ecg": "Cardiology", "chest": "Cardiology",
    "bone": "Orthopedics", "joint": "Orthopedics", "fracture": "Orthopedics", "knee": "Orthopedics",
    "skin": "Dermatology", "rash": "Dermatology", "derma": "Dermatology",
    "child": "Pediatrics", "kid": "Pediatrics", "pediatric": "Pediatrics",
    "scan": "Radiology", "xray": "Radiology", "x-ray": "Radiology", "mri": "Radiology", "imaging": "Radiology",
    "ear": "ENT", "nose": "ENT", "throat": "ENT",
    "brain": "Neurology", "nerve": "Neurology", "neuro": "Neurology", "headache": "Neurology",
}


def _heuristic_department(request: str, departments: list[dict]) -> str:
    text = (request or "").lower()
    names = {d["name"] for d in departments}
    # direct name mention
    for d in departments:
        if d["name"].lower() in text:
            return d["name"]
    # keyword hints
    for kw, dept in DEPT_HINTS.items():
        if kw in text and dept in names:
            return dept
    return "General Medicine" if "General Medicine" in names else departments[0]["name"]


def routing_agent(state: dict) -> dict:
    db = SessionLocal()
    try:
        req = state.get("request", "")
        departments = list_departments(db)

        # Decide a department name (LLM or heuristic)
        if llm_available():
            try:
                dept_list = ", ".join(d["name"] for d in departments)
                guess = chat(SYSTEM_PROMPT, f"Departments: {dept_list}\nRequest: {req}")
            except Exception:
                guess = _heuristic_department(req, departments)
        else:
            guess = _heuristic_department(req, departments)

        # Map to a real department row (real tool with fuzzy matching)
        result = lookup_department(db, guess)
        msgs = state.get("messages", [])

        if result["matched"]:
            msgs.append(f"Routing: -> {result['name']} ({result['confidence']})")
            write_audit(db, action="request_routed", entity_type="department",
                        entity_id=result["department_id"],
                        metadata={"guess": guess, "confidence": result["confidence"]})
            return {
                "department_id": result["department_id"],
                "department_name": result["name"],
                "routing_confidence": result["confidence"],
                "messages": msgs,
            }

        # Uncertain -> escalate for human routing
        esc = create_escalation(
            db, reason=f"Uncertain department routing for request: {req[:200]}",
            category="uncertain", workflow_run_id=state.get("workflow_run_id"),
        )
        msgs.append("Routing: uncertain -> escalated for human review")
        return {
            "routing_confidence": "uncertain",
            "escalated": True,
            "escalation_id": esc["escalation_id"],
            "status": "escalated",
            "messages": msgs,
        }
    finally:
        db.close()
