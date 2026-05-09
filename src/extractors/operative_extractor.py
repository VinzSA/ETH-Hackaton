"""
Operative note extractor.
Extracts: procedures performed, implants installed, complications.
"""
from src.extractors.base_extractor import claude_extract, make_source_ref
from src.schema.preop_brief import Implant, Procedure

_SYSTEM_PROC = """\
You are a surgical procedure extractor for pre-op assessment.

Extract all procedures performed from the operative note.

Return a JSON array. Each object:
{
  "name": string,
  "cpt_code": string | null,
  "ops_code": string | null,
  "chop_code": string | null,
  "procedure_date": string | null,  // ISO 8601 if present
  "surgeon": string | null,
  "complications": string | null,
  "raw_text": string  // exact phrase (max 80 chars)
}
If none found, return [].
Respond with ONLY the JSON array."""

_SYSTEM_IMPL = """\
You are an implant extractor for surgical pre-op assessment.

Extract all implants, hardware, or prostheses installed. Include: joint replacements,
pacemakers, ICDs, mesh, stents, plates, screws, rods.

Return a JSON array. Each object:
{
  "description": string,        // e.g. "Right total knee replacement, Zimmer NexGen"
  "manufacturer": string | null,
  "model": string | null,
  "implanted_date": string | null,  // ISO 8601 if present
  "body_site": string | null,
  "raw_text": string  // exact phrase (max 80 chars)
}
If none found, return [].
Respond with ONLY the JSON array."""


def extract_procedures(
    text: str,
    document_id: str,
    document_type: str = "operative_note",
    page: int = 1,
    global_char_offset: int = 0,
) -> list[Procedure]:
    raw = claude_extract(_SYSTEM_PROC, text, document_id)
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
                Procedure(
                    name=item["name"],
                    cpt_code=item.get("cpt_code"),
                    ops_code=item.get("ops_code"),
                    chop_code=item.get("chop_code"),
                    procedure_date=item.get("procedure_date"),
                    surgeon=item.get("surgeon"),
                    complications=item.get("complications"),
                    source=source,
                )
            )
        except (KeyError, TypeError):
            continue

    return results


def extract_implants(
    text: str,
    document_id: str,
    document_type: str = "operative_note",
    page: int = 1,
    global_char_offset: int = 0,
) -> list[Implant]:
    raw = claude_extract(_SYSTEM_IMPL, text, document_id)
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
                Implant(
                    description=item["description"],
                    manufacturer=item.get("manufacturer"),
                    model=item.get("model"),
                    implanted_date=item.get("implanted_date"),
                    body_site=item.get("body_site"),
                    source=source,
                )
            )
        except (KeyError, TypeError):
            continue

    return results
