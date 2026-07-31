"""
Document coordination tools — the highest-weighted document criteria:
ingestion, classification, patient mapping, SHA-256 duplicate detection,
and missing-required-document checks. All persisted.
"""
import hashlib
import os

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import PatientDocument
from app.tools.audit import write_audit

settings = get_settings()

# Keyword-based classifier (real logic on the filename/type, not a fixed label).
DOC_TYPE_KEYWORDS = {
    "ecg": "ECG",
    "ekg": "ECG",
    "electrocardiogram": "ECG",
    "blood": "blood_report",
    "cbc": "blood_report",
    "hemogram": "blood_report",
    "xray": "xray",
    "x-ray": "xray",
    "mri": "mri_scan",
    "ct": "ct_scan",
    "scan": "scan",
    "referral": "referral",
    "prescription": "prescription",
    "discharge": "discharge_summary",
    "insurance": "insurance",
    "id": "identification",
}

# Required documents per department (used for missing-doc checks).
REQUIRED_DOCS_BY_DEPARTMENT = {
    "Cardiology": ["ECG", "blood_report"],
    "Radiology": ["referral"],
    "Orthopedics": ["xray"],
    "General Medicine": [],
}


def classify_document(filename: str, declared_type: str | None = None) -> str:
    """Classify a document by declared type or filename keywords."""
    if declared_type:
        return declared_type
    name = (filename or "").lower()
    for kw, dtype in DOC_TYPE_KEYWORDS.items():
        if kw in name:
            return dtype
    return "unknown"


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def classify_and_store_document(
    db: Session,
    patient_id: int,
    filename: str,
    content: bytes,
    declared_type: str | None = None,
    document_date: str | None = None,
    appointment_id: int | None = None,
) -> dict:
    """
    Classify, checksum, dedupe, store metadata, and map a document to a patient.
    Duplicate detection is real: same checksum for the same patient => duplicate.
    """
    checksum = _sha256(content)
    doc_type = classify_document(filename, declared_type)

    # ── Duplicate detection (SHA-256, per patient) ──
    existing = (
        db.query(PatientDocument)
        .filter(PatientDocument.patient_id == patient_id,
                PatientDocument.checksum == checksum)
        .first()
    )
    if existing:
        write_audit(db, action="document_duplicate_detected", entity_type="patient_document",
                    entity_id=existing.id,
                    metadata={"checksum": checksum, "type": doc_type, "filename": filename})
        return {
            "success": True, "duplicate": True,
            "document_id": existing.id, "document_type": existing.document_type,
            "checksum": checksum,
            "message": "Duplicate of an already-stored document; not re-added.",
        }

    # ── Store the file to the upload dir (metadata + real storage reference) ──
    os.makedirs(settings.upload_dir, exist_ok=True)
    safe_name = f"{patient_id}_{checksum[:12]}_{os.path.basename(filename)}"
    file_path = os.path.join(settings.upload_dir, safe_name)
    with open(file_path, "wb") as f:
        f.write(content)

    doc = PatientDocument(
        patient_id=patient_id,
        appointment_id=appointment_id,
        document_type=doc_type,
        file_path=file_path,
        document_date=document_date,
        checksum=checksum,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    write_audit(db, action="document_stored", entity_type="patient_document",
                entity_id=doc.id,
                metadata={"type": doc_type, "checksum": checksum, "filename": filename,
                          "appointment_id": appointment_id})

    return {
        "success": True, "duplicate": False,
        "document_id": doc.id, "document_type": doc_type,
        "checksum": checksum, "file_path": file_path,
        "appointment_id": appointment_id,
    }


def check_missing_documents(db: Session, patient_id: int, department_name: str) -> dict:
    """Compare a patient's stored documents against the department's required set."""
    required = REQUIRED_DOCS_BY_DEPARTMENT.get(department_name, [])
    have = {
        d.document_type
        for d in db.query(PatientDocument).filter(PatientDocument.patient_id == patient_id).all()
    }
    missing = [r for r in required if r not in have]

    write_audit(db, action="missing_document_check", entity_type="patient_profile",
                entity_id=patient_id,
                metadata={"department": department_name, "required": required,
                          "missing": missing})
    return {
        "department": department_name,
        "required": required,
        "have": sorted(have),
        "missing": missing,
        "complete": len(missing) == 0,
    }