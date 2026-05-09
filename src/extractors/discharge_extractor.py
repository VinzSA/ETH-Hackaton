"""
Discharge summary extractor.
Extracts: active diagnoses, current medications, allergies.
"""
from src.extractors.base_extractor import claude_extract, make_source_ref
from src.schema.preop_brief import Allergy, Diagnosis, Medication

_SYSTEM_MEDS = """\
You are a medication extractor for surgical pre-op risk assessment.

Extract all current medications from the discharge summary.
Return a JSON array. Each object:
{
  "name": string,
  "dose": string | null,        // e.g. "5mg"
  "frequency": string | null,   // e.g. "BID", "daily"
  "route": string | null,       // e.g. "oral", "IV"
  "last_dose_datetime": string | null,  // ISO 8601 if present
  "indication": string | null,
  "is_anticoagulant": boolean,  // warfarin, heparin, enoxaparin, fondaparinux
  "is_antiplatelet": boolean,   // aspirin, clopidogrel, ticagrelor, prasugrel
  "raw_text": string            // exact phrase (max 80 chars)
}
If none found, return [].
Respond with ONLY the JSON array."""

_SYSTEM_DIAG = """\
You are a diagnosis extractor for surgical pre-op risk assessment.

Extract all ACTIVE diagnoses from the discharge summary. Exclude resolved or historical conditions
unless they are directly relevant to surgery (e.g. prior MI, diabetes, renal disease, COPD).

Return a JSON array. Each object:
{
  "description": string,
  "icd10_code": string | null,  // provide if confident, else null
  "is_active": boolean,
  "onset_date": string | null,  // ISO 8601 if present
  "raw_text": string            // exact phrase (max 80 chars)
}
If none found, return [].
Respond with ONLY the JSON array."""

_SYSTEM_ALLERGY = """\
You are an allergy extractor for surgical pre-op assessment.

Extract all documented allergies and adverse drug reactions.

Return a JSON array. Each object:
{
  "substance": string,
  "reaction": string | null,
  "severity": "mild" | "moderate" | "severe" | "anaphylaxis" | null,
  "raw_text": string  // exact phrase (max 80 chars)
}
If none found, return [].
Respond with ONLY the JSON array."""


def extract_medications(
    text: str,
    document_id: str,
    document_type: str = "discharge_summary",
    page: int = 1,
    global_char_offset: int = 0,
) -> list[Medication]:
    raw = claude_extract(_SYSTEM_MEDS, text, document_id)
    if not raw or not isinstance(raw, list):
        return []

    results = []
    for item in raw:
        try:
            raw_text = item.get("raw_text", item.get("name", ""))
            source = make_source_ref(
                document_id=document_id,
                document_type=document_type,
                text=text,
                entity_text=raw_text,
                page=page,
                global_char_offset=global_char_offset,
            )
            results.append(
                Medication(
                    name=item["name"],
                    dose=item.get("dose"),
                    frequency=item.get("frequency"),
                    route=item.get("route"),
                    last_dose_datetime=item.get("last_dose_datetime"),
                    indication=item.get("indication"),
                    is_anticoagulant=bool(item.get("is_anticoagulant", False)),
                    is_antiplatelet=bool(item.get("is_antiplatelet", False)),
                    source=source,
                )
            )
        except (KeyError, TypeError):
            continue

    return results


def extract_diagnoses(
    text: str,
    document_id: str,
    document_type: str = "discharge_summary",
    page: int = 1,
    global_char_offset: int = 0,
) -> list[Diagnosis]:
    raw = claude_extract(_SYSTEM_DIAG, text, document_id)
    if not raw or not isinstance(raw, list):
        return []

    results = []
    for item in raw:
        try:
            raw_text = item.get("raw_text", item.get("description", ""))
            source = make_source_ref(
                document_id=document_id,
                document_type=document_type,
                text=text,
                entity_text=raw_text,
                page=page,
                global_char_offset=global_char_offset,
            )
            results.append(
                Diagnosis(
                    description=item["description"],
                    icd10_code=item.get("icd10_code"),
                    is_active=bool(item.get("is_active", True)),
                    onset_date=item.get("onset_date"),
                    source=source,
                )
            )
        except (KeyError, TypeError):
            continue

    return results


def extract_allergies(
    text: str,
    document_id: str,
    document_type: str = "discharge_summary",
    page: int = 1,
    global_char_offset: int = 0,
) -> list[Allergy]:
    raw = claude_extract(_SYSTEM_ALLERGY, text, document_id)
    if not raw or not isinstance(raw, list):
        return []

    valid_severities = {"mild", "moderate", "severe", "anaphylaxis"}
    results = []
    for item in raw:
        try:
            raw_text = item.get("raw_text", item.get("substance", ""))
            source = make_source_ref(
                document_id=document_id,
                document_type=document_type,
                text=text,
                entity_text=raw_text,
                page=page,
                global_char_offset=global_char_offset,
            )
            severity = item.get("severity")
            if severity not in valid_severities:
                severity = None

            results.append(
                Allergy(
                    substance=item["substance"],
                    reaction=item.get("reaction"),
                    severity=severity,
                    source=source,
                )
            )
        except (KeyError, TypeError):
            continue

    return results
