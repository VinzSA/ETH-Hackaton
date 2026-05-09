"""
Diagnosis normalizer: maps free-text diagnoses to ICD-10 codes.

Priority:
1. Local lookup table (common surgical comorbidities)
2. simple_icd_10 fuzzy search
3. Claude fallback
"""
import os
import re
from functools import lru_cache

import anthropic

_DIAGNOSIS_TABLE: dict[str, str] = {
    # Cardiac
    "atrial fibrillation": "I48.91",
    "af": "I48.91",
    "heart failure": "I50.9",
    "congestive heart failure": "I50.9",
    "chf": "I50.9",
    "myocardial infarction": "I21.9",
    "mi": "I21.9",
    "coronary artery disease": "I25.10",
    "cad": "I25.10",
    "hypertension": "I10",
    "hypertensive": "I10",
    # Pulmonary
    "copd": "J44.1",
    "chronic obstructive pulmonary disease": "J44.1",
    "asthma": "J45.909",
    "pulmonary embolism": "I26.99",
    "pe": "I26.99",
    "deep vein thrombosis": "I82.409",
    "dvt": "I82.409",
    # Metabolic
    "type 2 diabetes": "E11.9",
    "diabetes mellitus type 2": "E11.9",
    "diabetes": "E11.9",
    "type 1 diabetes": "E10.9",
    "hypothyroidism": "E03.9",
    "hyperthyroidism": "E05.90",
    "obesity": "E66.9",
    # Renal
    "chronic kidney disease": "N18.9",
    "ckd": "N18.9",
    "renal failure": "N19",
    "acute kidney injury": "N17.9",
    "aki": "N17.9",
    # Neurological
    "stroke": "I63.9",
    "cerebrovascular accident": "I63.9",
    "cva": "I63.9",
    "tia": "G45.9",
    "transient ischemic attack": "G45.9",
    "dementia": "F03.90",
    "parkinson": "G20",
    # Musculoskeletal
    "osteoarthritis": "M19.90",
    "osteoporosis": "M81.0",
    "rheumatoid arthritis": "M06.9",
    # Coagulation
    "coagulopathy": "D68.9",
    "thrombocytopenia": "D69.6",
    "anemia": "D64.9",
    # GI
    "gastrointestinal bleeding": "K92.2",
    "gi bleed": "K92.2",
    "peptic ulcer": "K27.9",
    # Fracture
    "femur fracture": "S72.009A",
    "hip fracture": "S72.009A",
}

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    return _client


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", text.lower()).strip()


def lookup_icd10(description: str) -> str | None:
    """Return ICD-10 code for a diagnosis description, or None if not found."""
    key = _normalize(description)

    # Direct table hit
    if key in _DIAGNOSIS_TABLE:
        return _DIAGNOSIS_TABLE[key]

    # Partial match
    for table_key, code in _DIAGNOSIS_TABLE.items():
        if table_key in key:
            return code

    # simple_icd_10 search
    result = _icd10_search(description)
    if result:
        return result

    # Claude fallback
    return _claude_icd10(description)


def _icd10_search(description: str) -> str | None:
    try:
        import simple_icd_10 as icd
        # Search for codes matching the description
        results = icd.get_descendants("Z00-ZZZ")  # get all codes
        # simple_icd_10 doesn't have fuzzy search built in, use keyword matching
        desc_lower = description.lower()
        for code in results[:500]:  # limit to avoid performance issues
            try:
                code_desc = icd.get_description(code).lower()
                if any(word in code_desc for word in desc_lower.split() if len(word) > 4):
                    return code
            except Exception:
                continue
    except Exception:
        pass
    return None


@lru_cache(maxsize=256)
def _claude_icd10(description: str) -> str | None:
    try:
        client = _get_client()
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=20,
            system=(
                "You are a medical coder. Given a diagnosis, return ONLY the most specific "
                "ICD-10-CM code (e.g. I48.91). If unknown, return null. No explanation."
            ),
            messages=[{"role": "user", "content": description}],
        )
        code = response.content[0].text.strip()
        # Validate format: letter + digits + optional dot + digits
        if re.match(r"^[A-Z]\d{2}(\.\d+)?$", code):
            return code
        return None
    except Exception:
        return None
