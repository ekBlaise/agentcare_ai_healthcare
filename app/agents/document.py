"""
Document Agent — ingests attached documents, classifies them, stores metadata
with SHA-256 duplicate detection, maps them to the patient, and reports missing
required documents for the routed department. Tool-driven and persisted.
"""
from app.database import SessionLocal
from app.tools import (
    classify_and_store_document, check_missing_documents, write_audit, has_consent,
)


def document_agent(state: dict) -> dict:
    db = SessionLocal()
    try:
        patient_id = state.get("patient_id")
        dept_name = state.get("department_name")
        docs_in = state.get("documents_input", []) or []
        msgs = state.get("messages", [])

        stored = []
        consent_blocked = False
        if docs_in:
            # Consent gate: only store documents if the patient has granted consent.
            if not has_consent(db, patient_id, "document_storage"):
                consent_blocked = True
                msgs.append("Document: storage skipped - patient has not granted "
                            "document-storage consent.")
                write_audit(db, action="document_storage_blocked_no_consent",
                            entity_type="patient_profile", entity_id=patient_id,
                            metadata={"attached": len(docs_in)})
            else:
                for d in docs_in:
                    content = d.get("content", b"")
                    if isinstance(content, str):
                        content = content.encode("utf-8")
                    res = classify_and_store_document(
                        db, patient_id, d.get("filename", "document"), content,
                        declared_type=d.get("declared_type"),
                    )
                    stored.append(res)

        missing = []
        if dept_name:
            miss = check_missing_documents(db, patient_id, dept_name)
            missing = miss["missing"]

        if consent_blocked:
            pass  # message already added
        elif stored:
            dupes = sum(1 for s in stored if s.get("duplicate"))
            msgs.append(f"Document: {len(stored)} processed "
                        f"({dupes} duplicate(s)); missing = {missing or 'none'}")
        else:
            msgs.append(f"Document: no documents attached; missing = {missing or 'none'}")

        write_audit(db, action="documents_coordinated", entity_type="patient_profile",
                    entity_id=patient_id,
                    metadata={"stored": len(stored), "missing": missing,
                              "consent_blocked": consent_blocked})
        return {"stored_documents": stored, "missing_documents": missing,
                "consent_blocked": consent_blocked, "messages": msgs}
    finally:
        db.close()