"""
Smoke tests — verify the database layer and models work end to end.
More agent/tool tests are added on Day 2+.
"""
import os
import tempfile

import pytest


@pytest.fixture(scope="module")
def db_session():
    # Use a temporary throwaway SQLite DB for tests
    tmp = tempfile.mktemp(suffix=".db")
    os.environ["DATABASE_URL"] = f"sqlite:///{tmp}"

    # Import after setting env so config picks it up
    from app.config import get_settings
    get_settings.cache_clear()

    from app.database import init_db, SessionLocal
    init_db()
    db = SessionLocal()
    yield db
    db.close()


def test_create_department_and_doctor(db_session):
    from app.models import Department, Doctor
    dept = Department(name="Cardiology", description="Heart care", active=True)
    db_session.add(dept)
    db_session.flush()

    doc = Doctor(department_id=dept.id, name="Dr. Test", active=True)
    db_session.add(doc)
    db_session.commit()

    assert dept.id is not None
    assert doc.department_id == dept.id
    assert db_session.query(Doctor).filter_by(name="Dr. Test").count() == 1


def test_password_hashing_roundtrip():
    from app.security import hash_password, verify_password
    h = hash_password("secret123")
    assert h != "secret123"                 # never store plaintext
    assert verify_password("secret123", h)  # correct password verifies
    assert not verify_password("wrong", h)  # wrong password fails


def test_audit_event_persists(db_session):
    from app.models import AuditEvent
    ev = AuditEvent(actor_type="agent", action="test_action",
                    entity_type="test", entity_id=1, event_metadata={"k": "v"})
    db_session.add(ev)
    db_session.commit()
    assert db_session.query(AuditEvent).filter_by(action="test_action").count() == 1
