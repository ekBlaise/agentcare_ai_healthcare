"""
Consent management tests: patients control their consents; consent gates document
storage in the agent workflow; RBAC keeps consents patient-scoped.
"""
import os
os.environ["AGENTCARE_FAKE_LLM"] = "1"

import base64
import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    from app.database import init_db, SessionLocal
    from app.models import (User, PatientProfile, Department, Doctor,
                            AppointmentSlot, SlotStatus, UserRole)
    from app.security import hash_password
    from datetime import datetime, timedelta, timezone
    init_db()
    db = SessionLocal()
    if db.query(User).filter_by(email="cpat@example.com").first() is None:
        # create via registration path so default consents are granted
        pass
    dept = db.query(Department).filter_by(name="ConsentCardio").first()
    if dept is None:
        dept = Department(name="ConsentCardio", description="H", active=True)
        db.add(dept); db.flush()
        doc = Doctor(department_id=dept.id, name="Dr C", active=True)
        db.add(doc); db.flush()
        base = datetime.now(timezone.utc).replace(microsecond=0) + timedelta(days=4)
        for i in range(6):
            st = base + timedelta(hours=3 * i)
            db.add(AppointmentSlot(doctor_id=doc.id, start_time=st,
                                   end_time=st + timedelta(minutes=30), status=SlotStatus.OPEN))
        db.commit()
    db.close()
    from app.api.main import app
    c = TestClient(app)
    # register a patient (gets default consents)
    c.post("/auth/register", json={"name": "C Pat", "email": "cpat@example.com",
                                   "password": "secret1"})
    return c


def _tok(c):
    return c.post("/auth/login", data={"username": "cpat@example.com",
                                       "password": "secret1"}).json()["access_token"]


def _auth(t):
    return {"Authorization": f"Bearer {t}"}


def test_new_patient_has_default_consents(client):
    tok = _tok(client)
    consents = client.get("/me/consents", headers=_auth(tok)).json()
    by_type = {c["consent_type"]: c["granted"] for c in consents}
    assert by_type.get("document_storage") is True
    assert by_type.get("communications") is True


def test_patient_can_revoke_and_grant(client):
    tok = _tok(client)
    r = client.post("/me/consents?consent_type=document_storage&granted=false",
                    headers=_auth(tok))
    assert r.status_code == 200 and r.json()["granted"] is False
    consents = {c["consent_type"]: c["granted"]
                for c in client.get("/me/consents", headers=_auth(tok)).json()}
    assert consents["document_storage"] is False
    # grant back
    client.post("/me/consents?consent_type=document_storage&granted=true", headers=_auth(tok))
    consents = {c["consent_type"]: c["granted"]
                for c in client.get("/me/consents", headers=_auth(tok)).json()}
    assert consents["document_storage"] is True


def test_revoked_consent_blocks_document_storage(client):
    tok = _tok(client)
    # revoke document storage
    client.post("/me/consents?consent_type=document_storage&granted=false", headers=_auth(tok))
    # submit a request WITH a document -> should be blocked, not stored
    body = {"request": "consentcardio follow-up",
            "documents": [{"filename": "ecg.pdf",
                           "content_base64": base64.b64encode(b"ECG-CONSENT").decode()}]}
    client.post("/requests", headers=_auth(tok), json=body)
    docs = client.get("/me/documents", headers=_auth(tok)).json()
    assert len(docs) == 0     # nothing stored while consent revoked

    # grant, resubmit -> now stored
    client.post("/me/consents?consent_type=document_storage&granted=true", headers=_auth(tok))
    client.post("/requests", headers=_auth(tok), json=body)
    docs2 = client.get("/me/documents", headers=_auth(tok)).json()
    assert len(docs2) >= 1


def test_consents_require_auth(client):
    assert client.get("/me/consents").status_code == 401