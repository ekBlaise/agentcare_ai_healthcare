"""
Root conftest — runs before any test imports app code.
Points AgentCare at an isolated temp SQLite database for the whole test session,
so tests never touch the real dev database.
"""
import os
import tempfile

# Must be set before `app.config` / `app.database` are imported anywhere.
_TEST_DB = tempfile.mktemp(suffix=".db")
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB}"
os.environ["UPLOAD_DIR"] = tempfile.mkdtemp()
