"""
Main extraction pipeline.

Flow:
  PDF(s) / raw text
    → language detection + translation (if non-English)
    → parallel ingestion (pdf_reader)
    → document date extraction
    → document classifier (Claude Haiku)
    → specialized extractor (per document type)
    → normalizers (RxNorm, ICD-10)
    → ExtractedDocument (Pydantic, fully populated)
    → merger: list[ExtractedDocument] → PatientRecord
    → JSON output → backend picks up
"""
import asyncio
import uuid
from pathlib import Path

from src.classifier.classifier import classify
from src.extractors.anesthesia_extractor import extract_anesthesia
from src.extractors.cardiology_extractor import extract_cardiac, extract_cardiac_medications
from src.extractors.discharge_extractor import (
    extract_allergies,
    extract_diagnoses,
    extract_medications,
)
from src.extractors.lab_extractor import extract_labs
from src.extractors.operative_extractor import extract_implants, extract_procedures
from src.ingestion.pdf_reader import PageText, extract_pages, full_text
from src.normalizers.diagnosis_normalizer import lookup_icd10
from src.normalizers.medication_normalizer import lookup_drug
from src.schema.preop_brief import ExtractedDocument
from src.utils.date_extractor import extract_document_date
from src.utils.language import detect_and_translate


def process_text(
    text: str,
    document_id: str | None = None,
    document_type: str | None = None,
) -> ExtractedDocument:
    """
    Process already-extracted text (e.g. from MT Samples or pre-processed PDF).
    If document_type is not provided, the classifier will determine it.
    """
    doc_id = document_id or str(uuid.uuid4())

    # 1. Language detection + translation
    translated_text, lang = detect_and_translate(text)

    # 2. Extract document date from header
    doc_date = extract_document_date(translated_text)

    # 3. Classify
    if document_type is None:
        document_type = classify(translated_text)

    # 4. Route to specialized extractors
    medications, diagnoses, allergies, procedures, implants, labs, anesthesia_history, cardiac = \
        _extract_by_type(translated_text, doc_id, document_type)

    # 5. Normalize medications (RxNorm + ATC)
    for med in medications:
        codes = lookup_drug(med.name)
        med.rxnorm_code = codes.get("rxnorm")
        med.atc_code = codes.get("atc")

    # 6. Normalize diagnoses (ICD-10)
    for diag in diagnoses:
        if not diag.icd10_code:
            diag.icd10_code = lookup_icd10(diag.description)

    # 7. Compute confidence and warnings
    confidence, warnings = _assess_quality(translated_text, medications, diagnoses, labs, document_type)

    return ExtractedDocument(
        document_id=doc_id,
        document_type=document_type,  # type: ignore[arg-type]
        document_date=doc_date,
        language_detected=lang,
        medications=medications,
        diagnoses=diagnoses,
        allergies=allergies,
        procedures=procedures,
        implants=implants,
        labs=labs,
        anesthesia_history=anesthesia_history,
        cardiac=cardiac,
        extraction_confidence=confidence,
        extraction_warnings=warnings,
    )


def process_pdf(
    source: str | Path | bytes,
    document_id: str | None = None,
    document_type: str | None = None,
) -> ExtractedDocument:
    """Process a single PDF file (path or bytes)."""
    pages: list[PageText] = extract_pages(source)
    text = full_text(pages)
    doc_id = document_id or str(uuid.uuid4())
    return process_text(text, doc_id, document_type)


def process_pdfs(
    sources: list[str | Path | bytes],
) -> list[ExtractedDocument]:
    """
    Process multiple PDFs in parallel.
    Returns one ExtractedDocument per PDF, in the same order as sources.
    """
    async def _run():
        loop = asyncio.get_event_loop()
        tasks = [loop.run_in_executor(None, process_pdf, src) for src in sources]
        return await asyncio.gather(*tasks)

    return asyncio.run(_run())


def process_patient(
    sources: list[str | Path | bytes | str],
    patient_id: str | None = None,
    texts: list[str] | None = None,
):
    """
    Full patient pipeline: multiple PDFs (or raw texts) → merged PatientRecord.
    This is the primary entry point for the backend.

    Usage:
        record = process_patient(pdf_paths, patient_id="P001")
        record = process_patient([], texts=[text1, text2, text3])
    """
    from src.ingestion.merger import merge_documents, PatientRecord

    documents: list[ExtractedDocument] = []

    if sources:
        documents.extend(process_pdfs(sources))

    if texts:
        for i, text in enumerate(texts):
            doc = process_text(text, document_id=f"text_{i}")
            documents.append(doc)

    return merge_documents(documents, patient_id=patient_id)


def _extract_by_type(text, doc_id, document_type):
    """Route text to the right extractor(s) based on document type."""
    medications, diagnoses, allergies = [], [], []
    procedures, implants, labs = [], [], []
    anesthesia_history, cardiac = [], []

    if document_type == "discharge_summary":
        medications = extract_medications(text, doc_id, document_type)
        diagnoses = extract_diagnoses(text, doc_id, document_type)
        allergies = extract_allergies(text, doc_id, document_type)
        labs = extract_labs(text, doc_id, document_type)

    elif document_type == "operative_note":
        procedures = extract_procedures(text, doc_id, document_type)
        implants = extract_implants(text, doc_id, document_type)

    elif document_type == "anesthesia_record":
        anesthesia_history = extract_anesthesia(text, doc_id, document_type)

    elif document_type == "cardiology_consult":
        cardiac = extract_cardiac(text, doc_id, document_type)
        medications = extract_cardiac_medications(text, doc_id, document_type)

    elif document_type == "lab_report":
        labs = extract_labs(text, doc_id, document_type)

    elif document_type == "medication_list":
        medications = extract_medications(text, doc_id, document_type)
        allergies = extract_allergies(text, doc_id, document_type)

    else:
        # unknown — run all extractors, accept lower confidence
        medications = extract_medications(text, doc_id, document_type)
        diagnoses = extract_diagnoses(text, doc_id, document_type)
        allergies = extract_allergies(text, doc_id, document_type)
        labs = extract_labs(text, doc_id, document_type)

    return medications, diagnoses, allergies, procedures, implants, labs, anesthesia_history, cardiac


def _assess_quality(text, medications, diagnoses, labs, document_type) -> tuple[float, list[str]]:
    """Estimate extraction confidence and surface actionable warnings."""
    warnings = []
    score = 1.0

    text_lower = text.lower()

    # Short document — likely poor quality scan
    if len(text) < 300:
        score -= 0.3
        warnings.append("Document text very short — may be a poor quality scan")

    # Expected extractions missing
    if document_type in ("discharge_summary", "medication_list") and not medications:
        score -= 0.2
        warnings.append("No medications extracted from discharge summary")

    if document_type == "lab_report" and not labs:
        score -= 0.2
        warnings.append("No relevant lab values extracted from lab report")

    # Clinical safety gaps
    anticoag_mentioned = any(
        kw in text_lower
        for kw in ["warfarin", "apixaban", "rivaroxaban", "dabigatran", "heparin", "anticoagulant"]
    )
    has_inr = any(lab.test_name.upper() == "INR" for lab in labs)
    if anticoag_mentioned and not has_inr:
        warnings.append("Anticoagulant mentioned but no INR found — verify coagulation status")

    diabetes_mentioned = any(kw in text_lower for kw in ["diabetes", "diabetic", "hba1c"])
    has_hba1c = any(lab.test_name == "HbA1c" for lab in labs)
    if diabetes_mentioned and not has_hba1c:
        warnings.append("Diabetes mentioned but no HbA1c found — verify glycemic control")

    pacemaker_mentioned = any(kw in text_lower for kw in ["pacemaker", "icd", "defibrillator"])
    if pacemaker_mentioned:
        warnings.append("Cardiac device mentioned — verify device type and last check date")

    return round(max(0.0, min(1.0, score)), 2), warnings
