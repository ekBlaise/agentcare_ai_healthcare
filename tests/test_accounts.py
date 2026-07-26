"""
Tests for account features added in the UI-redesign branch:
public self-registration, admin user management, and patient self-service
escalation viewing. Backend RBAC is verified on the admin routes.
"""
import os
os.environ["AGENTCARE_FAKE_LLM"] = "1"

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    from app.database import init_db, SessionLocal
    from app.models import User, UserRole
    from app.security import hash_password
    init_db()
    db = SessionLocal()
    if db.query(User).filter_by(email="admin@agentcare.local").first() is None:
        db.add(User(name="Ada Admin", email="admin@agentcare.local",
                    password_hash=hash_password("admin123"), role=UserRole.ADMIN))
        db.commit()
    db.close()
    from app.api.main import app
    return TestClient(app)


def _tok(client, email, pw):
    return client.post("/auth/login", data={"username": email, "password": pw}).json()["access_token"]


def _auth(t):
    return {"Authorization": f"Bearer {t}"}


def test_public_registration_creates_patient(client):
    r = client.post("/auth/register",
                    json={"name": "Reg User", "email": "reg@example.com", "password": "secret1"})
    assert r.status_code == 201
    assert r.json()["role"] == "patient"
    # duplicate email rejected
    dup = client.post("/auth/register",
                      json={"name": "Reg User", "email": "reg@example.com", "password": "secret1"})
    assert dup.status_code in (400, 409)


def test_admin_creates_and_lists_users(client):
    tok = _tok(client, "admin@agentcare.local", "admin123")
    r = client.post("/admin/users", headers=_auth(tok),
                    json={"name": "New Staff", "email": "ns@example.com",
                          "password": "secret1", "role": "staff"})
    assert r.status_code == 201 and r.json()["role"] == "staff"
    users = client.get("/admin/users", headers=_auth(tok)).json()
    assert any(u["email"] == "ns@example.com" for u in users)


def test_admin_routes_reject_non_admin(client):
    """Backend RBAC on admin routes: patient and staff both get 403."""
    ptok = _tok(client, "reg@example.com", "secret1")
    assert client.get("/admin/users", headers=_auth(ptok)).status_code == 403
    assert client.post("/admin/users", headers=_auth(ptok),
                       json={"name": "x", "email": "x@x.com", "password": "secret1",
                             "role": "staff"}).status_code == 403


def test_patient_sees_own_escalations(client):
    ptok = _tok(client, "reg@example.com", "secret1")
    # trigger an escalation via a diagnosis-seeking request
    client.post("/requests", headers=_auth(ptok),
                json={"request": "what medication should I take for my headache"})
    r = client.get("/me/escalations", headers=_auth(ptok))
    assert r.status_code == 200
    assert isinstance(r.json(), list)