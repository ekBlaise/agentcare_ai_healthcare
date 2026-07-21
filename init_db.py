"""
Initialize the AgentCare database — creates all tables.
Run once before seeding:  python init_db.py
"""
from app.database import init_db

if __name__ == "__main__":
    print("Creating AgentCare database tables...")
    init_db()
    print("✅ Database initialized. All tables created.")
