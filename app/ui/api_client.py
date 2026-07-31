"""
API client for the Streamlit UI. Every function calls the real FastAPI backend
over HTTP — the UI holds no business logic and displays no hardcoded data.

Functions accept an optional `client` (an httpx.Client or FastAPI TestClient) so
they can be unit-tested against the live app without a running server.
"""
import os
import base64

import httpx

API_BASE = os.environ.get("AGENTCARE_API_BASE", "http://127.0.0.1:8000")


def _client(client=None):
    return client or httpx.Client(base_url=API_BASE, timeout=60.0)


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def login(email: str, password: str, client=None):
    c = _client(client)
    r = c.post("/auth/login", data={"username": email, "password": password})
    if r.status_code == 200:
        return True, r.json()
    return False, {"detail": r.json().get("detail", "Login failed")}


def register(name: str, email: str, password: str, client=None):
    c = _client(client)
    r = c.post("/auth/register", json={"name": name, "email": email, "password": password})
    if r.status_code in (200, 201):
        return True, r.json()
    return False, {"detail": r.json().get("detail", "Registration failed")}


def submit_request(token: str, request: str, documents: list | None = None,
                   preferred_slot_id: int | None = None, client=None):
    c = _client(client)
    docs = []
    for d in documents or []:
        content = d["content"]
        if isinstance(content, str):
            content = content.encode("utf-8")
        docs.append({"filename": d["filename"],
                     "content_base64": base64.b64encode(content).decode(),
                     "declared_type": d.get("declared_type")})
    body = {"request": request, "documents": docs, "preferred_slot_id": preferred_slot_id}
    r = c.post("/requests", headers=_auth(token), json=body)
    return r.status_code == 200, r.json()


def my_appointments(token, client=None):
    r = _client(client).get("/me/appointments", headers=_auth(token))
    return r.status_code == 200, r.json()


def my_documents(token, client=None):
    r = _client(client).get("/me/documents", headers=_auth(token))
    return r.status_code == 200, r.json()


def my_reminders(token, client=None):
    r = _client(client).get("/me/reminders", headers=_auth(token))
    return r.status_code == 200, r.json()


def my_escalations(token, client=None):
    r = _client(client).get("/me/escalations", headers=_auth(token))
    return r.status_code == 200, r.json()


def list_escalations(token, status="open", client=None):
    r = _client(client).get(f"/staff/escalations?status={status}", headers=_auth(token))
    return r.status_code == 200, r.json()


def review_escalation(token, escalation_id: int, decision: str, notes: str = "", client=None):
    r = _client(client).post(f"/staff/escalations/{escalation_id}/review",
                             headers=_auth(token), json={"decision": decision, "notes": notes})
    return r.status_code == 200, r.json()


def list_workflows(token, client=None):
    r = _client(client).get("/staff/workflows", headers=_auth(token))
    return r.status_code == 200, r.json()


def audit_trail(token, limit=50, client=None):
    r = _client(client).get(f"/staff/audit?limit={limit}", headers=_auth(token))
    return r.status_code == 200, r.json()


def list_departments(token, client=None):
    r = _client(client).get("/staff/departments", headers=_auth(token))
    return r.status_code == 200, r.json()


def list_users(token, role="all", client=None):
    r = _client(client).get(f"/admin/users?role={role}", headers=_auth(token))
    return r.status_code == 200, r.json()


def create_user(token, name, email, password, role="staff", client=None):
    r = _client(client).post("/admin/users", headers=_auth(token),
                             json={"name": name, "email": email,
                                   "password": password, "role": role})
    if r.status_code in (200, 201):
        return True, r.json()
    return False, {"detail": r.json().get("detail", "Could not create user")}


def available_slots(token, appointment_id: int, client=None):
    r = _client(client).get(f"/me/available-slots?appointment_id={appointment_id}",
                            headers=_auth(token))
    return r.status_code == 200, r.json()


def reschedule_appointment(token, appointment_id: int, new_slot_id: int, client=None):
    r = _client(client).post(
        f"/me/appointments/{appointment_id}/reschedule?new_slot_id={new_slot_id}",
        headers=_auth(token))
    return r.status_code == 200, r.json()


def cancel_appointment(token, appointment_id: int, client=None):
    r = _client(client).post(f"/me/appointments/{appointment_id}/cancel",
                             headers=_auth(token))
    return r.status_code == 200, r.json()


def list_appointments(token, status="awaiting_confirmation", client=None):
    r = _client(client).get(f"/staff/appointments?status={status}", headers=_auth(token))
    return r.status_code == 200, r.json()


def record_outcome(token, appointment_id: int, attended: bool, client=None):
    r = _client(client).post(
        f"/staff/appointments/{appointment_id}/outcome?attended={str(attended).lower()}",
        headers=_auth(token))
    return r.status_code == 200, r.json()


def analytics(token, client=None):
    r = _client(client).get("/staff/analytics", headers=_auth(token))
    return r.status_code == 200, r.json()


def my_consents(token, client=None):
    r = _client(client).get("/me/consents", headers=_auth(token))
    return r.status_code == 200, r.json()


def set_consent(token, consent_type: str, granted: bool, client=None):
    r = _client(client).post(
        f"/me/consents?consent_type={consent_type}&granted={str(granted).lower()}",
        headers=_auth(token))
    return r.status_code == 200, r.json()


def admin_list_doctors(token, department_id=None, client=None):
    url = "/admin/doctors" + (f"?department_id={department_id}" if department_id else "")
    r = _client(client).get(url, headers=_auth(token))
    return r.status_code == 200, r.json()


def admin_add_doctor(token, name, department_id, client=None):
    r = _client(client).post(
        f"/admin/doctors?name={name}&department_id={department_id}", headers=_auth(token))
    if r.status_code in (200, 201):
        return True, r.json()
    return False, {"detail": r.json().get("detail", "Could not add doctor")}


def admin_update_doctor(token, doctor_id, name=None, department_id=None,
                        active=None, client=None):
    params = []
    if name is not None:
        params.append(f"name={name}")
    if department_id is not None:
        params.append(f"department_id={department_id}")
    if active is not None:
        params.append(f"active={str(active).lower()}")
    qs = ("?" + "&".join(params)) if params else ""
    r = _client(client).patch(f"/admin/doctors/{doctor_id}{qs}", headers=_auth(token))
    return r.status_code == 200, r.json()


def admin_list_departments(token, client=None):
    r = _client(client).get("/admin/departments", headers=_auth(token))
    return r.status_code == 200, r.json()


def admin_add_department(token, name, description="", client=None):
    r = _client(client).post(
        f"/admin/departments?name={name}&description={description}", headers=_auth(token))
    if r.status_code in (200, 201):
        return True, r.json()
    return False, {"detail": r.json().get("detail", "Could not add department")}


def admin_update_department(token, department_id, name=None, description=None,
                            active=None, client=None):
    params = []
    if name is not None:
        params.append(f"name={name}")
    if description is not None:
        params.append(f"description={description}")
    if active is not None:
        params.append(f"active={str(active).lower()}")
    qs = ("?" + "&".join(params)) if params else ""
    r = _client(client).patch(f"/admin/departments/{department_id}{qs}", headers=_auth(token))
    return r.status_code == 200, r.json()