"""
Cardiology consult extractor.
Extracts: EF%, NYHA class, MI history, stents, AF, current cardiac meds.
"""
from src.extractors.base_extractor import claude_extract, make_source_ref
from src.schema.preop_brief import CardiacAssessment, Medication

_SYSTEM_CARDIAC = """\
You are a cardiology extractor for surgical pre-op risk assessment.

Extract cardiac assessment data from the cardiology consult or echo report.

Return a JSON object (not an array):
{
  "ejection_fraction_pct": number | null,   // as a percentage, e.g. 45.0
  "nyha_class": integer | null,             // 1-4
  "has_history_mi": boolean,
  "has_stents": boolean,
  "has_atrial_fibrillation": boolean,
  "last_assessment_date": string | null,    // ISO 8601 if present
  "raw_text": string                        // most relevant phrase (max 80 chars)
}
Respond with ONLY the JSON object."""

_SYSTEM_CARDIAC_MEDS = """\
You are a medication extractor focused on cardiac medications for surgical pre-op assessment.

Extract all cardiac medications from the cardiology consult (beta-blockers, ACE inhibitors,
ARBs, anticoagulants, antiplatelets, antiarrhythmics, statins, diuretics).

Return a JSON array. Each object:
{
  "name": string,
  "dose": string | null,
  "frequency": string | null,
  "is_anticoagulant": boolean,
  "is_antiplatelet": boolean,
  "raw_text": string  // exact phrase (max 80 chars)
}
If none found, return [].
Respond with ONLY the JSON array."""


def extract_cardiac(
    text: str,
    document_id: str,
    document_type: str = "cardiology_consult",
    page: int = 1,
    global_char_offset: int = 0,
) -> list[CardiacAssessment]:
    raw = claude_extract(_SYSTEM_CARDIAC, text, document_id)
    if not raw or not isinstance(raw, dict):
        return []

    try:
        raw_text = raw.get("raw_text", "cardiac assessment")
        source = make_source_ref(
            document_id=document_id,
            document_type=document_type,
            text=text,
            entity_text=raw_text,
            page=page,
            global_char_offset=global_char_offset,
        )

        ef = raw.get("ejection_fraction_pct")
        if ef is not None:
            try:
                ef = float(ef)
            except (ValueError, TypeError):
                ef = None

        nyha = raw.get("nyha_class")
        if nyha is not None:
            try:
                nyha = int(nyha)
                if not 1 <= nyha <= 4:
                    nyha = None
            except (ValueError, TypeError):
                nyha = None

        return [
            CardiacAssessment(
                ejection_fraction_pct=ef,
                nyha_class=nyha,
                has_history_mi=bool(raw.get("has_history_mi", False)),
                has_stents=bool(raw.get("has_stents", False)),
                has_atrial_fibrillation=bool(raw.get("has_atrial_fibrillation", False)),
                last_assessment_date=raw.get("last_assessment_date"),
                source=source,
            )
        ]
    except (KeyError, TypeError):
        return []


def extract_cardiac_medications(
    text: str,
    document_id: str,
    document_type: str = "cardiology_consult",
    page: int = 1,
    global_char_offset: int = 0,
) -> list[Medication]:
    from src.extractors.discharge_extractor import extract_medications
    # Reuse the medication extractor — same schema, same logic
    return extract_medications(text, document_id, document_type, page, global_char_offset)
