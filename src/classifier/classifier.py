"""
Document type classifier using Claude Haiku (few-shot, fast, cheap).
Falls back to keyword heuristics if the API is unavailable.
"""
import os
import re
from typing import Literal

import anthropic

DocumentType = Literal[
    "discharge_summary",
    "operative_note",
    "anesthesia_record",
    "cardiology_consult",
    "lab_report",
    "medication_list",
    "unknown",
]

VALID_TYPES = set(DocumentType.__args__)  # type: ignore[attr-defined]

_SYSTEM = """\
You are a medical document classifier. Classify the document excerpt into exactly one type.

Valid types:
- discharge_summary   : hospital discharge notes, admission/discharge summaries
- operative_note      : surgery notes, procedure notes, operative reports, implants
- anesthesia_record   : anesthesia records, pre-op anesthesia assessments, ASA scores
- cardiology_consult  : cardiology consultations, echo reports, ECG interpretations
- lab_report          : laboratory results, blood work, pathology, radiology results
- medication_list     : medication reconciliation lists, prescription records
- unknown             : anything that does not fit the above

Respond with ONLY the type label, no explanation."""

# Few-shot examples built from MT Samples patterns
_FEW_SHOT = [
    {"role": "user", "content": "DISCHARGE SUMMARY\nPatient was admitted with COPD exacerbation. Medications on discharge: Salbutamol, Prednisone. Follow-up in 2 weeks."},
    {"role": "assistant", "content": "discharge_summary"},
    {"role": "user", "content": "OPERATIVE REPORT\nProcedure: Right total knee replacement. Implant: Zimmer NexGen size 4. Tourniquet applied. No intraoperative complications."},
    {"role": "assistant", "content": "operative_note"},
    {"role": "user", "content": "ANESTHESIA RECORD\nASA Class III. General endotracheal anesthesia. Intubation: grade 1 view. No complications. Patient extubated in OR."},
    {"role": "assistant", "content": "anesthesia_record"},
    {"role": "user", "content": "CARDIOLOGY CONSULTATION\nEchocardiogram: EF 45%. Mild LV dysfunction. History of MI 2019. Currently on bisoprolol 5mg."},
    {"role": "assistant", "content": "cardiology_consult"},
    {"role": "user", "content": "LABORATORY RESULTS\nINR: 2.8 (H). Creatinine: 1.4 mg/dL. Hemoglobin: 10.2 g/dL. Platelets: 145 K/uL."},
    {"role": "assistant", "content": "lab_report"},
    {"role": "user", "content": "MEDICATION LIST\nWarfarin 5mg daily. Metoprolol 25mg BID. Lisinopril 10mg daily. Last filled: 2024-01-15."},
    {"role": "assistant", "content": "medication_list"},
]

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    return _client


def classify(text: str, use_first_chars: int = 800) -> DocumentType:
    """
    Classify a document from its text.
    Uses the first `use_first_chars` characters — headers carry the most signal.
    Falls back to keyword heuristics if the API call fails.
    """
    excerpt = text[:use_first_chars].strip()
    try:
        return _classify_with_claude(excerpt)
    except Exception:
        return _classify_heuristic(excerpt)


def _classify_with_claude(excerpt: str) -> DocumentType:
    client = _get_client()
    messages = _FEW_SHOT + [{"role": "user", "content": excerpt}]
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=20,
        system=_SYSTEM,
        messages=messages,
    )
    label = response.content[0].text.strip().lower()
    return label if label in VALID_TYPES else "unknown"  # type: ignore[return-value]


def _classify_heuristic(text: str) -> DocumentType:
    """Keyword fallback — no API needed."""
    t = text.lower()
    if re.search(r"\b(discharge|admission|admitted|discharge summary)\b", t):
        return "discharge_summary"
    if re.search(r"\b(operative|operation|procedure|incision|implant|surgeon)\b", t):
        return "operative_note"
    if re.search(r"\b(anesthesia|anaesthesia|asa class|intubat|airway)\b", t):
        return "anesthesia_record"
    if re.search(r"\b(cardiology|echocardiogram|ejection fraction|ef\s*\d|ecg|ekg)\b", t):
        return "cardiology_consult"
    if re.search(r"\b(laboratory|lab results?|inr|creatinine|hemoglobin|hba1c|platelets)\b", t):
        return "lab_report"
    if re.search(r"\b(medication list|medications?:|drug list|prescription)\b", t):
        return "medication_list"
    return "unknown"


async def classify_async(text: str) -> DocumentType:
    """Async wrapper for use in the parallel pipeline."""
    import asyncio
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, classify, text)
