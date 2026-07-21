"""
Seed AgentCare with synthetic (non-real) data:
 - demo patient, staff, and admin users
 - hospital departments and doctors
 - a week of open appointment slots

All data here is fabricated for development/demo only — no real patient
information. Run after init_db.py:  python seed.py
"""
from datetime import datetime, timedelta, timezone

from app.security import hash_password

from app.database import SessionLocal, init_db
from app.models import (
    User, PatientProfile, Department, Doctor, AppointmentSlot,
    UserRole, SlotStatus,
)

DEPARTMENTS = [
    ("Cardiology", "Heart and cardiovascular administration and follow-ups"),
    ("General Medicine", "General adult outpatient administration"),
    ("Orthopedics", "Bone, joint, and musculoskeletal appointments"),
    ("Dermatology", "Skin-related outpatient appointments"),
    ("Pediatrics", "Child and adolescent outpatient administration"),
    ("Radiology", "Imaging appointments and report coordination"),
    ("ENT", "Ear, nose, and throat outpatient appointments"),
    ("Neurology", "Nervous-system outpatient administration and follow-ups"),
]

DOCTORS = {
    "Cardiology": ["Dr. A. Mensah", "Dr. R. Okafor"],
    "General Medicine": ["Dr. S. Bello", "Dr. L. Nkemdirim"],
    "Orthopedics": ["Dr. T. Achterberg"],
    "Dermatology": ["Dr. P. Nguyen"],
    "Pediatrics": ["Dr. M. Owusu"],
    "Radiology": ["Dr. K. Adeyemi"],
    "ENT": ["Dr. J. Fofana"],
    "Neurology": ["Dr. C. Eze"],
}


def seed():
    init_db()
    db = SessionLocal()
    try:
        if db.query(Department).count() > 0:
            print("ℹ️  Data already present — skipping seed. "
                  "Delete data/agentcare.db to reseed from scratch.")
            return

        # ── Users ────────────────────────────────────────────────────
        admin = User(name="Ada Admin", email="admin@agentcare.local",
                     password_hash=hash_password("admin123"), role=UserRole.ADMIN)
        staff = User(name="Sam Staff", email="staff@agentcare.local",
                     password_hash=hash_password("staff123"), role=UserRole.STAFF)
        patient_user = User(name="Pat Patient", email="patient@agentcare.local",
                            password_hash=hash_password("patient123"), role=UserRole.PATIENT)
        db.add_all([admin, staff, patient_user])
        db.flush()

        profile = PatientProfile(
            user_id=patient_user.id, date_of_birth="1985-04-12", age=40,
            phone="+237-600-000-000", preferred_language="English",
            emergency_contact="Kin Patient +237-600-111-111",
        )
        db.add(profile)

        # ── Departments + doctors ────────────────────────────────────
        dept_objs = {}
        for name, desc in DEPARTMENTS:
            d = Department(name=name, description=desc, active=True)
            db.add(d)
            db.flush()
            dept_objs[name] = d

        doctor_objs = []
        for dept_name, names in DOCTORS.items():
            for dn in names:
                doc = Doctor(department_id=dept_objs[dept_name].id, name=dn, active=True)
                db.add(doc)
                doctor_objs.append(doc)
        db.flush()

        # ── Slots: next 7 days, 3 slots/day per doctor ───────────────
        base = datetime.now(timezone.utc).replace(hour=9, minute=0, second=0, microsecond=0)
        slot_count = 0
        for doc in doctor_objs:
            for day in range(1, 8):                # next 7 days
                for hour in (9, 11, 14):           # 3 slots/day
                    start = base + timedelta(days=day, hours=hour - 9)
                    end = start + timedelta(minutes=30)
                    db.add(AppointmentSlot(
                        doctor_id=doc.id, start_time=start, end_time=end,
                        status=SlotStatus.OPEN,
                    ))
                    slot_count += 1

        db.commit()
        print("✅ Seed complete:")
        print(f"   Users:       3 (admin / staff / patient)")
        print(f"   Departments: {len(DEPARTMENTS)}")
        print(f"   Doctors:     {len(doctor_objs)}")
        print(f"   Slots:       {slot_count}")
        print()
        print("   Demo logins (email / password):")
        print("     admin@agentcare.local   / admin123")
        print("     staff@agentcare.local   / staff123")
        print("     patient@agentcare.local / patient123")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
