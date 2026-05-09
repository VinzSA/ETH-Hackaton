"""
Anesthesia record extractor.
Extracts: ASA score, airway notes, anesthesia type, complications.
"""
from src.extractors.base_extractor import claude_extract, make_source_ref
from src.schema.preop_brief import AnesthesiaHistory

_SYSTEM = """\
You are an anesthesia record extractor for surgical pre-op assessment.

Extract anesthesia history from the record.

Return a JSON object (not an array):
{
  "asa_score": integer | null,       // 1-5
  "anesthesia_type": string | null,  // e.g. "general endotracheal", "spinal", "epidural"
  "airway_notes": string | null,     // Mallampati score, difficult airway, intubation grade
  "complications": string | null,    // e.g. "prolonged intubation", "hypotension", "PONV"
  "procedure_date": string | null,   // ISO 8601 if present
  "raw_text": string                 // most relevant phrase from the record (max 80 chars)
}
Respond with ONLY the JSON object."""


def extract_anesthesia(
    text: str,
    document_id: str,
    document_type: str = "anesthesia_record",
    page: int = 1,
    global_char_offset: int = 0,
) -> list[AnesthesiaHistory]:
    raw = claude_extract(_SYSTEM, text, document_id)
    if not raw or not isinstance(raw, dict):
        return []

    try:
        raw_text = raw.get("raw_text", "anesthesia")
        source = make_source_ref(
            document_id=document_id,
            document_type=document_type,
            text=text,
            entity_text=raw_text,
            page=page,
            global_char_offset=global_char_offset,
        )

        asa = raw.get("asa_score")
        if asa is not None:
            try:
                asa = int(asa)
                if not 1 <= asa <= 5:
                    asa = None
            except (ValueError, TypeError):
                asa = None

        record = AnesthesiaHistory(
            asa_score=asa,
            anesthesia_type=raw.get("anesthesia_type"),
            airway_notes=raw.get("airway_notes"),
            complications=raw.get("complications"),
            procedure_date=raw.get("procedure_date"),
            source=source,
        )
        return [record]
    except (KeyError, TypeError):
        return []
