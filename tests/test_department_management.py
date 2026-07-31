"""
Admin department-management tests: add, edit, activate/deactivate, unique-name
validation, and admin-only RBAC.
"""
import os
os.environ["AGENTCARE_FAKE_LLM"] = "1"

import uuid
import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    from app.database import init_db, SessionLocal
    from app.models import User, UserRole
    from app.security import hash_password
    init_db()
    db = SessionLocal()
    for email, role in [("depadmin@example.com", UserRole.ADMIN),
                        ("depstaff@example.com", UserRole.STAFF)]:
        if db.query(User).filter_by(email=email).first() is None:
            db.add(User(name=email.split("@")[0], email=email,
                        password_hash=hash_password("secret1"), role=role))
    db.commit(); db.close()
    from app.api.main import app
    return TestClient(app)


def _tok(c, email):
    return c.post("/auth/login", data={"username": email, "password": "secret1"}).json()["access_token"]


def _auth(t):
    return {"Authorization": f"Bearer {t}"}


def test_admin_add_edit_department(client):
    tok = _tok(client, "depadmin@example.com")
    name = f"Dept-{uuid.uuid4().hex[:6]}"
    r = client.post(f"/admin/departments?name={name}&description=Test", headers=_auth(tok))
    assert r.status_code == 201
    did = r.json()["department_id"]
    # edit description + deactivate
    r2 = client.patch(f"/admin/departments/{did}?description=Updated&active=false",
                      headers=_auth(tok))
    assert r2.status_code == 200 and r2.json()["active"] is False
    assert r2.json()["description"] == "Updated"


def test_duplicate_department_rejected(client):
    tok = _tok(client, "depadmin@example.com")
    name = f"Dupe-{uuid.uuid4().hex[:6]}"
    assert client.post(f"/admin/departments?name={name}", headers=_auth(tok)).status_code == 201
    assert client.post(f"/admin/departments?name={name}", headers=_auth(tok)).status_code == 400


def test_department_doctor_count(client):
    tok = _tok(client, "depadmin@example.com")
    name = f"Counted-{uuid.uuid4().hex[:6]}"
    did = client.post(f"/admin/departments?name={name}", headers=_auth(tok)).json()["department_id"]
    client.post(f"/admin/doctors?name=Dr. Count&department_id={did}", headers=_auth(tok))
    depts = client.get("/admin/departments", headers=_auth(tok)).json()
    row = [d for d in depts if d["name"] == name][0]
    assert row["doctor_count"] == 1


def test_department_management_admin_only(client):
    stok = _tok(client, "depstaff@example.com")
    assert client.get("/admin/departments", headers=_auth(stok)).status_code == 403
    assert client.post("/admin/departments?name=X", headers=_auth(stok)).status_code == 403