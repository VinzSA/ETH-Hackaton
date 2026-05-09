"""
MT Samples dataset loader.
Expects data/mtsamples.csv — download from:
https://www.kaggle.com/datasets/tboyle10/medicaltranscriptions
"""
import csv
from pathlib import Path
from typing import Optional

DATA_PATH = Path(__file__).parents[2] / "data" / "mtsamples.csv"

SPECIALTY_MAP = {
    "surgery": "operative_note",
    "discharge summary": "discharge_summary",
    "cardiology": "cardiology_consult",
    "radiology": "lab_report",
    "laboratory": "lab_report",
    "pathology": "lab_report",
    "anesthesia": "anesthesia_record",
    "pain management": "anesthesia_record",
    "general medicine": "discharge_summary",
    "internal medicine": "discharge_summary",
    "orthopedic": "operative_note",
    "neurosurgery": "operative_note",
    "urology": "operative_note",
    "obstetrics / gynecology": "operative_note",
    "gastroenterology": "discharge_summary",
    "neurology": "discharge_summary",
    "hematology - oncology": "discharge_summary",
    "nephrology": "discharge_summary",
    "pulmonology": "discharge_summary",
    "psychiatry / psychology": "discharge_summary",
    "endocrinology": "discharge_summary",
    "allergy / immunology": "discharge_summary",
}


def load_samples(
    specialty: Optional[str] = None,
    document_type: Optional[str] = None,
    limit: Optional[int] = None,
) -> list[dict]:
    """
    Load MT Samples rows, optionally filtered by specialty or mapped document_type.
    Returns list of dicts with keys: id, specialty, document_type, title, transcription.
    """
    if not DATA_PATH.exists():
        raise FileNotFoundError(
            f"MT Samples CSV not found at {DATA_PATH}.\n"
            "Download from https://www.kaggle.com/datasets/tboyle10/medicaltranscriptions"
        )

    rows = []
    with open(DATA_PATH, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            spec = row.get("medical_specialty", "").strip().lower()
            transcription = row.get("transcription", "").strip()
            if not transcription:
                continue

            doc_type = SPECIALTY_MAP.get(spec, "unknown")

            if specialty and spec != specialty.lower():
                continue
            if document_type and doc_type != document_type:
                continue

            rows.append(
                {
                    "id": f"mt_{i}",
                    "specialty": spec,
                    "document_type": doc_type,
                    "title": row.get("sample_name", "").strip(),
                    "transcription": transcription,
                    "keywords": row.get("keywords", "").strip(),
                }
            )

            if limit and len(rows) >= limit:
                break

    return rows


def get_examples_by_type(n_per_type: int = 1) -> dict[str, list[str]]:
    """Return n example transcription excerpts per document type — used for classifier prompts."""
    type_to_examples: dict[str, list[str]] = {}
    seen: set[str] = set()

    if not DATA_PATH.exists():
        return {}

    with open(DATA_PATH, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            spec = row.get("medical_specialty", "").strip().lower()
            text = row.get("transcription", "").strip()
            if not text or spec in seen:
                continue

            doc_type = SPECIALTY_MAP.get(spec, "unknown")
            if doc_type == "unknown":
                continue

            bucket = type_to_examples.setdefault(doc_type, [])
            if len(bucket) < n_per_type:
                bucket.append(text[:400])

            seen.add(spec)

    return type_to_examples
