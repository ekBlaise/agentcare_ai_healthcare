"""Smoke tests — database layer and models work end to end."""
import pytest


@pytest.fixture
def db():
    from app.database import init_db, SessionLocal
    init_db()
    session = SessionLocal()
    yield session
    session.close()


def test_create_department_and_doctor(db):
    from app.models import Department, Doctor
    dept = Department(name="SmokeCardiology", description="Heart care", active=True)
    db.add(dept); db.flush()
    doc = Doctor(department_id=dept.id, name="Dr. Smoke", active=True)
    db.add(doc); db.commit()
    assert dept.id is not None
    assert db.query(Doctor).filter_by(name="Dr. Smoke").count() == 1


def test_password_hashing_roundtrip():
    from app.security import hash_password, verify_password
    h = hash_password("secret123")
    assert h != "secret123"
    assert verify_password("secret123", h)
    assert not verify_password("wrong", h)


def test_audit_event_persists(db):
    from app.models import AuditEvent
    ev = AuditEvent(actor_type="agent", action="smoke_action",
                    entity_type="test", entity_id=1, event_metadata={"k": "v"})
    db.add(ev); db.commit()
    assert db.query(AuditEvent).filter_by(action="smoke_action").count() == 1
