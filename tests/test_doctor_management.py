"""
Admin doctor-management tests: admins can list, add, reassign, and
activate/deactivate doctors (schedulable resources). RBAC: admin only.
"""
import os
os.environ["AGENTCARE_FAKE_LLM"] = "1"

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    from app.database import init_db, SessionLocal
    from app.models import User, Department, Doctor, UserRole
    from app.security import hash_password
    init_db()
    db = SessionLocal()
    for email, role in [("dadmin@example.com", UserRole.ADMIN),
                        ("dstaff@example.com", UserRole.STAFF)]:
        if db.query(User).filter_by(email=email).first() is None:
            db.add(User(name=email.split("@")[0], email=email,
                        password_hash=hash_password("secret1"), role=role))
    if db.query(Department).filter_by(name="DocMgmtDept").first() is None:
        db.add(Department(name="DocMgmtDept", description="x", active=True))
    db.commit(); db.close()
    from app.api.main import app
    return TestClient(app)


def _tok(c, email):
    return c.post("/auth/login", data={"username": email, "password": "secret1"}).json()["access_token"]


def _auth(t):
    return {"Authorization": f"Bearer {t}"}


def _dept_id(c, tok):
    depts = c.get("/staff/departments", headers=_auth(tok)).json()
    return [d for d in depts if d["name"] == "DocMgmtDept"][0]["id"]


def test_admin_add_and_list_doctor(client):
    tok = _tok(client, "dadmin@example.com")
    dept_id = _dept_id(client, tok)
    r = client.post(f"/admin/doctors?name=Dr. Test&department_id={dept_id}", headers=_auth(tok))
    assert r.status_code == 201 and r.json()["name"] == "Dr. Test"
    docs = client.get("/admin/doctors", headers=_auth(tok)).json()
    assert any(d["name"] == "Dr. Test" for d in docs)


def test_admin_update_and_deactivate_doctor(client):
    tok = _tok(client, "dadmin@example.com")
    dept_id = _dept_id(client, tok)
    did = client.post(f"/admin/doctors?name=Dr. Toggle&department_id={dept_id}",
                      headers=_auth(tok)).json()["doctor_id"]
    r = client.patch(f"/admin/doctors/{did}?active=false", headers=_auth(tok))
    assert r.status_code == 200 and r.json()["active"] is False
    r2 = client.patch(f"/admin/doctors/{did}?name=Dr. Renamed", headers=_auth(tok))
    assert r2.json()["name"] == "Dr. Renamed"


def test_add_doctor_bad_department(client):
    tok = _tok(client, "dadmin@example.com")
    r = client.post("/admin/doctors?name=Dr. Nowhere&department_id=99999", headers=_auth(tok))
    assert r.status_code == 400


def test_doctor_management_is_admin_only(client):
    stok = _tok(client, "dstaff@example.com")
    dept_id = _dept_id(client, stok)
    assert client.get("/admin/doctors", headers=_auth(stok)).status_code == 403
    assert client.post(f"/admin/doctors?name=X&department_id={dept_id}",
                       headers=_auth(stok)).status_code == 403