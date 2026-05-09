"""
Lab report extractor.
Pulls only the 6 surgical-relevant lab values: INR, creatinine, HbA1c,
hemoglobin, platelets, ejection fraction.
"""
from src.extractors.base_extractor import claude_extract, make_source_ref
from src.schema.preop_brief import LabValue, SourceRef

_SYSTEM = """\
You are a medical lab extractor for surgical pre-op assessment.

Extract ONLY these lab values if present: INR, creatinine, HbA1c, hemoglobin, platelets, ejection fraction (EF).
Ignore all other lab values.

Return a JSON array. Each object must have:
{
  "test_name": string,         // standardized: "INR" | "creatinine" | "HbA1c" | "hemoglobin" | "platelets" | "EF"
  "value": number,
  "unit": string,
  "reference_range": string | null,
  "measured_date": string | null,  // ISO 8601 if available, else null
  "raw_text": string               // the exact phrase you found this in (max 80 chars)
}

If no relevant labs found, return [].
Respond with ONLY the JSON array."""

LOINC_MAP = {
    "INR": "34714-6",
    "creatinine": "2160-0",
    "HbA1c": "4548-4",
    "hemoglobin": "718-7",
    "platelets": "777-3",
    "EF": "10230-1",
}


def extract_labs(
    text: str,
    document_id: str,
    document_type: str = "lab_report",
    page: int = 1,
    global_char_offset: int = 0,
) -> list[LabValue]:
    raw = claude_extract(_SYSTEM, text, document_id)
    if not raw or not isinstance(raw, list):
        return []

    results = []
    for item in raw:
        try:
            name = item.get("test_name", "").strip()
            value = float(item["value"])
            unit = item.get("unit", "").strip()
            raw_text = item.get("raw_text", name)

            source = make_source_ref(
                document_id=document_id,
                document_type=document_type,
                text=text,
                entity_text=raw_text,
                page=page,
                global_char_offset=global_char_offset,
            )

            results.append(
                LabValue(
                    test_name=name,
                    loinc_code=LOINC_MAP.get(name),
                    value=value,
                    unit=unit,
                    reference_range=item.get("reference_range"),
                    measured_date=item.get("measured_date"),
                    source=source,
                )
            )
        except (KeyError, ValueError, TypeError):
            continue

    return results
